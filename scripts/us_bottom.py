"""Daily US market bottom watch. Missing or mismatched observations never pass."""
import csv, datetime as dt, io, json, math, pathlib, urllib.request, time
from statistics import mean
from zoneinfo import ZoneInfo

FRED="https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500,VIXCLS"
CBOE="https://cdn.cboe.com/data/us/options/market_statistics/daily/"
OUT=pathlib.Path("data/us_bottom.json")
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=15) as r:
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
    gate=drawdown is not None and min(100*(x["spx"]/max(y["spx"] for y in rows[max(0,j-251):j+1])-1) for j,x in enumerate(rows) if j>=max(251,n-20))<=-10
    return {"date":r["date"],"score":score,"coverage":coverage,"drawdown":drawdown,"correctionGate":gate,"ma20":ma,"priorLow":low,"pcrMA10":pma,"vixPeak20":peak,"rules":[{"name":a,"weight":b,"pass":c} for a,b,c in rules],"latest":r}
def main():
    now=dt.datetime.now(ZoneInfo("America/New_York"))
    # Do not include the ongoing regular session.
    cutoff=now.date() if now.hour>=18 else now.date()-dt.timedelta(days=1)
    rows=[]
    for r in csv.DictReader(io.StringIO(get(FRED))):
        date=r.get("observation_date") or r.get("DATE")
        p=number(r.get("SP500"))
        if date and p and date<=cutoff.isoformat():
            rows.append({"date":date,"spx":p,"vix":number(r.get("VIXCLS"))})
    rows.sort(key=lambda r:r["date"])
    if len(rows)<252: raise RuntimeError("FRED SP500 history insufficient")
    errors=[]
    for r in rows[-30:]:
        try: r.update(parse_options(json.loads(get(CBOE+r["date"]+"_daily_options"))))
        except Exception as e: errors.append(r["date"]+": "+str(e)[:160])
        time.sleep(.15)
    report=evaluate(rows)
    report.update({"generatedAt":dt.datetime.now(dt.timezone.utc).isoformat(),"history":rows[-30:],"errors":errors,"sources":{"price":FRED,"options":CBOE}})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False),encoding="utf-8")
if __name__=="__main__": main()
