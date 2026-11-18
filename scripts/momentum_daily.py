"""D1 momentum radar computed from saved TWSE/TPEx daily OHLCV, not from guessed prices.

For each stock, use only bars on or before the evaluation day. XQ-style
WeightedClose=(H+L+2*C)/4, MACD(12,26,9), Bollinger(20,2) and SMA20.
The warm-up and numeric oscillator can differ slightly from XQ; the sign
transition is the intended research signal.
"""
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MIN_BARS = 80


def _ema(values, period):
    alpha = 2.0 / (period + 1)
    result = []
    for value in values:
        result.append(value if not result else result[-1] + alpha * (value - result[-1]))
    return result


def _sma(values):
    return sum(values) / len(values)


def _bands(closes):
    mid = _sma(closes)
    var = sum((v - mid) ** 2 for v in closes) / len(closes)
    sd = math.sqrt(max(0.0, var))
    return mid, mid + 2 * sd, mid - 2 * sd


def assess(bars):
    """Return flags and diagnostics; never claim a pass on short/incomplete data.

    OHLCV bars are [ISO date, open, high, low, close, lots] oldest first.
    """
    if not isinstance(bars, list) or len(bars) < MIN_BARS:
        return {"status": "資料不足", "bars": len(bars) if isinstance(bars, list) else 0,
                "reason": "至少需要80根連續有效日K，現有資料不足"}
    if any(len(b) != 6 or not all(isinstance(x, (int, float)) and
           math.isfinite(x) and x > 0 for x in b[1:]) or
           b[2] < max(b[1], b[4]) or b[3] > min(b[1], b[4]) for b in bars):
        return {"status": "資料不足", "bars": len(bars), "reason": "部分OHLCV欄位無效"}
    closes = [b[4] for b in bars]
    weighted = [(b[2] + b[3] + 2 * b[4]) / 4 for b in bars]
    fast, slow = _ema(weighted, 12), _ema(weighted, 26)
    dif = [a - b for a, b in zip(fast, slow)]
    signal = _ema(dif, 9)
    osc = [a - b for a, b in zip(dif, signal)]
    cross = [osc[i] > 0 and osc[i-1] <= 0 for i in range(len(osc))]
    mid, up, dn = _bands(closes[-20:])
    prevmid, prevup, prevdn = _bands(closes[-21:-1])
    bandwidth = (up - dn) / mid * 100 if mid > 0 else None
    prevwidth = (prevup - prevdn) / prevmid * 100 if prevmid > 0 else None
    widen = bandwidth is not None and prevwidth is not None and bandwidth > prevwidth
    strict = widen and up > prevup and dn < prevdn
    ma = {d: _sma(closes[-20-d:len(closes)-d]) for d in (0, 1, 3, 5)}
    above = closes[-1] > ma[0]
    slope = {str(d): ma[0] > ma[d] for d in (1, 3, 5)}
    volume = bars[-1][5]
    today = bool(cross[-1])
    recent = bool(osc[-1] > 0 and any(cross[-3:]))
    original = today and strict and above and slope["1"] and volume >= 500
    relaxed = recent and strict and above and slope["1"] and volume >= 500
    below3 = all(closes[-i] < _sma(closes[-20-i+1:len(closes)-i+1])
                 for i in (1, 2, 3))
    return {
        "status": "原始訊號" if original else ("三日MACD訊號" if relaxed else "未通過"),
        "bars": len(bars), "date": bars[-1][0], "close": round(closes[-1], 4),
        "volumeLots": round(volume, 2),
        "macdOsc": round(osc[-1], 6), "macdFlipToday": today, "macdFlip3": recent,
        "bbWiden": widen, "bbStrict": strict,
        "bbBandwidthPct": round(bandwidth, 3) if bandwidth is not None else None,
        "bbUpper": round(up, 4), "bbLower": round(dn, 4),
        "ma20": round(ma[0], 4), "aboveMA20": above,
        "maUp": slope, "distMA20Pct": round((closes[-1] / ma[0] - 1) * 100, 2),
        "belowMA20ThreeDays": below3, "passOriginal": original,
        "passRecent3": relaxed
    }


def build(days, roster, market_as_of=None):
    """Publish current per-stock assessments; market date guards stale symbols."""
    market_as_of = market_as_of or {}
    if not isinstance(days, dict) or not isinstance(roster, dict):
        raise ValueError("Missing OHLCV day map or stock roster")
    series = defaultdict(list)
    for day in sorted(days)[-260:]:
        rows = days[day]
        if not isinstance(rows, dict):
            continue
        for code, values in rows.items():
            if code in roster and isinstance(values, list) and len(values) == 5:
                series[code].append([day, *values])
    if not market_as_of:
        market_as_of = {}
        for market in ("上市", "上櫃"):
            dates = [day for day in sorted(days) if sum(
                1 for code in days[day] if code in roster and roster[code].get("market") == market
            ) >= 200]
            market_as_of[market] = dates[-1] if dates else None
    # Report why an active stock is missing from the full-confidence screen.
    # A market-day gap may be no trade/suspension OR an incomplete upstream
    # capture: DO NOT substitute yesterday's close or certify its signal.
    market_sessions = {}
    for market in ("上市", "上櫃"):
        market_sessions[market] = [
            day for day in sorted(days)[-260:]
            if isinstance(days[day], dict) and sum(
                1 for c in days[day] if c in roster and roster[c].get("market") == market
            ) >= 200
        ]
    checks = {}
    by_type = defaultdict(int)
    by_market = defaultdict(lambda: defaultdict(int))
    for code, info in roster.items():
        market = info.get("market", "")
        stock_bars = series.get(code, [])
        result = assess(stock_bars)
        expected = market_sessions.get(market, [])[-MIN_BARS:]
        available = {bar[0] for bar in stock_bars}
        missing = [date for date in expected if date not in available]
        market_date = market_as_of.get(market)
        last = stock_bars[-1] if stock_bars else None
        kind = "ready"
        reason = None
        if not last:
            kind = "no_history"
            reason = "沒有取得任何官方有效日K（可能停牌、零成交或資料來源未包含）"
        elif market_date and last[0] != market_date:
            kind = "stale"
            reason = f"最新個股成交K線 {last[0]}，市場盤後行情 {market_date}"
        elif len(expected) < MIN_BARS:
            kind = "market_short"
            reason = f"市場歷史盤後資料僅 {len(expected)}/{MIN_BARS} 個交易日"
        elif len(stock_bars) < MIN_BARS:
            kind = "short"
            reason = f"有效日K只有 {len(stock_bars)}/{MIN_BARS} 根（可能新上市、停牌或成交資料缺漏）"
        elif missing:
            kind = "gap"
            reason = (f"最近{MIN_BARS}個市場交易日缺少 {len(missing)} 日有效日K；"
                      f"例：{', '.join(missing[:3])}。可能零成交、停牌或官方報表漏列")
        # Individual latest traded bars can still show exploratory indicators.
        # However *any* missing market session removes the pass flag.
        if kind != "ready":
            result["status"] = "行情落後" if kind == "stale" else "資料不足"
            result["passOriginal"] = False
            result["passRecent3"] = False
            result["referenceOnly"] = True
            if last:
                result.setdefault("date", last[0])
                result.setdefault("close", round(last[4], 4))
                result.setdefault("volumeLots", round(last[5], 2))
        result["dataQuality"] = kind
        result["reason"] = reason
        result["lastQuoteDate"] = last[0] if last else None
        result["missingSessionCount"] = len(missing)
        result["missingDatesSample"] = missing[:5]
        result["availableMarketSessions"] = len(expected) - len(missing)
        result["name"] = info.get("name", "")
        result["market"] = market
        checks[code] = result
        by_type[kind] += 1
        by_market[market][kind] += 1
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "marketAsOf": market_as_of, "minBars": MIN_BARS,
        "model": "WCL(H+L+2C)/4 MACD(12,26,9); Bollinger(20,2); SMA20; 500張",
        "limitations": "未還原除權息；缺日K僅顯示參考數值、不提供確認訊號；均線/EMA起始值可能與XQ略異；不代表歷史回測",
        "evaluatedStocks": by_type["ready"],
        "originalSignals": sum(a.get("passOriginal", False) for a in checks.values()),
        "recent3Signals": sum(a.get("passRecent3", False) for a in checks.values()),
        "coverage": {
            "total": len(roster),
            "ready": by_type["ready"],
            "byReason": dict(by_type),
            "byMarket": {m: dict(v) for m, v in by_market.items()}
        },
        "assessments": checks
    }


def main():
    cache = json.loads((DATA / "vcp_daily.json").read_text(encoding="utf-8"))
    roster = json.loads((DATA / "universe.json").read_text(encoding="utf-8"))
    vcp_path = DATA / "vcp_signals.json"
    vcp = json.loads(vcp_path.read_text(encoding="utf-8")) if vcp_path.exists() else {}
    result = build(cache.get("days", {}), roster, vcp.get("marketAsOf"))
    (DATA / "momentum_signals.json").write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8")
    print(f"Momentum: {result['evaluatedStocks']} assessed; {result['originalSignals']} exact; "
          f"{result['recent3Signals']} within 3 sessions")


if __name__ == "__main__":
    main()
