"""Exploratory event-by-event A/B backtest from retained official daily OHLCV.

NOT a portfolio backtest or a recreation of historical top-100 market caps.
Current-listed universe is survivorship biased, daily prices are unadjusted, and
the retained cache may be too short. Results fail closed if insufficient.
"""
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.momentum_daily import DATA, assess
except ImportError:
    from momentum_daily import DATA, assess

ENTRY_SLIPPAGE = 0.001
EXIT_SLIPPAGE = 0.001
COMMISSION = 0.001425
SELL_TAX = 0.003


def is_exit(bars, i):
    """Exit after three completed closes BELOW the respective daily MA20."""
    if i < 21:
        return False
    return all(
        bars[j][4] < sum(x[4] for x in bars[j-19:j+1]) / 20
        for j in (i, i-1, i-2)
    )


def simulate_run(bars, variant, code):
    """No same-bar fills; signals close t, entries/exits at t+1 open."""
    completed = []
    open_trades = 0
    position = None
    for i in range(79, len(bars)-1):
        if position:
            if is_exit(bars, i):
                exit_open = bars[i+1][1]
                net_sell = exit_open * (1 - EXIT_SLIPPAGE) * (1 - COMMISSION - SELL_TAX)
                net_return = net_sell / position["effectiveBuy"] - 1
                completed.append({
                    "code": code, "entry": position["date"], "exit": bars[i+1][0],
                    "returnPct": round(net_return * 100, 5),
                    "holdingSessions": i + 1 - position["index"]
                })
                position = None
            continue
        m = assess(bars[:i+1])
        passed = m.get("passOriginal" if variant == "A" else "passRecent3", False)
        if passed:
            entry_open = bars[i+1][1]
            position = {
                "index": i+1, "date": bars[i+1][0],
                "effectiveBuy": entry_open * (1 + ENTRY_SLIPPAGE) * (1 + COMMISSION)
            }
    if position:
        open_trades += 1
    return completed, open_trades


def market_sessions(days, roster, market):
    """Use only days with broad market coverage, not calendar weekdays."""
    codes = {c for c, info in roster.items() if info.get("market") == market}
    return [day for day in sorted(days)[-260:] if isinstance(days[day], dict) and
            sum(1 for c in days[day] if c in codes) >= 200]


def contiguous_runs(days, sessions, code):
    run = []
    for day in sessions:
        candle = days[day].get(code)
        if isinstance(candle, list) and len(candle) == 5:
            run.append([day, *candle])
        else:
            if run:
                yield run
                run = []
    if run:
        yield run


def summary(trades, open_count, market_days):
    n = len(trades)
    p = [t["returnPct"] for t in trades]
    winners = sum(v > 0 for v in p)
    gains = sum(v for v in p if v > 0)
    losses = -sum(v for v in p if v < 0)
    return {
        "closedTrades": n, "openTradesExcluded": open_count,
        "winRatePct": round(100 * winners/n, 2) if n else None,
        "avgNetReturnPct": round(statistics.mean(p), 3) if n else None,
        "medianNetReturnPct": round(statistics.median(p), 3) if n else None,
        "profitFactor": round(gains/losses, 3) if losses else None,
        "firstEntry": min((t["entry"] for t in trades), default=None),
        "lastExit": max((t["exit"] for t in trades), default=None),
        "marketSessionCount": market_days,
        "maxPortfolioDrawdownPct": None,
        "note": "樣本量過少不得視為已建立統計優勢" if n < 50 else
                "僅探索性歷史研究；非樣本外績效"
    }


def backtest(days, roster):
    all_results = {}
    sessions = {m: market_sessions(days, roster, m) for m in ("上市", "上櫃")}
    total_sessions = {m: len(v) for m,v in sessions.items()}
    for variant in ("A", "B"):
        trades, open_count, tested = [], 0, 0
        for code, meta in roster.items():
            market = meta.get("market")
            if market not in sessions:
                continue
            for run in contiguous_runs(days, sessions[market], code):
                if len(run) < 81:
                    continue
                tested += 1
                closed, opened = simulate_run(run, variant, code)
                trades.extend(closed)
                open_count += opened
        all_results[variant] = {**summary(trades, open_count, total_sessions),
                                "eligibleContinuousSeries": tested}
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "variants": all_results,
        "hypotheses": {
            "A": "當日翻正＋布林上下軌雙向張開＋MA20向上＋量至少500張",
            "B": "近3日內翻正且當下仍正值＋其餘同A"
        },
        "costs": {
            "slippageEachSidePct": ENTRY_SLIPPAGE * 100,
            "commissionEachSidePct": COMMISSION * 100,
            "sellTaxPct": SELL_TAX * 100
        },
        "limitations": [
            "現存日K歷史長度有限，僅當期仍在上市/上櫃名冊股票，存在存活者偏差",
            "日K未調整除權息，未處理漲跌停無法成交、零股、完整停牌限制",
            "僅比較單股交易事件，沒有配置資金與同時持倉規則，故不能計算可靠組合最大回撤或大盤超額報酬",
            "每檔持倉最多一筆，訊號收盤確認、下一交易日開盤進；連3日收盤跌破MA20、次日開盤出",
            "D1、VCP的歷史可得時間點尚待完整核驗，C/D整合組不輸出虛構回測"
        ]
    }


def main():
    cache = json.loads((DATA/"vcp_daily.json").read_text(encoding="utf-8"))
    roster = json.loads((DATA/"universe.json").read_text(encoding="utf-8"))
    report = backtest(cache.get("days", {}), roster)
    out = DATA/"momentum_backtest_exploratory.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n",
                   encoding="utf-8")
    print("Exploratory A/B backtest (closed trades only):")
    for name,r in report["variants"].items():
        print(name, "series=",r["eligibleContinuousSeries"],
              "trades=",r["closedTrades"], "open=",r["openTradesExcluded"],
              "winRate=",r["winRatePct"], "avgNetPct=",r["avgNetReturnPct"],
              "PF=",r["profitFactor"])
    print("Market sessions:", {m:len(market_sessions(cache.get("days", {}),roster,m))
                                 for m in ("上市","上櫃")})


if __name__ == "__main__":
    main()
