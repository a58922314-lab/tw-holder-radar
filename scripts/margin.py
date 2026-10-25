"""Fetch official weekly margin balances (unit: lots/張), without fabricating missing values."""
import json,re
from datetime import datetime
from urllib.parse import quote

def _number(x):
    try:
        s=re.sub(r'<[^>]+>','',str(x or '')).replace(',','').strip()
        if not s or s in ('--','-','—','X'):return None
        n=float(s)
        return round(n) if n>=0 else None
    except (ValueError,TypeError):return None

def _code(x):return bool(re.fullmatch(r'[1-9][0-9]{3}',str(x or '').strip()))

def _tables(payload):
    if isinstance(payload,list):
        if payload and isinstance(payload[0],dict):
            fields=list(payload[0]);yield fields,[[row.get(k) for k in fields] for row in payload]
        return
    if not isinstance(payload,dict) or payload.get('stat') not in (None,'OK','ok'):return
    a=list(payload.get('tables') or [])
    if isinstance(payload.get('data'),list):a.insert(0,payload)
    if isinstance(payload.get('aaData'),list):a.insert(0,{'fields':payload.get('fields',[]),'aaData':payload.get('aaData')})
    for tbl in a:
        fields=tbl.get('fields') or []
        rows=tbl.get('data') or tbl.get('aaData') or []
        if rows and isinstance(rows[0],dict) and not fields:fields=list(rows[0])
        if fields and rows:
            yield [str(f).strip().replace(' ','') for f in fields],[
                [row.get(k) for k in fields] if isinstance(row,dict) else row for row in rows]

def parse_margin(payload,market):
    out={}
    for fields,rows in _tables(payload):
        cidx=next((i for i,f in enumerate(fields) if f in ('股票代號','證券代號','代號','Code','SecuritiesCompanyCode','SecuritiesCode')),None)
        # TWSE repeats 今日餘額 for financing and short-selling; the first is financing.
        midx=next((i for i,f in enumerate(fields) if ('融資' in f and ('餘額' in f or 'Balance' in f)) and '前日' not in f and 'Prev' not in f),None)
        if midx is None:
            midx=next((i for i,f in enumerate(fields) if f in ('今日餘額','今餘額','融資餘額','MarginBalance','MarginTodayBalance','MarginPurchaseBalance')),None)
        # TWSE margin table: code,name,(finance buy,sell,repay,prev,today,limit),
        # (short buy,sell,repay,prev,today,limit) -> finance today is index 6.
        if market=='上市' and midx is None and len(fields)>=14 and cidx==0:
            midx=6
        if cidx is None or midx is None:continue
        for row in rows:
            if not isinstance(row,list) or max(cidx,midx)>=len(row):continue
            c=str(row[cidx]).strip()
            n=_number(row[midx])
            if _code(c) and n is not None:out[c]=n
    return out

def fill_week_margin(weeks,roster,download,read,write):
    margins=read('margin_history.json',{})
    meta=read('margin_cache_metadata.json',{})
    # Previously an undated latest-only TPEx endpoint was used as historical
    # fallback. Purge those OTC cache entries exactly once; never reuse them.
    if meta.get('source_policy_version')!=2:
        for cache in margins.values():
            for c in list(cache):
                if c in roster and roster[c].get('market')=='上櫃':del cache[c]
        write('margin_history.json',margins)
        write('margin_cache_metadata.json',{'source_policy_version':2,'otc_history_requires_dated_endpoint':True})
        print('Cleared unverified OTC margin backfill from prior snapshots')
    warnings=[]
    dates=sorted(weeks)[-12:]
    for d in dates:
        current=margins.setdefault(d,{})
        roc=f"{datetime.fromisoformat(d).year-1911}/{d[5:7]}/{d[8:10]}"
        urls={
            '上市':['https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date='+d.replace('-','')+'&selectType=ALL&response=json'],
            '上櫃':['https://www.tpex.org.tw/www/zh-tw/margin/balance?date='+quote(roc,safe='')+'&response=json',
                    'https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal.php?l=zh-tw&d='+quote(roc,safe='')+'&o=json']
        }
        for market,targets in urls.items():
            stockcount=sum(c in roster and roster[c].get('market')==market for c in current)
            if stockcount>=('上市'==market and 700 or 350):continue
            found={}
            for url in targets:
                try:
                    payload=json.loads(download(url).decode('utf-8-sig'))
                    vals=parse_margin(payload,market)
                    valid={c:v for c,v in vals.items() if c in roster and roster[c].get('market')==market}
                    if len(valid)<100:raise ValueError('insufficient valid rows: '+str(len(valid)))
                    found=valid
                    print('Margin history recovered',d,market,'stocks',len(found))
                    break
                except Exception as e:warnings.append('Margin '+market+' '+d+': '+str(e)[:150])
            current.update(found)
    write('margin_history.json',margins)
    return margins,warnings
