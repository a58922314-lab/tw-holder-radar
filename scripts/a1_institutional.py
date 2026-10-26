"""A1 official institutional flow ingestion: strict, dated, partial-data-safe."""
import json, re
from datetime import date as _date, timedelta
from urllib.parse import quote

def _n(v):
    if v is None:return None
    try:return int(str(v).strip().replace(',','').replace('+','').replace('−','-'))
    except (ValueError,TypeError):return None

def _code(v):return bool(re.fullmatch(r'[1-9][0-9]{3}',str(v or '').strip()))

def parse_twse(payload):
    result={}
    if not isinstance(payload,dict) or str(payload.get('stat','')).upper()!='OK':return result
    # TWSE T86 schema shifted historically. Rely on exact unique field headings.
    for t in payload.get('tables',[]):
        fields=[str(x).replace(' ','').replace('（','(').replace('）',')') for x in t.get('fields',[])]
        i=lambda name:fields.index(name) if name in fields else None
        indices=[i('證券代號'),i('外陸資買賣超股數(不含外資自營商)'),
                 i('投信買賣超股數'),i('三大法人買賣超股數')]
        if any(x is None for x in indices):continue
        ff=i('外資自營商買賣超股數')
        dd=i('自營商買賣超股數')
        selfidx=i('自營商買賣超股數(自行買賣)')
        hedgeidx=i('自營商買賣超股數(避險)')
        if selfidx is None or hedgeidx is None:continue
        for row in t.get('data',[]):
            if len(row)<len(fields):continue
            c=str(row[indices[0]]).strip()
            if not _code(c):continue
            f=_n(row[indices[1]]);trust=_n(row[indices[2]]);allnet=_n(row[indices[3]])
            selfnet=_n(row[selfidx]);hedge=_n(row[hedgeidx])
            fd=_n(row[ff]) if ff is not None else 0
            if None in (f,trust,allnet,selfnet,hedge,fd):continue
            dealer=selfnet+hedge
            if dd is not None and _n(row[dd]) != dealer:continue
            if f+trust+dealer != allnet:continue
            # Exclude foreign dealers: they belong to dealer aggregate.
            result[c]={'foreign':f,'trust':trust,'dealer':dealer}
    return result

def parse_tpex(payload):
    result={}
    if not isinstance(payload,dict):return result
    tables=payload.get('tables') or []
    arrays=[]
    if isinstance(payload.get('aaData'),list):arrays.append(payload['aaData'])
    if isinstance(payload.get('data'),list):
        if payload['data'] and isinstance(payload['data'][0],list):arrays.append(payload['data'])
    for t in tables:
        rows=t.get('data') or t.get('aaData') or []
        if rows and isinstance(rows[0],list):arrays.append(rows)
    for rows in arrays:
        for row in rows:
            # TPEx dated 24-column stock-level table, seven buy/sell/net triplets.
            if len(row)<24 or not _code(row[0]):continue
            f=_n(row[4]);trust=_n(row[13]);selfnet=_n(row[16]);hedge=_n(row[19])
            dealer=_n(row[22]);total=_n(row[23])
            if None in (f,trust,selfnet,hedge,dealer,total):continue
            if selfnet+hedge!=dealer or f+trust+dealer!=total:continue
            result[str(row[0]).strip()]={'foreign':f,'trust':trust,'dealer':dealer}
    return result

def _dates_between(start,end):
    s=_date.fromisoformat(start);e=_date.fromisoformat(end)
    out=[]
    s+=timedelta(days=1)
    while s<=e:
        if s.weekday()<5:out.append(s.isoformat())
        s+=timedelta(days=1)
    return out

def collect_institutional(weeks,prices,roster,download,read,write):
    history=read('institutional_daily.json',{})
    dates=sorted(weeks)
    warnings=[]
    if len(dates)<2:return history,warnings
    # For current/latest A1 plus preceding weekly period only, never backdate latest snapshots.
    for cur in dates[-2:]:
        idx=dates.index(cur)
        if idx==0:continue
        prev=dates[idx-1]
        weekdays=_dates_between(prev,cur)
        # Prefer historical dates known to have closed, avoid weekends/market holidays.
        for d in weekdays:
            if d not in prices:continue
            cached=history.setdefault(d,{})
            for market in ('上市','上櫃'):
                if market in cached and len(cached[market])>180:continue
                if market=='上市':
                    url='https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date='+d.replace('-','')+'&selectType=ALLBUT0999'
                    parse=parse_twse
                else:
                    roc=str(int(d[:4])-1911)+'/'+d[5:7]+'/'+d[8:]
                    url='https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d='+quote(roc,safe='')
                    parse=parse_tpex
                try:
                    payload=json.loads(download(url).decode('utf-8-sig'))
                    if not isinstance(payload,dict):raise ValueError('Unexpected institutional payload')
                    found=parse(payload)
                    valid={c:x for c,x in found.items() if c in roster and roster[c]['market']==market}
                    if len(valid)<180:raise ValueError('Small/incompatible institutional report '+str(len(valid)))
                    cached[market]=valid
                    print('A1 institution fetched',d,market,'rows',len(valid))
                except Exception as e:warnings.append('A1法人 '+market+' '+d+': '+str(e)[:120])
    for d in sorted(history)[:-90]:del history[d]
    write('institutional_daily.json',history)
    return history,warnings

def weekly_institutional(start,end,c,market,history,prices):
    if not start:return {'foreignWeekly':None,'trustWeekly':None,'dealerWeekly':None,'instCoverage':None,'instExpected':None}
    weekdays=_dates_between(start,end)
    # A weekday can be a genuine market holiday. Use saved whole-market closes to
    # determine sessions; if daily quote history is sparse, do not certify completeness.
    sessions=[d for d in weekdays if d in prices and len(prices[d])>=800]
    if not sessions or len(sessions)<max(1,len(weekdays)-1):
        return {'foreignWeekly':None,'trustWeekly':None,'dealerWeekly':None,'instCoverage':len(sessions),'instExpected':len(weekdays)}
    items=[]
    for d in sessions:
        v=history.get(d,{}).get(market,{}).get(c)
        if not v:return {'foreignWeekly':None,'trustWeekly':None,'dealerWeekly':None,'instCoverage':len(items),'instExpected':len(sessions)}
        items.append(v)
    return {'foreignWeekly':round(sum(x['foreign'] for x in items)/1000,1),
            'trustWeekly':round(sum(x['trust'] for x in items)/1000,1),
            'dealerWeekly':round(sum(x['dealer'] for x in items)/1000,1),
            'instCoverage':len(items),'instExpected':len(sessions)}
