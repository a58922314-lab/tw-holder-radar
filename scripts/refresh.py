#!/usr/bin/env python3
"""TWSE / TPEX / TDCC snapshot updater. Fails closed when data is incomplete."""
import csv,io,json,re,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict
try:
    from scripts.margin import fill_week_margin
    from scripts.a1_institutional import collect_institutional,weekly_institutional
    from scripts.a1_archive_backfill import verified_archive_backfill
except ModuleNotFoundError:
    from margin import fill_week_margin
    from a1_institutional import collect_institutional,weekly_institutional
    from a1_archive_backfill import verified_archive_backfill

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
TDCC=['https://opendata.tdcc.com.tw/getOD.ashx?id=1-5','https://openapi.tdcc.com.tw/v1/opendata/1-5']
MASTER={'上市':['https://openapi.twse.com.tw/v1/opendata/t187ap03_L'],'上櫃':['https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O','https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv']}
CLOSE={'上市':'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL','上櫃':'https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes'}
def download(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; TaiwanHolderRadar/2.1)','Accept':'application/json,text/csv,*/*'}),timeout=35) as r:
                return r.read()
        except Exception as e:
            print('Download warning:',url,str(e));time.sleep(2*(i+1))
    raise RuntimeError('Official endpoint unavailable: '+url)
def rows(raw):
    s=raw.decode('utf-8-sig').strip()
    if s.startswith(('[','{')):
        x=json.loads(s)
        return x if isinstance(x,list) else x.get('data',x.get('Data',[]))
    return list(csv.DictReader(io.StringIO(s)))
def read(name,default):
    p=DATA/name
    return json.loads(p.read_text(encoding='utf8')) if p.exists() else default
def write(name,obj):
    DATA.mkdir(parents=True,exist_ok=True)
    (DATA/name).write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n',encoding='utf8')
def get(r,*fields):
    for f in fields:
        if r.get(f) not in (None,''):return r[f]
def num(v):
    try:return float(str(v).strip().replace(',',''))
    except (TypeError,ValueError):return None
def date(v):
    x=str(v or '').strip().replace('/','').replace('-','')
    if len(x)==7 and x.isdigit():return str(int(x[:3])+1911)+'-'+x[3:5]+'-'+x[5:]
    if len(x)==8 and x.isdigit() and x.startswith('20'):return x[:4]+'-'+x[4:6]+'-'+x[6:]
def code(s):return bool(re.fullmatch('[1-9][0-9]{3}',str(s or '').strip()))
def tdcc_parse(rr):
    a=defaultdict(dict)
    for r in rr:
        c=str(get(r,'證券代號','SecuritiesCode','SecurityCode') or '').strip()
        d=date(get(r,'資料日期','Date'))
        level=num(get(r,'持股分級','HoldingRange','ShareholdingLevel'))
        if not(code(c) and d and level is not None):continue
        level=int(level)
        ratio=num(get(r,'占集保庫存數比例%','占集保庫存數比例％','Percent','Percentage'))
        if level<=15 and level>=1 and ratio is not None:a[(d,c)][level]=ratio
        if level==17:
            a[(d,c)]['owners']=num(get(r,'人數','NumberOfHolders','Holders'))
            a[(d,c)]['totalShares']=num(get(r,'股數','NumberOfShares','Shares'))
    ds=sorted({d for d,c in a})
    if not ds:raise ValueError('No TDCC dates')
    d=ds[-1]; out={}
    for (dt,c),v in a.items():
        if dt!=d or any(i not in v for i in range(1,16)):continue
        out[c]={'big':round(sum(v[i] for i in range(12,16)),4),'thousand':v[15],'retail':round(sum(v[i] for i in range(1,6)),4),'owners':v.get('owners'),'totalShares':v.get('totalShares'),'totalSharesSource':'tdcc_current_openapi' if v.get('totalShares') is not None else None}
    return d,out
def get_tdcc():
    errors=[]
    for url in TDCC:
        try:
            d,v=tdcc_parse(rows(download(url)))
            if len(v)<1200:raise ValueError('TDCC incomplete '+str(len(v)))
            return d,v
        except Exception as e:errors.append(str(e))
    raise RuntimeError('TDCC fetch failed: '+'; '.join(errors))
def get_roster(old):
    result={}
    warnings=[]
    for market,urls in MASTER.items():
        available=None
        for url in urls:
            try:
                raw=rows(download(url));current={}
                for r in raw:
                    c=str(get(r,'公司代號','SecuritiesCompanyCode','Code','公司代碼') or '').strip()
                    n=str(get(r,'公司簡稱','CompanyAbbreviation','CompanyName','公司名稱','Name') or '').strip()
                    if code(c) and n:current[c]={'name':n,'market':market}
                if len(current)<250:raise ValueError('Small roster '+str(len(current)))
                available=current;break
            except Exception as e:warnings.append(market+': '+str(e))
        if available is None:
            available={c:r for c,r in old.items() if r['market']==market}
            if len(available)<250:raise RuntimeError('Missing '+market+' stock roster')
            warnings.append(market+' using previous roster')
        result.update(available)
    if len(result)<1300:raise RuntimeError('Incomplete listed+OTC roster')
    return result,warnings
def get_close(history):
    warnings=[]
    for market,url in CLOSE.items():
        try:
            rr=rows(download(url));by_date=defaultdict(dict)
            for r in rr:
                c=str(get(r,'Code','SecuritiesCompanyCode','SecuritiesCode') or '').strip()
                d=date(get(r,'Date','date'))
                v=num(get(r,'ClosingPrice','Close','ClosePrice'))
                if code(c) and d and v is not None and v>0:by_date[d][c]=v
            if not by_date:raise ValueError('No valid dated prices')
            d=max(by_date)
            if len(by_date[d])<250:raise ValueError('Incomplete quote set '+str(len(by_date[d])))
            history.setdefault(d,{}).update(by_date[d])
        except Exception as e:warnings.append(market+' closing price: '+str(e))
    for d in sorted(history)[:-250]:del history[d]
    return warnings

def _historical_rows(payload):
    """Yield (field names, row values) from an official historical response."""
    if isinstance(payload,dict) and payload.get('stat') not in (None,'OK','ok'):
        raise ValueError('Official history replied: '+str(payload.get('stat')))
    groups=(payload.get('tables') or []) if isinstance(payload,dict) else []
    if isinstance(payload,dict) and isinstance(payload.get('data'),list):
        groups=[{'fields':payload.get('fields',[]),'data':payload.get('data')}]+groups
    for table in groups:
        fields=[str(x).strip().replace(' ','') for x in table.get('fields',[])]
        if not fields:continue
        data=table.get('data') or table.get('aaData') or []
        for entry in data:
            if isinstance(entry,list) and len(entry)==len(fields):yield fields,entry
            elif isinstance(entry,dict):yield list(entry),list(entry.values())

def _clean_number(val):
    import html as _html
    v=re.sub('<[^>]+>','',str(val or ''))
    v=_html.unescape(v).replace(',','').strip()
    try:
        p=float(v)
        return p if 0<p<1000000 else None
    except (ValueError,TypeError):return None

def _parse_history(payload,market):
    """Avoid guessing columns: require code + closing-price field headings."""
    result={}
    for fields,values in _historical_rows(payload):
        names=[re.sub(r'\s+','',k) for k in fields]
        code_index=next((i for i,h in enumerate(names) if h in ('證券代號','股票代號','代號','Code')),None)
        close_index=next((i for i,h in enumerate(names) if h in ('收盤價','收盤','Close','ClosingPrice')),None)
        if code_index is None or close_index is None:continue
        c=re.sub('<[^>]+>','',str(values[code_index] or '')).strip()
        v=_clean_number(values[close_index])
        if code(c) and v is not None:result[c]=v
    return result

def backfill_week_closes(prices,weekly_dates,roster):
    """Fetch a small number of official historical sessions for missing weekly anchors.

    Historical prices are optional. They must never be approximated or invented.
    Max six market/date requests per run; data are saved once per verified session.
    """
    from urllib.parse import quote
    warnings=[]
    wanted=sorted(set(weekly_dates))[-12:]
    for d in wanted:
        current=prices.setdefault(d,{})
        dt=datetime.fromisoformat(d)
        urls={
            '上市':'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date='+d.replace('-','')+'&type=ALLBUT0999&response=json',
            '上櫃':'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json&date='+quote(d.replace('-','/'),safe='')
        }
        for market,url in urls.items():
            have=sum(1 for c in current if c in roster and roster[c]['market']==market)
            if have>=('上市'==market and 850 or 600):continue
            try:
                payload=json.loads(download(url).decode('utf-8-sig'))
                found=_parse_history(payload,market)
                if len(found)<250:raise ValueError('Insufficient valid quote rows: '+str(len(found)))
                valid={c:p for c,p in found.items() if c in roster and roster[c]['market']==market}
                if len(valid)<200:raise ValueError('Historical market coverage too low '+str(len(valid)))
                current.update(valid)
                print('History recovered',d,market,'stocks',len(valid))
            except Exception as e:
                warnings.append('Historical '+market+' '+d+': '+str(e)[:180])
    return warnings

def close_near(history,d,c):
    if not d:return None
    target=datetime.fromisoformat(d)
    for dt in sorted(history,reverse=True):
        delta=(target-datetime.fromisoformat(dt)).days
        if 0<=delta<=5 and c in history[dt]:return history[dt][c]
    return None
def latest_close(history,c):
    """Most recent official close for this code, with its OWN trade date."""
    for dt in sorted(history,reverse=True):
        price=history[dt].get(c)
        if price is not None and price>0:return dt,price
    return None,None

def make_records(d,now,old,older,roster,prices,prevdate,margin_now=None,margin_prior=None,institutional=None):
    margin_now=margin_now or {}
    margin_prior=margin_prior or {}
    institutional=institutional or {}
    result=[]
    for c,r in roster.items():
        if c not in now:continue
        v=now[c];p=old.get(c);q=older.get(c)
        f=lambda k:round(v[k]-p[k],4) if p else None
        pclose=close_near(prices,prevdate,c);nclose=close_near(prices,d,c)
        latest_price_date,latest_price=latest_close(prices,c)
        curr_total=v.get('totalShares');prev_total=p.get('totalShares') if p else None
        inventory_pct=round((curr_total/prev_total-1)*100,4) if curr_total and prev_total else None
        inst=weekly_institutional(prevdate,d,c,r['market'],institutional,prices)
        weekly=round(100*(nclose/pclose-1),2) if pclose and nclose else None
        result.append({'code':c,'name':r['name'],'market':r['market'],'delta':f('big'),'priorDelta':round(p['big']-q['big'],4) if p and q else None,'kilo':f('thousand'),'retail':f('retail'),'owners':round(v['owners']-p['owners']) if p and v['owners'] is not None and p['owners'] is not None else None,'returnPct':weekly,'latestPrice':latest_price,'latestPriceDate':latest_price_date,'inventoryChangePct':inventory_pct,'inventoryShares':curr_total,'inventoryDataSource':('archived_tdcc_csv_crosschecked' if p and p.get('totalSharesSource')=='tdcc_csv_independent_archive_verified' else 'tdcc_current_openapi') if inventory_pct is not None else None,'foreignWeekly':inst['foreignWeekly'],'trustWeekly':inst['trustWeekly'],'dealerWeekly':inst['dealerWeekly'],'instCoverage':inst['instCoverage'],'instExpected':inst['instExpected'],'margin':None,'marginBalance':margin_now.get(c),'marginChange':round(margin_now[c]-margin_prior[c]) if c in margin_now and c in margin_prior else None,'tags':'','top':None,'rank':None,'source':'TDCC/TWSE/TPEx 官方快照'})
    for label,arr in [('gain',sorted([r for r in result if r['delta'] is not None and r['delta']>0],key=lambda x:-x['delta'])[:50]),('loss',sorted([r for r in result if r['delta'] is not None and r['delta']<0],key=lambda x:x['delta'])[:50])]:
        for i,r in enumerate(arr,1):r['top']=label;r['rank']=i
    return result
def refresh():
    prices=read('prices.json',{});warn_price=get_close(prices);write('prices.json',prices)
    date_tdcc,now=get_tdcc()
    roster,warn_roster=get_roster(read('universe.json',{}))
    if len(set(roster)&set(now))<1200:raise RuntimeError('Market coverage below 1200, no report published')
    weeks=read('tdcc_history.json',{})
    weeks[date_tdcc]=now
    for d in sorted(weeks)[:-25]:del weeks[d]
    archival_recovered=verified_archive_backfill(weeks,download)
    warn_history=backfill_week_closes(prices,weeks.keys(),roster)
    write('prices.json',prices)
    margins,warn_margin=fill_week_margin(weeks,roster,download,read,write)
    institutional,warn_inst=collect_institutional(weeks,prices,roster,download,read,write)
    write('universe.json',roster);write('tdcc_history.json',weeks)
    timeline=sorted(weeks);reports=[]
    for i,d in enumerate(timeline[-12:]):
        idx=timeline.index(d);p=timeline[idx-1] if idx>0 else None;q=timeline[idx-2] if idx>1 else None
        if p and (datetime.fromisoformat(d)-datetime.fromisoformat(p)).days>10:p=None;q=None
        if p and q and (datetime.fromisoformat(p)-datetime.fromisoformat(q)).days>10:q=None
        rs=make_records(d,weeks[d],weeks[p] if p else {},weeks[q] if q else {},roster,prices,p,margins.get(d,{}),margins.get(p,{}) if p else {},institutional)
        reports.append({'date':d,'compareDate':p,'label':d+' 官方定期快照','type':'auto','source':'臺灣集保結算所／證交所／櫃買中心','records':rs,'marketCoverage':len(rs),'warnings':warn_price+warn_roster+warn_history+warn_margin+warn_inst})
    write('auto_snapshots.json',{'generatedAt':datetime.now(timezone.utc).isoformat(),'latestDate':date_tdcc,'snapshots':reports})
    print('Updated',date_tdcc,'records',len(reports[-1]['records']),'trading days',len(prices),'TDCC weeks',len(weeks))
    print('A1 backfill verified:',archival_recovered)
    for w in warn_price+warn_roster+warn_history+warn_margin+warn_inst:print('Warning:',w)
if __name__=='__main__':refresh()
