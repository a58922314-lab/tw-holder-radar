"""Strict backfill of TDCC holdings denominator from archived ORIGINAL TDCC CSV.

Official TDCC 1-5 exposes only the current week. The community archive mirrors
the original published CSV. Historical rows MUST match the already-persisted
official TDCC holdings ratios and holder totals on every covered security.
Unverifiable rows are never filled. This is not an official historic API.
"""
from collections import defaultdict
import csv,io
from datetime import date

ARCHIVE_ROOT='https://raw.githubusercontent.com/wirelessr/tdcc-opendata-archive/main/snapshots'
ARCHIVE_SOURCE='tdcc_csv_independent_archive_verified'
OFFICIAL_SOURCE='tdcc_current_openapi'

def _archived_snapshot(raw,d):
    text=raw.decode('utf-8-sig')
    if not text.startswith('資料日期,證券代號,'):raise ValueError('Unknown archive CSV header')
    out=defaultdict(lambda:{'ranges':{},'owners':None,'shares':None})
    for r in csv.DictReader(io.StringIO(text)):
        if str(r.get('資料日期','')).strip()!=d.replace('-',''):raise ValueError('Archive date disagrees with requested week')
        c=str(r.get('證券代號','')).strip()
        if len(c)!=4 or not c.isdigit():continue
        level=int(str(r['持股分級']).strip())
        if level in range(1,16):
            out[c]['ranges'][level]=float(str(r['占集保庫存數比例%']).strip())
        elif level==17:
            out[c]['owners']=int(str(r['人數']).strip())
            out[c]['shares']=int(str(r['股數']).strip())
    return out

def verified_archive_backfill(weeks,download):
    result=[]
    for d,snapshot in sorted(weeks.items()):
        if not any('totalShares' not in item for item in snapshot.values()):continue
        if date.fromisoformat(d).year<2025:continue
        url=f'{ARCHIVE_ROOT}/{d[:4]}/{d}.csv'
        try:
            archive=_archived_snapshot(download(url),d)
        except Exception as e:
            print('A1 archive unavailable',d,str(e)[:200])
            continue
        matches={}
        mismatch=[]
        for c,current in snapshot.items():
            row=archive.get(c)
            if not row or row['shares'] is None or row['shares']<=0 or row['owners'] is None:
                mismatch.append(c);continue
            vals=row['ranges']
            if any(i not in vals for i in range(1,16)):
                mismatch.append(c);continue
            sum_big=sum(vals[k] for k in range(12,16))
            sum_small=sum(vals[k] for k in range(1,6))
            correct=(row['owners']==current.get('owners') and
                     abs(sum_big-current['big'])<=0.02 and
                     abs(sum_small-current['retail'])<=0.02 and
                     abs(vals[15]-current['thousand'])<=0.02)
            if correct:matches[c]=row['shares']
            else:mismatch.append(c)
        # Require near-total match with existing first-party records. Reject
        # wholesale rather than trusting a mismatched third-party file.
        if mismatch or len(matches)<max(1000,0.98*len(snapshot)):
            print('A1 archive rejected',d,'matched',len(matches),'mismatched',len(mismatch))
            continue
        changed=0
        for c,total in matches.items():
            if snapshot[c].get('totalShares') is None:
                snapshot[c]['totalShares']=total
                snapshot[c]['totalSharesSource']=ARCHIVE_SOURCE
                changed+=1
        result.append((d,changed))
        print('A1 archive verified',d,'matches',len(matches),'backfilled',changed,'source',url)
    return result
