"""Strict post-update data checks, never synthesizes missing market data."""
import json
from pathlib import Path
from collections import Counter

data=json.loads((Path(__file__).resolve().parents[1]/"data/auto_snapshots.json").read_text(encoding="utf-8"))
snapshots=data.get("snapshots") or []
assert snapshots, "No official snapshots"
for s in snapshots:
    rows=s.get("records") or []
    codes=[r.get("code") for r in rows]
    assert len(rows)>=1200, f"Incomplete market coverage on {s.get('date')}: {len(rows)}"
    assert len(codes)==len(set(codes)), f"Duplicate ticker on {s.get('date')}"
    gains=[r for r in rows if r.get('top')=='gain']
    losses=[r for r in rows if r.get('top')=='loss']
    comparable=sum(isinstance(r.get('delta'),(float,int)) for r in rows)
    if comparable:
        assert comparable>=1000, f"Partial holder comparison {s.get('date')}"
        assert len(gains)==50 and len(losses)==50, f"Wrong TOP50 sizes on {s.get('date')}"
        assert all(x['delta']>0 for x in gains) and all(x['delta']<0 for x in losses), "Incorrect holder rank polarity"
    result=sum(isinstance(r.get('returnPct'),(float,int)) for r in rows)
    if result and result<200:raise AssertionError("Only few returns, quote coverage likely corrupted")
    prior=sum(isinstance(r.get('priorDelta'),(float,int)) for r in rows)
    categories=Counter(
        '續買' if r['priorDelta']>=1 and r['delta']>=1 else
        '回頭車' if r['priorDelta']<=-1 and r['delta']>=1 else
        '下車' if r['priorDelta']>=1 and r['delta']<=-1 else
        '續賣' if r['priorDelta']<=-1 and r['delta']<=-1 else
        '未分類'
        for r in rows
        if isinstance(r.get('priorDelta'),(int,float)) and isinstance(r.get('delta'),(int,float))
    )
    print(f"SNAPSHOT {s['date']} versus {s.get('compareDate')}: stocks={len(rows)} big_holder_delta={comparable} prior_week_delta={prior} weekly_return={result} gainTop={len(gains)} lossTop={len(losses)} categories={dict(categories)}")
print("OFFICIAL DATA VALIDATION PASSED")
