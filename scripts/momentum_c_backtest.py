"""Research-only comparison: MACD three-day technical B versus B gated by
D1/D1+ weekly official snapshots C, on the SAME eligible days and universe.

Never apply present-week holdings to earlier days. This uses a deliberately
conservative seven-calendar-day disclosure embargo after each TDCC snapshot
*date*, because exact historical public release timestamps are not in the
snapshot archive. The embargo is an assumption, NOT a verified timestamp.
The report must not be represented as a point-in-time audited strategy.

Snapshot and bars are both sourced from repo data/. No future weekly data is
consulted when generating an entry. The early available weeks are limited.
"""

import json
import math
import statistics
from collections import Counter
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

try:
    from scripts.momentum_backtest import (
        DATA, COMMISSION, SELL_TAX, ENTRY_SLIPPAGE, EXIT_SLIPPAGE,
        is_exit, market_sessions, contiguous_runs,
    )
    from scripts.momentum_daily import assess
except ImportError:
    from momentum_backtest import (
        DATA, COMMISSION, SELL_TAX, ENTRY_SLIPPAGE, EXIT_SLIPPAGE,
        is_exit, market_sessions, contiguous_runs,
    )
    from momentum_daily import assess

DISCLOSURE_DELAY_DAYS = 7
MAX_SNAPSHOT_AGE_DAYS = 14
REQUIRED_RECORDS = 1200
MIN_SNAPSHOT_COVERAGE = 1000
VARIANTS = ("B", "C", "Cplus")


def finite(n):
    return type(n) in (float, int) and math.isfinite(n)


def tier(row):
    """Exact Python equivalent of rules/d1-screening.js D1/D1+ portion."""
    if not isinstance(row, dict):
        return None
    whale, weekly = row.get("delta"), row.get("returnPct")
    diff, current = row.get("marginChange"), row.get("marginBalance")
    if not (finite(whale) and finite(weekly) and finite(diff)):
        return None
    if not (whale >= 1.0 and weekly <= 0 and diff < 0):
        return None
    previous = current - diff if finite(current) else None
    drop = -100 * diff / previous if previous is not None and previous > 0 else None
    return ("D1+" if whale >= 2.0 and drop is not None and drop >= 5 else "D1")


def historical_week_rows(payload):
    if not isinstance(payload, dict):
        return []
    weeks = []
    for w in payload.get("snapshots", []):
        if (not isinstance(w, dict) or w.get("type") != "auto" or
            not isinstance(w.get("records"), list) or len(w["records"]) < REQUIRED_RECORDS):
            continue
        try:
            dt = date.fromisoformat(w["date"])
            compare = date.fromisoformat(w["compareDate"])
            if not 0 < (dt - compare).days <= 10:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        seen = set()
        eligible = {}
        complete = 0
        for r in w["records"]:
            code = str(r.get("code", ""))
            if len(code) != 4 or not code.isdigit() or code in seen:
                continue
            seen.add(code)
            if (finite(r.get("delta")) and finite(r.get("returnPct"))
                and finite(r.get("marginChange"))):
                complete += 1
            result = tier(r)
            if result:
                eligible[code] = result
        if complete < MIN_SNAPSHOT_COVERAGE:
            continue
        weeks.append({"date": dt, "compareDate": compare, "tiers": eligible,
                      "records": len(w["records"]), "complete": complete})
    # Deduplicate weekly snapshots and never mix a date across multiple weeks.
    return sorted({w["date"]: w for w in weeks}.values(), key=lambda w: w["date"])


def make_windows(snapshots, lag_days=DISCLOSURE_DELAY_DAYS,
                 max_age_days=MAX_SNAPSHOT_AGE_DAYS):
    """Day -> publicly-usable historical snapshot, conservative assumed delay.

    If a newer snapshot is available, it replaces the older selection.
    Do not reuse stale older snapshots after the bounded expiry.
    """
    weeks = historical_week_rows(snapshots)
    windows = []
    for i, w in enumerate(weeks):
        start = w["date"] + timedelta(days=lag_days)
        end = start + timedelta(days=max_age_days)
        if i+1 < len(weeks):
            next_avail = weeks[i+1]["date"] + timedelta(days=lag_days)
            end = min(end, next_avail)
        if start < end:
            windows.append({**w, "start": start.isoformat(),
                            "endExclusive": end.isoformat()})
    return windows


def calendar_index(windows):
    """ISO day -> as-of snapshot; only use past snapshots."""
    result = {}
    for w in windows:
        day = date.fromisoformat(w["start"])
        end = date.fromisoformat(w["endExclusive"])
        while day < end:
            key = day.isoformat()
            if key in result:
                raise AssertionError("Overlapping D1 vintage windows")
            result[key] = w
            day += timedelta(days=1)
    return result


def net_return(buy_open, sell_open):
    buy = buy_open * (1 + ENTRY_SLIPPAGE) * (1 + COMMISSION)
    sell = sell_open * (1 - EXIT_SLIPPAGE) * (1 - COMMISSION - SELL_TAX)
    return 100 * (sell / buy - 1)


def summary(trades, open_trades, signals):
    returns = [t["netReturnPct"] for t in trades]
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    return {
        "closedTrades": len(trades),
        "openTradesExcluded": open_trades,
        "entrySignals": signals,
        "winRatePct": round(100 * len(wins) / len(returns), 2) if returns else None,
        "avgNetReturnPct": round(statistics.mean(returns), 3) if returns else None,
        "medianNetReturnPct": round(statistics.median(returns), 3) if returns else None,
        "profitFactor": round(sum(wins) / -sum(losses), 3) if losses else None,
        "firstEntry": min((t["entry"] for t in trades), default=None),
        "lastExit": max((t["exit"] for t in trades), default=None),
        "sampleSufficient": len(trades) >= 50,
    }


def simulate(bars, by_calendar, ticker):
    """Evaluate signals on completed daily closes, fill on next bar open.

    One position per stock and variant. B & C use exactly the same active
    calendar and stock universe; C restricts entries by known historical D1.
    """
    results = {v: [] for v in VARIANTS}
    opened = {v: 0 for v in VARIANTS}
    signal_count = Counter()
    position = {v: None for v in VARIANTS}
    for i in range(79, len(bars) - 1):
        day = bars[i][0]
        week = by_calendar.get(day)
        for v in VARIANTS:
            if position[v]:
                if is_exit(bars, i):
                    opened_position = position[v]
                    ret = net_return(opened_position["buyOpen"], bars[i+1][1])
                    results[v].append({
                        "code":ticker, "entry":opened_position["entry"],
                        "exit": bars[i+1][0], "netReturnPct": round(ret, 6),
                        "holderWeek":opened_position["holderWeek"],
                    })
                    position[v] = None
        if not week:
            continue
        # All versions share the identical market dates. Position signals
        # remain independently subject to the one-position rule.
        if all(position[v] for v in VARIANTS):
            continue
        candidate = assess(bars[:i+1])
        if not candidate.get("passRecent3"):
            continue
        signal_count["technical"] += 1
        known_tier = week["tiers"].get(ticker)
        if known_tier:
            signal_count["technical_and_d1"] += 1
        if known_tier == "D1+":
            signal_count["technical_and_d1plus"] += 1
        for variant in VARIANTS:
            if position[variant]:
                continue
            if variant == "C" and not known_tier:
                continue
            if variant == "Cplus" and known_tier != "D1+":
                continue
            position[variant] = {
                "entry":bars[i+1][0], "buyOpen":bars[i+1][1],
                "holderWeek":week["date"].isoformat() if variant != "B" else None,
            }
            opened[variant] += 1
    open_positions = {v: int(position[v] is not None) for v in VARIANTS}
    return results, open_positions, signal_count, opened


def simulate_fixed_horizon(bars, by_calendar, ticker, hold_sessions=5):
    """Independent sensitivity check: hold exactly N market sessions.

    This study does NOT use the MA20 exit rule. It avoids the bias of counting
    only early exits while profitable positions remain open near sample end.
    A future price is read solely for scoring a completed trade, never to
    decide whether a historical signal qualifies.
    """
    results = {v: [] for v in VARIANTS}
    censored = Counter()
    entries = Counter()
    next_entry_allowed = {v: 79 for v in VARIANTS}
    for i in range(79, len(bars)-1):
        week = by_calendar.get(bars[i][0])
        if not week:
            continue
        if all(i < next_entry_allowed[v] for v in VARIANTS):
            continue
        signal = assess(bars[:i+1])
        if not signal.get("passRecent3"):
            continue
        known_tier = week["tiers"].get(ticker)
        for variant in VARIANTS:
            if i < next_entry_allowed[variant]:
                continue
            if variant == "C" and not known_tier:
                continue
            if variant == "Cplus" and known_tier != "D1+":
                continue
            entries[variant] += 1
            # Entry open is next market session; exit is after N sessions.
            buy_index = i+1
            sell_index = buy_index+hold_sessions
            if sell_index >= len(bars):
                censored[variant] += 1
                next_entry_allowed[variant] = len(bars)+1
                continue
            results[variant].append({
                "code":ticker, "entry":bars[buy_index][0],
                "exit":bars[sell_index][0],
                "holderWeek":week["date"].isoformat() if variant != "B" else None,
                "netReturnPct":round(net_return(bars[buy_index][1],
                                                bars[sell_index][1]),6),
            })
            next_entry_allowed[variant] = sell_index
    return results, censored, entries


def compare(days, roster, snapshots):
    windows = make_windows(snapshots)
    by_calendar = calendar_index(windows)
    # Full-market B and C share these dates, never benchmark C against last
    # year's different B trade sample.
    sessions_by_market = {m: market_sessions(days, roster, m)
                          for m in ("上市", "上櫃")}
    relevant_days = sorted(set(by_calendar) & set(
        sessions_by_market["上市"] + sessions_by_market["上櫃"]))
    all_trades = {v: [] for v in VARIANTS}
    all_open = Counter()
    signals = Counter()
    entries = Counter()
    eligible_series = 0
    for code, meta in roster.items():
        market = meta.get("market")
        if market not in sessions_by_market:
            continue
        for bars in contiguous_runs(days, sessions_by_market[market], code):
            if len(bars) < 81:
                continue
            if bars[-1][0] < (relevant_days[0] if relevant_days else "9999"):
                continue
            eligible_series += 1
            trades, opened, signs, taken = simulate(bars, by_calendar, code)
            for v in VARIANTS:
                all_trades[v].extend(trades[v])
                all_open[v] += opened[v]
                entries[v] += taken[v]
            signals.update(signs)
    fixed_studies = {}
    for horizon in (5, 10):
        fixed_trades = {v: [] for v in VARIANTS}
        fixed_open = Counter()
        fixed_entries = Counter()
        for code, meta in roster.items():
            market = meta.get("market")
            if market not in sessions_by_market:
                continue
            for bars in contiguous_runs(days, sessions_by_market[market], code):
                if len(bars) < 81 or (
                    bars[-1][0] < (relevant_days[0] if relevant_days else "9999")
                ):
                    continue
                trades, opened, taken = simulate_fixed_horizon(
                    bars, by_calendar, code, hold_sessions=horizon
                )
                for v in VARIANTS:
                    fixed_trades[v].extend(trades[v])
                    fixed_open[v] += opened[v]
                    fixed_entries[v] += taken[v]
        fixed_studies[str(horizon)] = {
            "holdingSessions":horizon,
            "method":"收盤B/C訊號、隔日開盤進、再持有固定交易日後開盤出場",
            "variants":{v:summary(fixed_trades[v],fixed_open[v],fixed_entries[v])
                        for v in VARIANTS}
        }
    # Completion is measured with all historical available bars after entry;
    # positions still open at end are excluded from win rate, not treated as wins.
    stats = {v: {**summary(all_trades[v], all_open[v], entries[v]),
                 "qualifyingStockUniverse":eligible_series} for v in VARIANTS}
    output = {
        "generatedAt":datetime.now(timezone.utc).isoformat(),
        "status":"exploratory" if windows else "insufficient_historical_weekly_data",
        "method":"日K收盤確認、隔日開盤入場；3日收盤跌破當日MA20、隔日開盤出場",
        "weeklyAvailabilityAssumption":"集保基準日+7個日曆日，非歷史實際公布時間",
        "costs":{"commissionEachSidePct":COMMISSION*100,
                 "slippageEachSidePct":ENTRY_SLIPPAGE*100,
                 "sellTaxPct":SELL_TAX*100},
        "windows":[{"week":w["date"].isoformat(), "compareWeek":w["compareDate"].isoformat(),
                    "validFrom":w["start"],"validUntilExclusive":w["endExclusive"],
                    "d1":sum(t=="D1" for t in w["tiers"].values()),
                    "d1plus":sum(t=="D1+" for t in w["tiers"].values()),
                    "records":w["records"],"completeRows":w["complete"]} for w in windows],
        "weeklySnapshotsUsed":len(windows),
        "marketActiveSessions":len(relevant_days),
        "eligibleSeries":eligible_series,
        "signals":dict(signals),
        "variants":stats,
        "fixedHoldingStudies":fixed_studies,
        "comparison":{"B_minus_C_winRatePp":round(stats["B"]["winRatePct"]-stats["C"]["winRatePct"],2)
                 if stats["B"]["winRatePct"] is not None and stats["C"]["winRatePct"] is not None else None,
                 "C_minus_B_profitFactor":round(stats["C"]["profitFactor"]-stats["B"]["profitFactor"],3)
                 if stats["B"]["profitFactor"] is not None and stats["C"]["profitFactor"] is not None else None},
        "limitations":[
            "公開歷史日期無精確發表時間；採基準日後7日保守延遲（需核驗）",
            "原有每週籌碼快照最多12筆；無法補造尚未保存的歷史D1選股",
            "股價未還原除權息；現存上市櫃股票名冊有存活者偏差",
            "不做股票持倉組合資金配置，無法得出組合最大回撤",
            "未能確認歷史漲跌停可成交、停牌與滑價，均為研究級假設",
            "若C交易數過少，不足以推論大戶條件提高勝率",
            "僅使用原D1股價、融資、大戶百分點規則；可疑股本異動仍須另核對",
        ],
    }
    return output


def main():
    cache=json.loads((DATA/"vcp_daily.json").read_text(encoding="utf8"))
    roster=json.loads((DATA/"universe.json").read_text(encoding="utf8"))
    weekly=json.loads((DATA/"auto_snapshots.json").read_text(encoding="utf8"))
    result=compare(cache.get("days",{}),roster,weekly)
    out=DATA/"momentum_c_backtest_exploratory.json"
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print("D1 momentum B vs C, SAME eligibility days; snapshots",result["weeklySnapshotsUsed"],
          "market sessions",result["marketActiveSessions"],"series",result["eligibleSeries"])
    print("Historical vintages:",json.dumps(result["windows"],ensure_ascii=False))
    print("D1 technical overlap",result["signals"])
    for v,s in result["variants"].items():
        print(v,"entries",s["entrySignals"],"closed",s["closedTrades"],
              "open",s["openTradesExcluded"],"wins",s["winRatePct"],
              "avg",s["avgNetReturnPct"],"PF",s["profitFactor"])
    for horizon,study in result["fixedHoldingStudies"].items():
        print("Fixed holding horizon",horizon,"sessions")
        for v,st in study["variants"].items():
            print("  ",v,"entries",st["entrySignals"],"completed",st["closedTrades"],
                  "excluded",st["openTradesExcluded"],"winRate",st["winRatePct"],
                  "avg",st["avgNetReturnPct"],"PF",st["profitFactor"])
    if result["variants"]["C"]["closedTrades"] < 50:
        print("WARNING: C has fewer than 50 closed trades; no reliable win-rate claim.")


if __name__=="__main__":
    main()
