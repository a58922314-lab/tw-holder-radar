"""A1 official institutional flow ingestion: strict, dated, partial-data-safe."""
import json, re, hashlib
from datetime import date as _date, timedelta
from urllib.parse import quote

PARSER_VERSION=3

def parse_holidays(payload,year):
    """Only explicit official closures, never infer holidays from missing quotes."""
    if str(payload.get('stat','')).lower()!='ok' or int(payload.get('queryYear',0))!=year:
        raise ValueError('Invalid official holiday calendar year/status')
    closed=[]
    for row in payload.get('data',[]):
        d=str(row[0])
        if not re.fullmatch(str(year)+r'-\d{2}-\d{2}',d):
            raise ValueError('Invalid holiday date')
        description=' '.join(str(v) for v in row[1:])
        if any(word in description for word in ('放假','補假','無交易','休市','停止交易')):
            closed.append(d)
    if not closed:raise ValueError('Empty official holiday calendar')
    return sorted(set(closed))

def collect_calendar(weeks,download,read,write):
    calendar=read('trading_calendar.json',{})
    warnings=[]
    for year in sorted({int(d[:4]) for d in weeks}):
        url='https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&queryYear='+str(year-1911)
        try:
            raw=download(url)
            calendar[str(year)]={'closedDates':parse_holidays(json.loads(raw.decode('utf-8-sig')),year),
                                 'source':url,'sha256':hashlib.sha256(raw).hexdigest()}
        except Exception as e:
            warnings.append('A1休市表 '+str(year)+': '+str(e)[:120])
    write('trading_calendar.json',calendar)
    return calendar,warnings

def expected_sessions(start,end,calendar=None):
    closed={d for entry in (calendar or {}).values() for d in entry.get('closedDates',[])}
    return [d for d in _dates_between(start,end) if d not in closed]

def _n(v):
    if v is None:return None
    try:return int(str(v).strip().replace(',','').replace('+','').replace('−','-'))
    except (ValueError,TypeError):return None

def _code(v):return bool(re.fullmatch(r'[1-9][0-9]{3}',str(v or '').strip()))

def parse_twse(payload):
    """Parse the real TWSE T86 root fields/data response (not always tables)."""
    result={}
    if not isinstance(payload,dict) or str(payload.get('stat','')).upper()!='OK':return result
    reports=list(payload.get('tables') or [])
    if isinstance(payload.get('data'),list):
        reports.insert(0,{'fields':payload.get('fields',[]),'data':payload.get('data')})
    for t in reports:
        fields=[str(x).replace(' ','').replace('（','(').replace('）',')') for x in t.get('fields',[])]
        i=lambda name:fields.index(name) if name in fields else None
        indices=[i('證券代號'),i('外陸資買賣超股數(不含外資自營商)'),
                 i('投信買賣超股數'),i('三大法人買賣超股數')]
        if any(x is None for x in indices):continue
        fdidx=i('外資自營商買賣超股數')
        dd=i('自營商買賣超股數')
        selfidx=i('自營商買賣超股數(自行買賣)')
        hedgeidx=i('自營商買賣超股數(避險)')
        if selfidx is None or hedgeidx is None:continue
        for row in t.get('data',[]):
            if not isinstance(row,list) or not row:continue
            if len(row)==16 and len(fields)==19 and fdidx is not None:
                # TWSE T86 sometimes omits the three foreign-dealer columns per
                # stock. Do not align those short rows to 19 shared headers.
                code,f,trust,selfnet,hedge,allnet=(row[0],_n(row[4]),_n(row[7]),_n(row[11]),_n(row[14]),_n(row[15]))
                dealer_agg=_n(row[8]);fd=0
            elif len(row)==len(fields):
                code=row[indices[0]]
                f=_n(row[indices[1]]);trust=_n(row[indices[2]])
                selfnet=_n(row[selfidx]);hedge=_n(row[hedgeidx])
                allnet=_n(row[indices[3]])
                dealer_agg=_n(row[dd]) if dd is not None else None
                fd=_n(row[fdidx]) if fdidx is not None else 0
            else:
                continue
            c=str(code).strip()
            if not _code(c) or None in (f,trust,allnet,selfnet,hedge,fd):continue
            dealer=selfnet+hedge
            if dealer_agg is not None and dealer_agg!=dealer:continue
            if f+trust+dealer!=allnet:continue
            # Foreign dealers are excluded: they are included in the dealer bucket.
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

def collect_institutional(weeks,prices,roster,download,read,write,calendar=None):
    history=read('institutional_daily.json',{})
    metadata=read('institutional_metadata.json',{})
    dates=sorted(weeks)
    warnings=[]
    if len(dates)<2:return history,warnings
    # Cover every displayed comparison, independently of the price cache.
    for cur in dates[-12:]:
        idx=dates.index(cur)
        if idx==0:continue
        prev=dates[idx-1]
        if (_date.fromisoformat(cur)-_date.fromisoformat(prev)).days>10:continue
        weekdays=expected_sessions(prev,cur,calendar)
        for d in weekdays:
            cached=history.setdefault(d,{})
            for market in ('上市','上櫃'):
                proof=metadata.get(d,{}).get(market,{})
                if market in cached and len(cached[market])>180 and proof.get('parserVersion')==PARSER_VERSION:continue
                if market=='上市':
                    url='https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date='+d.replace('-','')+'&selectType=ALLBUT0999'
                    parse=parse_twse
                else:
                    url='https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&response=json&date='+quote(d.replace('-','/'),safe='')
                    parse=parse_tpex
                try:
                    raw=download(url)
                    payload=json.loads(raw.decode('utf-8-sig'))
                    if not isinstance(payload,dict):raise ValueError('Unexpected institutional payload')
                    if str(payload.get('stat','')).lower()!='ok' or payload.get('date')!=d.replace('-',''):
                        raise ValueError('Institutional report date/status mismatch')
                    found=parse(payload)
                    valid={c:x for c,x in found.items() if c in roster and roster[c]['market']==market}
                    minimum=max(180,sum(r['market']==market for r in roster.values())*0.6)
                    if len(valid)<minimum:raise ValueError('Small/incompatible institutional report '+str(len(valid)))
                    # Keep the entire parsed market report: today's roster may
                    # not yet contain a newly listed stock needed by a later run.
                    cached[market]=found
                    metadata.setdefault(d,{})[market]={'source':url,'date':d,'rows':len(found),
                        'parserVersion':PARSER_VERSION,'sha256':hashlib.sha256(raw).hexdigest()}
                    print('A1 institution fetched',d,market,'rows',len(valid))
                except Exception as e:
                    # Do not let an unverified legacy cache masquerade as dated evidence.
                    if proof.get('parserVersion')!=PARSER_VERSION:cached.pop(market,None)
                    warnings.append('A1法人 '+market+' '+d+': '+str(e)[:120])
    for d in sorted(history)[:-90]:del history[d]
    metadata={d:v for d,v in metadata.items() if d in history}
    write('institutional_daily.json',history)
    write('institutional_metadata.json',metadata)
    return history,warnings

def weekly_institutional(start,end,c,market,history,prices,calendar=None):
    empty={'foreignWeekly':None,'trustWeekly':None,'dealerWeekly':None,
           'instCoverage':None,'instExpected':None,'instMissingDates':[],
           'instMissingReasons':{},'instSessionDates':[]}
    if not start:return empty
    sessions=expected_sessions(start,end,calendar)
    if not sessions:return {**empty,'instCoverage':0,'instExpected':0}
    items=[(d,history.get(d,{}).get(market,{}).get(c)) for d in sessions]
    available=[v for _,v in items if v is not None]
    missing=[d for d,v in items if v is None]
    if missing:
        return {**empty,'instCoverage':len(available),'instExpected':len(sessions),
                'instMissingDates':missing,'instSessionDates':sessions,
                'instMissingReasons':{d:('report_not_listed' if history.get(d,{}).get(market) else 'report_unavailable') for d in missing}}
    return {'foreignWeekly':sum(x['foreign'] for x in available)/1000,
            'trustWeekly':sum(x['trust'] for x in available)/1000,
            'dealerWeekly':sum(x['dealer'] for x in available)/1000,
            'instCoverage':len(available),'instExpected':len(sessions),
            'instMissingDates':[],'instMissingReasons':{},'instSessionDates':sessions}
