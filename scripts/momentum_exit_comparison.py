"""Fair exit-rule study for tw-holder-radar: identical B entry cohorts.

Three exits:
 - MA20: 3 consecutive completed daily closes below their individual SMA20,
   sell at NEXT session's open.
 - FIXED5: same MA20 exit OR initial entry-open * 0.95 protective stop.
 - ATR2: same MA20 exit OR initial entry-open - 2 * Wilder ATR(14), based
   ONLY on the signal-day and earlier candles (not a trailing stop).

OHLC intraday path assumptions: gap below stop -> open; otherwise if day's
low <= stop -> stop price (minus slippage); pending MA exit -> next open.
If an open simultaneously breaches the stop and MA exit is due, fill at the
open and attribute to the stop gap. Enter at next day's open; stop can fill
later in that same day's session. No next-day closing price is used for
the entry decision.

The same entry dates are used across all exits: each stock waits until ALL
three versions from a cohort have exited before another entry is allowed.
Portfolio max drawdown uses a separate, capital-backed, 10-slot common-cohort
portfolio (identical entries across exits), with cash, commissions, taxes,
slippage and daily open-position marks. It is NOT the same as max drawdown
from sorted closed trades. No leverage or shorting.

Limitations: present-day ticker universe, unadjusted historical prices,
possible limit-down execution failures, zero-volume gaps, no lot constraints,
no exact intraday stop execution sequence or order-book fills. Research only.
"""
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

try:
    from scripts.momentum_daily import DATA, _bands, _ema
    from scripts.momentum_backtest import (
        COMMISSION, SELL_TAX, ENTRY_SLIPPAGE, EXIT_SLIPPAGE,
        market_sessions, contiguous_runs, is_exit,
    )
    from scripts.momentum_c_backtest import make_windows, calendar_index
except ImportError:
    from momentum_daily import DATA, _bands, _ema
    from momentum_backtest import (
        COMMISSION, SELL_TAX, ENTRY_SLIPPAGE, EXIT_SLIPPAGE,
        market_sessions, contiguous_runs, is_exit,
    )
    from momentum_c_backtest import make_windows, calendar_index

VARIANTS = ("MA20", "FIXED5", "ATR2")
INITIAL_CAPITAL = 1_000_000.0
MAX_POSITIONS = 10
STOP_FIXED_PCT = 5.0
ATR_LENGTH = 14
ATR_MULTIPLIER = 2.0
MIN_HISTORY = 80


def wilder_atr(bars, period=ATR_LENGTH):
    """TR uses previous close; first Wilder ATR = SMA of initial 14 TRs."""
    tr = []
    for i, b in enumerate(bars):
        hi, lo = b[2], b[3]
        prev = bars[i-1][4] if i else b[4]
        tr.append(max(hi-lo, abs(hi-prev), abs(lo-prev)))
    out = [None] * len(bars)
    if len(bars) < period:
        return out
    prev_atr = sum(tr[:period]) / period
    out[period-1] = prev_atr
    for i in range(period,len(bars)):
        prev_atr = ((period-1)*prev_atr + tr[i])/period
        out[i] = prev_atr
    return out


def b_signals(bars):
    """Precalculate exactly the site B (3-session MACD + strict BB + MA20)."""
    closes = [b[4] for b in bars]
    weighted = [(b[2]+b[3]+2*b[4])/4 for b in bars]
    fast = _ema(weighted,12)
    slow = _ema(weighted,26)
    dif = [a-b for a,b in zip(fast,slow)]
    sig = _ema(dif,9)
    osc = [a-b for a,b in zip(dif,sig)]
    cross = [i>0 and osc[i]>0 and osc[i-1]<=0 for i in range(len(osc))]
    result = [False]*len(bars)
    for i in range(MIN_HISTORY-1,len(bars)-1):
        if (not (osc[i]>0 and any(cross[i-2:i+1])) or
            bars[i][5]<500):
            continue
        mid, up, dn = _bands(closes[i-19:i+1])
        prevmid, prevup, prevdn = _bands(closes[i-20:i])
        avg = mid
        if (avg>0 and prevmid>0 and
            (up-dn)/mid>(prevup-prevdn)/prevmid and
            up>prevup and dn<prevdn and
            closes[i]>avg and avg>prevmid):
            result[i] = True
    return result


def stop_level(variant, entry_open, signal_atr):
    if variant=="FIXED5":
        return entry_open*(1-STOP_FIXED_PCT/100)
    if variant=="ATR2":
        if signal_atr is None or not math.isfinite(signal_atr):
            return None
        return max(0.0001,entry_open-ATR_MULTIPLIER*signal_atr)
    return None


def simulate_exit(bars, entry_index, variant, signal_atr):
    """Return raw exit order, never a close-price instant fill."""
    entry_open = bars[entry_index][1]
    stop = stop_level(variant,entry_open,signal_atr)
    for j in range(entry_index,len(bars)):
        day, op, _hi, lo, _cl, _lots = bars[j]
        due_ma = j>entry_index and is_exit(bars,j-1)
        if stop is not None and j>entry_index and op<=stop:
            return {"exitIndex":j,"exitDate":day,"exitRaw":op,
                    "exitReason":"stop_gap","stop":stop}
        if due_ma:
            return {"exitIndex":j,"exitDate":day,"exitRaw":op,
                    "exitReason":"ma20_next_open","stop":stop}
        # A newly established stop is below the entry-day opening price.
        if stop is not None and lo<=stop:
            return {"exitIndex":j,"exitDate":day,"exitRaw":stop,
                    "exitReason":"stop_intraday","stop":stop}
    return {"exitIndex":None,"exitDate":None,"exitRaw":None,
            "exitReason":"unclosed","stop":stop}


def make_cohorts(days, roster, gate="B", snapshots=None):
    """Generate a set of identical entry cohorts, before capital limitations."""
    by_date = {}
    if gate=="C":
        by_date=calendar_index(make_windows(snapshots or {"snapshots":[]}))
    sessions = {m:market_sessions(days,roster,m) for m in ("上市","上櫃")}
    all_cohorts=[]
    counters=Counter()
    for ticker,meta in sorted(roster.items()):
        if meta.get("market") not in sessions:
            continue
        for bars in contiguous_runs(days,sessions[meta["market"]],ticker):
            if len(bars)<MIN_HISTORY+1:
                continue
            # A series has genuine stock-specific rows on each market day
            # within this particular contiguous run.
            if any(len(b)!=6 or min(b[1:5])<=0 or b[5]<=0 for b in bars):
                continue
            atr=wilder_atr(bars)
            signals=b_signals(bars)
            i=MIN_HISTORY-1
            while i <len(bars)-1:
                if not signals[i]:
                    i+=1
                    continue
                if gate=="C":
                    week=by_date.get(bars[i][0])
                    if not week or ticker not in week["tiers"]:
                        i+=1
                        continue
                counters["signalsEligible"]+=1
                entry_idx=i+1
                entry_day=bars[entry_idx][0]
                entry_raw=bars[entry_idx][1]
                variants={v:simulate_exit(bars,entry_idx,v,atr[i]) for v in VARIANTS}
                all_cohorts.append({
                    "code":ticker,"signalDate":bars[i][0],
                    "entryDate":entry_day,"entryIndex":entry_idx,
                    "entryRaw":entry_raw,"signalATR14":atr[i],
                    "bars":bars,"variants":variants,
                })
                # Re-entry is prohibited until ALL three methods have exited.
                # Excluding the last exit day also avoids same-day refills.
                exits=[e["exitIndex"] for e in variants.values()]
                if any(x is None for x in exits):
                    break
                i=max(exits)+1
    all_cohorts.sort(key=lambda x:(x["entryDate"],x["code"]))
    return all_cohorts,counters,sessions


def accept_common_slots(cohorts, slots=MAX_POSITIONS):
    """Same entries in ALL strategies; block if any strategy lacks a slot."""
    accepted=[]
    blocked=0
    for item in cohorts:
        day=item["entryDate"]
        capacity=True
        for variant in VARIANTS:
            open_count=sum(
                prev["entryDate"]<=day and
                (prev["variants"][variant]["exitDate"] is None or
                 prev["variants"][variant]["exitDate"]>=day)
                for prev in accepted
            )
            if open_count>=slots:
                capacity=False
                break
        if capacity:
            accepted.append(item)
        else:
            blocked+=1
    return accepted,blocked


def net_trade_return(entry_raw, exit_raw):
    buy=entry_raw*(1+ENTRY_SLIPPAGE)*(1+COMMISSION)
    sell=exit_raw*(1-EXIT_SLIPPAGE)*(1-COMMISSION-SELL_TAX)
    return 100*(sell/buy-1)


def trade_stats(cohorts, variant):
    finished=[]
    reasons=Counter()
    open_count=0
    for item in cohorts:
        exit_row=item["variants"][variant]
        if exit_row["exitRaw"] is None:
            open_count+=1
            continue
        net=net_trade_return(item["entryRaw"],exit_row["exitRaw"])
        finished.append(net)
        reasons[exit_row["exitReason"]]+=1
    gains=sum(x for x in finished if x>0)
    losses=-sum(x for x in finished if x<0)
    return {
        "entryCohorts":len(cohorts),"closedTrades":len(finished),
        "stillOpen":open_count,
        "winRatePct":round(100*sum(x>0 for x in finished)/len(finished),2) if finished else None,
        "averageNetReturnPct":round(statistics.mean(finished),3) if finished else None,
        "medianNetReturnPct":round(statistics.median(finished),3) if finished else None,
        "profitFactor":round(gains/losses,3) if losses else None,
        "exitCounts":dict(reasons),
    }


def simulate_portfolio(cohorts, days, variant, capital=INITIAL_CAPITAL,
                       slots=MAX_POSITIONS):
    """Non-leveraged, equal-target-size daily mark-to-market cash ledger.

    Entry list is IDENTICAL for all exits. Shares are fractional here; this
    approximates liquidity, not TWSE 1,000-share board-lot execution.
    """
    first=cohorts[0]["entryDate"] if cohorts else None
    if first is None:
        return {"maxDrawdownPct":None,"equityReturnPct":None,
                "days":0,"openPositions":0,"staleMarkedDays":0}
    dates=sorted(d for d in days if d>=first)
    enters=defaultdict(list)
    closes=defaultdict(list)
    for n,cohort in enumerate(cohorts):
        enters[cohort["entryDate"]].append((n,cohort))
        e=cohort["variants"][variant]
        if e["exitDate"]:
            closes[e["exitDate"]].append((n,cohort))
    cash=float(capital)
    positions={}
    last_marks={}
    stale=0
    peak=capital
    maxdd=0.0
    entry_count=0
    min_cash=capital
    for day in dates:
        def current_price(code):
            candle=days[day].get(code)
            return candle[4] if candle is not None else last_marks.get(code)
        # Open exits execute before new opening buys; intraday stops do NOT
        # fund buys made earlier on the same day.
        for n,c in closes.get(day,[]):
            ex=c["variants"][variant]
            if ex["exitReason"]=="stop_intraday" or n not in positions:
                continue
            qty=positions.pop(n)[0]
            cash+=qty*ex["exitRaw"]*(1-EXIT_SLIPPAGE)*(1-COMMISSION-SELL_TAX)
        # Value existing positions at today's opening quotes when available.
        opening_equity=cash
        for n,(qty,c) in positions.items():
            item=days[day].get(c["code"])
            op=item[0] if item is not None else last_marks.get(c["code"],c["entryRaw"])
            opening_equity+=qty*op
        for n,c in enters.get(day,[]):
            if n in positions or len(positions)>=slots:
                continue
            allocated=min(cash,max(0.0,opening_equity)/slots)
            buy_gross=c["entryRaw"]*(1+ENTRY_SLIPPAGE)*(1+COMMISSION)
            qty=allocated/buy_gross if buy_gross>0 else 0
            if qty<=0:
                continue
            cash-=qty*buy_gross
            positions[n]=(qty,c)
            entry_count+=1
        # Intraday protective stops: after the opening trades, including
        # entry-day stop touches.
        for n,c in closes.get(day,[]):
            ex=c["variants"][variant]
            if ex["exitReason"]!="stop_intraday" or n not in positions:
                continue
            qty=positions.pop(n)[0]
            cash+=qty*ex["exitRaw"]*(1-EXIT_SLIPPAGE)*(1-COMMISSION-SELL_TAX)
        equity=cash
        for n,(qty,c) in positions.items():
            px=current_price(c["code"])
            if px is None:
                px=c["entryRaw"]
            else:
                if c["code"] not in days[day]:
                    stale+=1
            equity+=qty*px
        for code,raw in days[day].items():
            if isinstance(raw,list) and len(raw)==5:
                last_marks[code]=raw[3]
        peak=max(peak,equity)
        if peak>0:
            maxdd=max(maxdd,100*(peak-equity)/peak)
        min_cash=min(cash,min_cash)
    return {
        "maxDrawdownPct":round(maxdd,3),
        "equityReturnPct":round(100*(equity/capital-1),3),
        "days":len(dates),"openPositions":len(positions),
        "entriesExecuted":entry_count,
        "staleMarkedDays":stale,
        "minCash":round(min_cash,2),
        "endEquity":round(equity,2)
    }


def run_study(days, roster, gate="B", snapshots=None):
    candidates,counts,sessions=make_cohorts(days,roster,gate,snapshots)
    selected,blocked=accept_common_slots(candidates)
    sample={
        "status":"exploratory",
        "generatedAt":datetime.now(timezone.utc).isoformat(),
        "marketAsOf":{"上市":sessions["上市"][-1] if sessions["上市"] else None,
                       "上櫃":sessions["上櫃"][-1] if sessions["上櫃"] else None},
        "entryScope":gate,
        "entryRule":"MACD(12,26,9) weighted-close oscillator positive with a crossover in last 3 sessions, strict BB(20,2) expansion, close above rising SMA20, volume >=500 lots",
        "entryDayRule":"signal at completed close, next market session open entry",
        "variants":{
          "MA20":"3 consecutive closes below each day's MA20; next open",
          "FIXED5":"MA20 OR initial 5% below entry open stop",
          "ATR2":"MA20 OR initial stop=entry open - 2*Wilder ATR14 (ATR signal-day), not trailing"
        },
        "fillRules":"Gap opening below stop => open minus slippage; else day low <= stop => stop minus slippage; pending MA20 => next open. Same-open gap stop takes priority over queued MA sell.",
        "costs":{"commissionEachSidePct":100*COMMISSION,
                 "sellTaxPct":100*SELL_TAX,
                 "slippageEachSidePct":100*ENTRY_SLIPPAGE},
        "portfolioAssumptions":{
            "capitalTWD":INITIAL_CAPITAL,"maxSimultaneousPositions":MAX_POSITIONS,
            "allocation":"10% of current opening equity per new position, cash capped, no leverage",
            "sameEntryCohortsForAllExits":True,
            "markToMarket":"end-of-day equity incl unrealized P/L, fees and cash",
            "nonBoardLot":"fractional share approximation"
        },
        "data":{
            "candidateEntrySignals":counts["signalsEligible"],
            "cohortsBeforeCapacity":len(candidates),
            "sameEntryCohortsAccepted":len(selected),
            "capacityBlocked":blocked,
            "firstEntry":selected[0]["entryDate"] if selected else None,
            "lastEntry":selected[-1]["entryDate"] if selected else None,
            "marketSessions":{"上市":len(sessions["上市"]),
                              "上櫃":len(sessions["上櫃"])}
        },
        "results":{},
        "limitations":[
            "回測股票名單為現今仍掛牌股票，可能存在存活者偏差；並非歷史成分股",
            "股票價量資料未還原除權息，假設沒有配息現金流；遇除權息可能扭曲ATR和停損",
            "停損價用日K low 推測成交、無逐筆報價；急跌、跌停、流動性不足時可能無法於預設停損成交",
            "ATR使用Wilder ATR14，以信號日數值決定初始固定保護停損，不是移動停損",
            "為固定進場名單，採共享交易cohort和10槽位資金模型；與單獨最適化每種出場的實際持倉數可能不同",
            "未完成交易不列入已完成交易的勝率和平均報酬，但計入每日組合淨值與最大回撤",
            "零成交、個股交易日K缺漏會截斷資料連續序列；仍持有但無新報價者以最後有效收盤估值",
            "本研究是探索性回測，沒有參數尋優、樣本外驗證或保證投資績效",
        ]
    }
    for variant in VARIANTS:
        sample["results"][variant]={
            **trade_stats(selected,variant),
            "portfolio":simulate_portfolio(selected,days,variant),
        }
    return sample


def main():
    history=json.loads((DATA/"vcp_daily.json").read_text(encoding="utf8"))
    roster=json.loads((DATA/"universe.json").read_text(encoding="utf8"))
    snapshots_path=DATA/"auto_snapshots.json"
    snapshots=json.loads(snapshots_path.read_text(encoding="utf8")) if snapshots_path.exists() else None
    days=history.get("days",{})
    report=run_study(days,roster,gate="B")
    # D1/C has much shorter reliable window; expose separately with a warning.
    if snapshots:
        report["d1Subset"]=run_study(days,roster,gate="C",snapshots=snapshots)
        report["d1Subset"]["warning"]="D1歷史週資料很短；完成交易少時不推論優劣"
    out=DATA/"momentum_exit_comparison.json"
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print("EXIT COMPARISON",report["data"])
    for k,v in report["results"].items():
        print(k,"closed",v["closedTrades"],"open",v["stillOpen"],
              "wins",v["winRatePct"],"avgNet",v["averageNetReturnPct"],
              "PF",v["profitFactor"],"MDD",v["portfolio"]["maxDrawdownPct"],
              "equityReturn",v["portfolio"]["equityReturnPct"])
    if "d1Subset" in report:
        print("D1 SUBSET",report["d1Subset"]["data"])
        for k,v in report["d1Subset"]["results"].items():
            print(" D1",k,"closed",v["closedTrades"],"wins",v["winRatePct"],
                  "MDD",v["portfolio"]["maxDrawdownPct"])


if __name__=="__main__":
    main()
