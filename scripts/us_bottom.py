"""Daily US market bottom watch. Missing or mismatched observations never pass."""
import csv, datetime as dt, io, json, math, pathlib, urllib.request, time, re, html
from concurrent.futures import ThreadPoolExecutor
from statistics import mean
from zoneinfo import ZoneInfo

FRED="https://fred.stlouisfed.org/graph/fredgraph.csv?id="
FRED_TABLE="https://fred.stlouisfed.org/data/"
VIX_CSV="https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
SPX_JSON="https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_SPX.json"
CACHE=pathlib.Path(".us-bottom-cache/last.json")
SEED=pathlib.Path("data/us_bottom_seed.json")
CBOE="https://cdn.cboe.com/data/us/options/market_statistics/daily/"
OUT=pathlib.Path("data/us_bottom.json")
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=12) as r:
        return r.read().decode("utf-8-sig")
def number(x):
    try:
        v=float(str(x).replace(",",""))
        return v if math.isfinite(v) and v>0 else None
    except (TypeError,ValueError): return None
def parse_options(data):
    ratios={r["name"]:number(r["value"]) for r in data["ratios"]}
    name=next((k for k in ("SPX + SPXW + SPXO","SPX + SPXW") if k in data),None)
    total=ratios.get("TOTAL PUT/CALL RATIO")
    if not total: raise ValueError("missing total PCR")
    oi=next((r for r in data.get(name,[]) if r.get("name")=="OPEN INTEREST"),{})
    c,p=number(oi.get("call")),number(oi.get("put"))
    return {"pcr":total,"equityPCR":ratios.get("EQUITY PUT/CALL RATIO"),"spxPCR":ratios.get(str(name)+" PUT/CALL RATIO"),"oi":p/c if c and p else None,"oiCall":c,"oiPut":p,"oiScope":name}
def evaluate(rows):
    n=len(rows)
    if not n: return None
    r=rows[-1]; price=r["spx"]; v=r.get("vix")
    def vals(key,k):
        a=[x.get(key) for x in rows[-k:]]
        return a if len(a)==k and all(x is not None for x in a) else None
    v20=vals("vix",20); v3=vals("vix",3); p20=vals("pcr",20); p11=vals("pcr",11); oi3=vals("oi",3)
    scope_ok=len({x.get("oiScope") for x in rows[-3:]})==1
    peak=max(v20) if v20 else None
    # Prior 20 completed sessions, excluding today. A confirmed rebound requires
    # three closes above the prior 20-session low (known before those closes).
    prior=rows[-23:-3]; low=min(x["spx"] for x in prior) if len(prior)==20 else None
    ma=mean(x["spx"] for x in rows[-20:]) if n>=20 else None
    pma=mean(p11[-10:]) if p11 else None
    prevma=mean(p11[:10]) if p11 else None
    drawdown=100*(price/max(x["spx"] for x in rows[-252:])-1) if n>=252 else None
    def test(available,condition): return bool(condition) if available else None
    rules=[
      ("VIX 近20日收盤曾達35",15,test(v20,peak is not None and peak>=35)),
      ("VIX 自高點回落至30以下",10,test(v20 and v,peak is not None and v is not None and peak>=35 and v<30)),
      ("VIX 連續3日低於25",15,test(v3,v3 is not None and max(v3)<25)),
      ("整體PCR近20日曾達1.1",10,test(p20,p20 is not None and max(p20)>=1.1)),
      ("PCR 10日均線高檔反轉",15,test(p20 and p11,p20 is not None and p11 is not None and max(mean(p20[i:i+10]) for i in range(11))>=1.1 and pma<prevma)),
      ("SPX系列OI比連續下降",10,test(oi3 and scope_ok,oi3 is not None and oi3[0]>oi3[1]>oi3[2])),
      ("近3日收盤守住此前20日低點",15,test(low is not None,low is not None and min(x["spx"] for x in rows[-3:])>low)),
      ("S&P 500 收盤站上MA20",10,test(ma is not None,ma is not None and price>ma))]
    score=sum(w for _,w,s in rules if s is True)
    coverage=sum(w for _,w,s in rules if s is not None)
    gate=None if n<271 else min(100*(x["spx"]/max(y["spx"] for y in rows[max(0,j-251):j+1])-1) for j,x in enumerate(rows) if j>=max(251,n-20))<=-10
    return {"date":r["date"],"score":score,"coverage":coverage,"drawdown":drawdown,"correctionGate":gate,"ma20":ma,"priorLow":low,"pcrMA10":pma,"vixPeak20":peak,"rules":[{"name":a,"weight":b,"pass":c} for a,b,c in rules],"latest":r}
def fred_series(symbol):
    # Separate requests avoid combined CSV failures and permit independent fallback.
    errors=[]
    try:
        rows={}
        for r in csv.DictReader(io.StringIO(get(FRED+symbol))):
            date=r.get("observation_date") or r.get("DATE") or r.get("date")
            value=number(r.get(symbol))
            if date and value: rows[date]=value
        if len(rows)>=252: return rows,FRED+symbol
        raise ValueError("insufficient CSV observations: "+str(len(rows)))
    except Exception as e: errors.append(str(e))
    try:
        raw=html.unescape(re.sub(r"<[^>]*>"," ",get(FRED_TABLE+symbol)))
        rows={d:number(v) for d,v in re.findall(r"(\d{4}-\d{2}-\d{2})\s+([0-9]+(?:\.[0-9]+)?)(?=\s|$)",raw)}
        rows={d:v for d,v in rows.items() if v is not None}
        if len(rows)>=252: return rows,FRED_TABLE+symbol
        raise ValueError("insufficient table observations: "+str(len(rows)))
    except Exception as e: errors.append(str(e))
    if symbol=="VIXCLS":
        try:
            rows={}
            for r in csv.DictReader(io.StringIO(get(VIX_CSV))):
                d=dt.datetime.strptime(r["DATE"],"%m/%d/%Y").date().isoformat()
                v=number(r["CLOSE"])
                if v: rows[d]=v
            if len(rows)>=252:return rows,VIX_CSV
        except Exception as e: errors.append(str(e))
    if symbol=="SP500":
        try:
            rows={}
            for r in json.loads(get(SPX_JSON))["data"]:
                d=str(r.get("date") or r.get("datetime") or "")[:10]
                v=number(r.get("close"))
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}",d) and v: rows[d]=v
            if len(rows)>=252:return rows,SPX_JSON
        except Exception as e: errors.append(str(e))
    raise RuntimeError(symbol+": "+"; ".join(errors))
def read_previous():
    for path in (CACHE, OUT, SEED):
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("history"),list) and data["history"]: return data
        except (OSError,ValueError,TypeError): pass
    return {}
def main():
    now=dt.datetime.now(ZoneInfo("America/New_York"))
    # Do not include the ongoing regular session.
    cutoff=now.date() if now.hour>=18 else now.date()-dt.timedelta(days=1)
    errors=[]
    previous=read_previous()
    prev={r["date"]:r for r in previous.get("history",[]) if r.get("date")}
    sources={}
    series={}
    for key,symbol in (("spx","SP500"),("vix","VIXCLS")):
        try: series[key],sources[key]=fred_series(symbol)
        except Exception as e:
            errors.append(str(e))
            print("WARN:",e,flush=True)
            series[key]={d:r[key] for d,r in prev.items() if r.get(key) is not None}
            sources[key]=previous.get("sources",{}).get(key,"previous verified data")
    rows=[]
    for d,p in sorted(series["spx"].items()):
        if d>cutoff.isoformat(): continue
        r={"date":d,"spx":p,"vix":series["vix"].get(d)}
        old=prev.get(d,{})
        for k in ("pcr","equityPCR","spxPCR","oi","oiCall","oiPut","oiScope"):
            if old.get(k) is not None:r[k]=old[k]
        rows.append(r)
    if not rows:
        raise RuntimeError("No verified S&P 500 observations from sources or cache")
    def options(r):
        # Cache historical verified values; always recheck the latest three sessions.
        try:
            r.update(parse_options(json.loads(get(CBOE+r["date"]+"_daily_options"))))
        except Exception as e:
            return r["date"]+" CBOE: "+str(e)[:180]
        return None
    recent=rows[-30:]
    targets=[r for i,r in enumerate(recent) if i>=len(recent)-3 or r.get("pcr") is None or r.get("oi") is None]
    with ThreadPoolExecutor(max_workers=4) as pool:
        errors.extend(e for e in pool.map(options,targets) if e)
    # An independently published VIX value must not be attached to a different SPX date.
    report=evaluate(rows)
    report.update({"generatedAt":dt.datetime.now(dt.timezone.utc).isoformat(),"history":rows[-30:],"errors":errors,"sources":{**sources,"options":CBOE},"historyCount":len(rows),"fallback":len(rows)<271 or any("SP500:" in e or "VIXCLS:" in e for e in errors)})
    # Store enough verified history for future price-source outages; public report is lightweight.
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps({**report,"history":rows[-300:]},ensure_ascii=False,allow_nan=False),encoding="utf-8")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    print("US bottom: date",report["date"],"coverage",report["coverage"],"sessions",len(rows),"errors",len(errors),flush=True)
    for e in errors: print("WARN:",e,flush=True)
if __name__=="__main__": main()
