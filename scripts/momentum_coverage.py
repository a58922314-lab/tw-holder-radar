"""Diagnose official daily OHLCV coverage without assuming zero-volume = missing.

Run inside repository: python scripts/momentum_coverage.py
Reports per-stock gaps by market session and points to sparse quote days.
"""
import json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
MIN=80
SAMPLE=["1213","1218","1240","1259","1341","1413","1423","2233","6796"]


def diagnose(days, roster):
    stored=sorted(days)[-260:]
    members={m:{c for c,meta in roster.items() if meta.get("market")==m}
             for m in ("上市","上櫃")}
    sessions={}
    for m in members:
        sessions[m]=[d for d in stored if isinstance(days[d],dict) and
            sum(c in members[m] for c in days[d])>=200]
    by_market={}
    for m,codes in members.items():
        expected=sessions[m][-MIN:]
        reasons=Counter()
        gaps=Counter()
        examples={}
        for code in codes:
            dates=[d for d in stored if code in days[d]]
            present=set(dates)
            missing=[d for d in expected if d not in present]
            if not dates:
                kind="no_history"
            elif dates[-1]!=sessions[m][-1]:
                kind="stale"
            elif len(dates)<MIN:
                kind="short"
            elif len(expected)<MIN:
                kind="short_market"
            elif missing:
                kind="gap"
                gaps.update(missing)
            else:
                kind="ready"
            reasons[kind]+=1
            if code in SAMPLE:
                examples[code]={"type":kind,"bars":len(dates),"recentGaps":missing[:8],"last":dates[-1] if dates else None}
        # Cross-sectional quote count on active dates, useful to separate bad fetches from no-trade rows.
        sparse=[{"date":d,"count":sum(c in members[m] for c in days[d])} for d in sessions[m][-100:]]
        sparse.sort(key=lambda x:x["count"])
        by_market[m]={"stocks":len(codes),"sessions":len(sessions[m]),"reasons":dict(reasons),
                "topMissingDates":gaps.most_common(12),"lowestCoverageDays":sparse[:15],"examples":examples}
    return by_market


def main():
    raw=json.loads((DATA/"vcp_daily.json").read_text(encoding="utf-8"))
    roster=json.loads((DATA/"universe.json").read_text(encoding="utf-8"))
    print(json.dumps(diagnose(raw.get("days",{}),roster),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
