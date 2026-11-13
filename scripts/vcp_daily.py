"""Official TWSE/TPEx daily OHLCV collection and approximate VCP pre-breakout scan.

Only completed daily bars are used. All VCP rows require actual historical OHLCV;
weekly holder snapshots are joined at presentation time, never fabricated.
"""
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TWSE_LATEST = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_LATEST = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
LOOKBACK_CALENDAR_DAYS = 385
MAX_SESSIONS = 260
MIN_BARS = 76
SEGMENT = 25
# Up to 22 missed weekdays per market per refresh: resume incrementally on next run.
BACKFILL_PER_RUN = max(0, min(80, int(os.getenv("VCP_BACKFILL_PER_RUN", "22"))))


def _number(s):
    if s is None:
        return None
    s = re.sub(r"<[^>]*>", "", str(s)).replace(",", "").strip()
    try:
        f = float(s)
        return f if f == f and abs(f) != float("inf") else None
    except ValueError:
        return None


def _iso(s):
    s = str(s or "").strip()
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{7}", s):
        return f"{int(s[:3])+1911:04d}-{s[3:5]}-{s[5:7]}"
    if re.fullmatch(r"\d{8}", s) and s.startswith("20"):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if re.fullmatch(r"\d{3}/\d{2}/\d{2}", s):
        a, b, c = s.split("/")
        return f"{int(a)+1911:04d}-{b}-{c}"
    return None


def _get(r, *names):
    for key in names:
        if key in r and r[key] not in (None, ""):
            return r[key]
    return None


def _parse_row(r, day):
    code = re.sub(r"<[^>]*>", "", str(_get(r, "Code", "SecuritiesCompanyCode", "SecuritiesCode",
                                            "證券代號", "股票代號", "代號") or "")).strip()
    if not re.fullmatch(r"[1-9]\d{3}", code):
        return None
    d = _iso(_get(r, "Date", "date", "日期", "資料日期")) or day
    if d != day:
        return None
    fields = [
        ("OpeningPrice", "Open", "開盤價", "開盤"),
        ("HighestPrice", "High", "最高價", "最高"),
        ("LowestPrice", "Low", "最低價", "最低"),
        ("ClosingPrice", "Close", "收盤價", "收盤"),
        ("TradeVolume", "TradingShares", "成交股數", "成交量"),
    ]
    values = [_number(_get(r, *f)) for f in fields]
    if any(x is None for x in values):
        return None
    op, hi, lo, cl, shares = values
    if min(op, hi, lo, cl) <= 0 or shares <= 0:
        return None
    if hi < max(op, cl, lo) or lo > min(op, cl, hi):
        return None
    return code, [round(op, 4), round(hi, 4), round(lo, 4), round(cl, 4),
                  round(shares / 1000, 3)]  # Lots; both official feeds provide shares.


def parse_latest(payload, market):
    """Validate source dates and named fields instead of guessing column offsets."""
    from scripts.refresh import date as parse_date
    if not isinstance(payload, list):
        raise ValueError("Latest feed not a list")
    group = defaultdict(dict)
    for r in payload:
        if not isinstance(r, dict):
            continue
        day = _iso(_get(r, "Date", "date")) or parse_date(_get(r, "Date", "date"))
        if day:
            row = _parse_row(r, day)
            if row:
                group[day][row[0]] = row[1]
    if not group:
        raise ValueError("No official daily OHLCV data")
    latest = max(group)
    result = group[latest]
    if len(result) < 250:
        raise ValueError(f"{market} daily coverage too low: {len(result)}")
    return latest, result


def parse_history(payload, day):
    """Historical TWSE MI_INDEX / TPEx afterTrading/otc, keyed by named headers."""
    if not isinstance(payload, dict) or str(payload.get("stat", "")).lower() not in ("ok", ""):
        return {}
    tables = list(payload.get("tables") or [])
    if isinstance(payload.get("data"), list) and payload.get("fields"):
        tables.insert(0, {"fields": payload["fields"], "data": payload["data"]})
    result = {}
    for table in tables:
        headers = [re.sub(r"\s+", "", str(h)) for h in table.get("fields") or []]
        needed = (("代號", "證券代號", "股票代號"),
                  ("最高", "最高價"), ("最低", "最低價"),
                  ("收盤", "收盤價"), ("成交股數", "成交量"))
        if not all(any(k in headers for k in group) for group in needed):
            continue
        for row in table.get("data") or table.get("aaData") or []:
            record = dict(zip(headers, row)) if isinstance(row, list) and len(row) == len(headers) else row
            if not isinstance(record, dict):
                continue
            parsed = _parse_row(record, day)
            if parsed:
                result[parsed[0]] = parsed[1]
    return result


def history_url(market, day):
    if market == "上市":
        return ("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date="
                + day.replace("-", "") + "&type=ALLBUT0999&response=json")
    return ("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?response=json"
            "&type=EW&date=" + quote(day.replace("-", "/"), safe=""))


def _mean(vals):
    return sum(vals) / len(vals)


def scan_one(bars):
    """A 3x25-session fixed-window proxy, NOT subjective swing-based VCP.

    Bars are chronological [date, open, high, low, close, volume_lots].
    Excludes today's price and volume from pivot / volume dry-up reference.
    Returns None unless all conditions (including distance 1..3%) pass.
    """
    if len(bars) < MIN_BARS:
        return None
    today = bars[-1]
    prev = bars[:-1]
    day, _, _, _, close, volume = today
    if close <= 0 or volume < 500:
        return None
    ma50 = _mean([x[4] for x in bars[-50:]])
    if close <= ma50:
        return None
    # A more rigorous trend template is required once 220+ bars exist.
    if len(bars) >= 220:
        ma150 = _mean([x[4] for x in bars[-150:]])
        ma200 = _mean([x[4] for x in bars[-200:]])
        old200 = _mean([x[4] for x in bars[-220:-20]])
        if not (ma50 > ma150 > ma200 and ma200 > old200):
            return None
    if len(bars) >= 250:
        low52 = min(x[3] for x in bars[-250:])
        high52 = max(x[2] for x in bars[-250:])
        if close < low52 * 1.3 or close < high52 * 0.75:
            return None

    segments = [prev[-75:-50], prev[-50:-25], prev[-25:]]
    depths = []
    for seg in segments:
        h = max(x[2] for x in seg)
        l = min(x[3] for x in seg)
        depths.append((h - l) / h * 100)
    d1, d2, d3 = depths
    if not (d1 >= 10 and d1 > d2 > d3 and d3 <= 10):
        return None

    v50 = _mean([x[5] for x in prev[-50:]])
    v10 = _mean([x[5] for x in prev[-10:]])
    if v50 <= 0 or v10 / v50 >= 0.7:
        return None
    pivot = max(x[2] for x in segments[-1])
    distance = (pivot / close - 1) * 100
    if not (1 <= distance <= 3 and close < pivot):
        return None
    return {
        "date": day, "close": round(close, 2), "pivot": round(pivot, 2),
        "distancePct": round(distance, 2),
        "depthsPct": [round(x, 2) for x in depths],
        "dryRatio": round(v10 / v50, 3),
        "volumeLots": round(volume, 1),
        "bars": len(bars),
        "grade": "完整趨勢" if len(bars) >= 250 else ("均線趨勢" if len(bars) >= 220 else "初步觀察"),
    }


def scan_all(days, roster):
    by_code = defaultdict(list)
    dates = sorted(days)[-MAX_SESSIONS:]
    for day in dates:
        for code, row in days[day].items():
            if code in roster:
                by_code[code].append([day] + row)
    results = []
    covered = 0
    for code, bars in by_code.items():
        if len(bars) < MIN_BARS:
            continue
        covered += 1
        item = scan_one(bars)
        if item:
            result = {"code": code, "name": roster[code]["name"],
                      "market": roster[code]["market"]}
            result.update(item)
            results.append(result)
    results.sort(key=lambda x: (x["distancePct"], x["dryRatio"], x["code"]))
    return covered, results


def collect(roster, download, read, write, batch=BACKFILL_PER_RUN):
    """Collect latest official daily OHLCV and a small historical catch-up batch.

    Historical source issues are reported; they never produce dummy candles.
    Uses one chronological session as a unit, not a per-stock API request.
    """
    cache = read("vcp_daily.json", {"days": {}, "skipped": {"上市": [], "上櫃": []}})
    days = cache.get("days") or {}
    skipped = cache.get("skipped") or {"上市": [], "上櫃": []}
    warnings = []
    recent_by_market = {}
    for market, url in (("上市", TWSE_LATEST), ("上櫃", TPEX_LATEST)):
        try:
            day, records = parse_latest(json.loads(download(url).decode("utf-8-sig")), market)
            records = {k: v for k, v in records.items()
                       if k in roster and roster[k].get("market") == market}
            if len(records) < 200:
                raise ValueError("Too few stocks matched official company list")
            days.setdefault(day, {}).update(records)
            recent_by_market[market] = day
        except Exception as err:
            warnings.append(f"VCP {market} 當日行情: {str(err)[:130]}")

    newest = max(recent_by_market.values(), default=max(days, default=None))
    if newest:
        end = datetime.fromisoformat(newest).date()
        first = end - timedelta(days=LOOKBACK_CALENDAR_DAYS)
        wanted = []
        dt = end - timedelta(days=1)
        while dt >= first and len(wanted) < 365:
            if dt.weekday() < 5:
                wanted.append(dt.isoformat())
            dt -= timedelta(days=1)
        for market in ("上市", "上櫃"):
            misses = 0
            known_skipped = set(skipped.get(market, []))
            for day in wanted:
                if misses >= batch:
                    break
                have = sum(1 for code in days.get(day, {})
                           if code in roster and roster[code].get("market") == market)
                if have >= 200 or day in known_skipped:
                    continue
                misses += 1
                try:
                    payload = json.loads(download(history_url(market, day)).decode("utf-8-sig"))
                    found = parse_history(payload, day)
                    matched = {c: r for c, r in found.items()
                               if c in roster and roster[c].get("market") == market}
                    if len(matched) >= 200:
                        days.setdefault(day, {}).update(matched)
                    elif not found and str(payload.get("stat", "")).lower() in ("ok", "沒有符合條件的資料", "no data"):
                        known_skipped.add(day)  # Verified empty session / public holiday.
                    else:
                        warnings.append(f"VCP {market} {day} 歷史行情不足 {len(found)} 檔")
                except Exception as err:
                    warnings.append(f"VCP {market} {day}: {str(err)[:100]}")
            skipped[market] = sorted(known_skipped)[-300:]

        cutoff = (end - timedelta(days=LOOKBACK_CALENDAR_DAYS)).isoformat()
        days = {k: v for k, v in days.items() if k >= cutoff}
        # Avoid accidentally retaining out-of-order / impossible future sessions.
        days = {k: v for k, v in days.items() if k <= newest}
    write("vcp_daily.json", {"days": days, "skipped": skipped})
    covered, candidates = scan_all(days, roster)
    # Report each market's actual last verified quote day.
    by_market_date = {}
    for market in ("上市", "上櫃"):
        ds = [d for d in days if sum(1 for code in days[d]
              if code in roster and roster[code].get("market") == market) >= 200]
        by_market_date[market] = max(ds, default=None)
    # Drop stale symbols if one market is behind, and do not mix different dates.
    candidates = [r for r in candidates if r["date"] == by_market_date.get(r["market"])]
    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "marketAsOf": by_market_date, "storedSessions": len(days),
        "eligibleStocks": covered, "candidateCount": len(candidates),
        "model": "25+25+25 日固定區間近似 VCP；不是完整波段辨識或買進建議",
        "warnings": warnings[:25], "candidates": candidates
    }
    write("vcp_signals.json", result)
    return result
