"""Official TWSE/TPEx daily OHLCV collection and approximate VCP pre-breakout scan.

Only completed daily bars are used. All VCP rows require actual historical OHLCV;
weekly holder snapshots are joined at presentation time, never fabricated.
"""
import json
import os
import re
import time
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
BACKFILL_PER_RUN = max(0, min(80, int(os.getenv("VCP_BACKFILL_PER_RUN", "65"))))
# Retry missing individual-stock OHLCV even when a date has >200 securities.
GAP_REPAIR_PER_RUN = max(0, min(25, int(os.getenv("VCP_GAP_REPAIR_PER_RUN", "12"))))
GAP_REPAIR_MAX_CHECKS = 2


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
    if not isinstance(payload, list):
        raise ValueError("Latest feed not a list")
    group = defaultdict(dict)
    for r in payload:
        if not isinstance(r, dict):
            continue
        day = _iso(_get(r, "Date", "date"))
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


def assess_one(bars):
    """Return explainable status for every stock, including failed or missing VCP.

    Missing K bars never count as a pass; no weekly D1 data are inferred here.
    Pivot, dry-up and depths use ONLY candles before the evaluation day.
    """
    if not bars:
        return {"status": "資料不足", "reasons": ["缺少官方日K行情"],
                "bars": 0, "strict": False}
    last = bars[-1]
    day, _, _, _, close, volume = last
    output = {
        "date": day, "close": round(close, 2),
        "volumeLots": round(volume, 1), "bars": len(bars),
        "strict": False, "status": "資料不足", "reasons": [],
        "trendGrade": "初步趨勢" if len(bars) < 220 else
                      ("完整趨勢" if len(bars) >= 250 else "均線趨勢")
    }
    if len(bars) < MIN_BARS:
        output["reasons"] = [f"歷史K線不足（{len(bars)}/{MIN_BARS}日）"]
        return output
    prev = bars[:-1]
    reasons = []
    if close <= 0:
        reasons.append("收盤價無效")
    if volume < 500:
        reasons.append("當日量低於500張")

    ma50 = _mean([x[4] for x in bars[-50:]])
    if close <= ma50:
        reasons.append("收盤未站穩50日線")
    if len(bars) >= 220:
        ma150 = _mean([x[4] for x in bars[-150:]])
        ma200 = _mean([x[4] for x in bars[-200:]])
        old200 = _mean([x[4] for x in bars[-220:-20]])
        if not (ma50 > ma150 > ma200 and ma200 > old200):
            reasons.append("50／150／200日線趨勢未通過")
    if len(bars) >= 250:
        low52 = min(x[3] for x in bars[-250:])
        high52 = max(x[2] for x in bars[-250:])
        if close < low52 * 1.3 or close < high52 * 0.75:
            reasons.append("52週高低點位置未通過")

    segments = [prev[-75:-50], prev[-50:-25], prev[-25:]]
    depths = []
    for segment in segments:
        h = max(x[2] for x in segment)
        l = min(x[3] for x in segment)
        depths.append((h - l) / h * 100)
    d1, d2, d3 = depths
    pivot = max(x[2] for x in segments[-1])
    distance = (pivot / close - 1) * 100 if close > 0 else None
    v50 = _mean([x[5] for x in prev[-50:]])
    v10 = _mean([x[5] for x in prev[-10:]])
    dry = v10 / v50 if v50 > 0 else None

    output.update({
        "pivot": round(pivot, 2),
        "distancePct": round(distance, 2) if distance is not None else None,
        "depthsPct": [round(x, 2) for x in depths],
        "dryRatio": round(dry, 3) if dry is not None else None
    })
    if not (distance is not None and 1 <= distance <= 3 and close < pivot):
        reasons.append("距樞紐不在突破前1%～3%")
    if d3 > 12:
        reasons.append("末段波動超過12%")
    if dry is None or dry >= 0.9:
        reasons.append("10／50日成交量未達縮量比0.9")

    strict_shape = d1 >= 10 and d1 > d2 > d3 and d3 <= 10
    strict_dry = dry is not None and dry < 0.7
    strict = strict_shape and strict_dry and not reasons
    output["strict"] = strict
    output["reasons"] = reasons
    output["status"] = ("嚴格三段收縮" if strict else
                        "縮量近樞紐" if not reasons else "未符合")
    # Notes are non-blocking, but do not assert the full Minervini trend
    # template without the necessary history.
    if len(bars) < 250:
        output["note"] = f"僅有{len(bars)}根K線；完整趨勢樣板需250根"
    return output


def scan_one(bars):
    """Legacy VCP candidate API: keep passing-only behaviour and fields."""
    result = assess_one(bars)
    if result["status"] not in ("縮量近樞紐", "嚴格三段收縮"):
        return None
    result["grade"] = result["status"]
    return result


def scan_all(days, roster):
    """Build daily diagnostics for ALL stocks, plus VCP-only candidates."""
    by_code = defaultdict(list)
    dates = sorted(days)[-MAX_SESSIONS:]
    for day in dates:
        for code, row in days[day].items():
            if code in roster:
                by_code[code].append([day] + row)
    diagnostics = {}
    results = []
    covered = 0
    for code, bars in by_code.items():
        item = assess_one(bars)
        diagnostics[code] = item
        if len(bars) < MIN_BARS:
            continue
        covered += 1
        if item["status"] in ("縮量近樞紐", "嚴格三段收縮"):
            results.append({"code": code, "name": roster[code]["name"],
                            "market": roster[code]["market"],
                            **item, "grade": item["status"]})
    results.sort(key=lambda x: (x["distancePct"], x["dryRatio"], x["code"]))
    return covered, results, diagnostics


def repair_individual_bar_gaps(days, roster, download, attempts=None,
                               per_market_limit=GAP_REPAIR_PER_RUN):
    """Re-fetch official full-day reports for sparse stock-level gaps.

    Previously, a market day with >=200 quotes was never revisited for stock
    gaps. A candidate code must have real observations shortly before and
    after the missing day. This does not prove the security traded that day.
    Only official valid rows are inserted; bounded attempt history prevents
    repeated requests when legitimate no-trade gaps persist.
    """
    attempts = attempts if isinstance(attempts, dict) else {}
    if not per_market_limit:
        return 0, 0, attempts, []
    warnings = []
    filled_total = 0
    checks = 0
    for market in ("上市", "上櫃"):
        members = {c for c, r in roster.items() if r.get("market") == market}
        sessions = [d for d in sorted(days)[-MAX_SESSIONS:]
                    if isinstance(days[d], dict) and
                    sum(c in members for c in days[d]) >= 200][-100:]
        candidates = []
        for i in range(1, len(sessions)-1):
            day = sessions[i]
            nearby_before = set()
            nearby_after = set()
            for other in sessions[max(0, i-3):i]:
                nearby_before.update(c for c in days[other] if c in members)
            for other in sessions[i+1:i+4]:
                nearby_after.update(c for c in days[other] if c in members)
            observed = {c for c in days[day] if c in members}
            absent = (nearby_before & nearby_after) - observed
            if absent and int(attempts.get(market + ":" + day, 0)) < GAP_REPAIR_MAX_CHECKS:
                candidates.append((len(absent), day, absent))
        candidates.sort(key=lambda item: (-item[0], -int(item[1].replace("-", ""))))
        for _, day, missing in candidates[:per_market_limit]:
            key = market + ":" + day
            attempts[key] = int(attempts.get(key, 0)) + 1
            checks += 1
            try:
                time.sleep(0.35)
                payload = json.loads(download(history_url(market, day)).decode("utf-8-sig"))
                records = parse_history(payload, day)
                recovered = 0
                for code in missing:
                    if code in records and code in roster and roster[code].get("market") == market:
                        days[day][code] = records[code]
                        recovered += 1
                filled_total += recovered
                if recovered:
                    print("Recovered stock-level OHLCV gaps",market,day,"filled",recovered,
                          "of",len(missing))
            except Exception as err:
                warnings.append(f"補抓個股日K {market} {day}: {str(err)[:115]}")
    recent_days = set(sorted(days)[-130:])
    attempts = {k:v for k,v in attempts.items() if k.split(":")[-1] in recent_days
                and isinstance(v, int) and v > 0}
    return filled_total, checks, attempts, warnings


def collect(roster, download, read, write, batch=BACKFILL_PER_RUN):
    """Collect latest official daily OHLCV and a small historical catch-up batch.

    Historical source issues are reported; they never produce dummy candles.
    Uses one chronological session as a unit, not a per-stock API request.
    """
    cache = read("vcp_daily.json", {"days": {}, "skipped": {"上市": [], "上櫃": []}})
    days = cache.get("days") or {}
    skipped = cache.get("skipped") or {"上市": [], "上櫃": []}
    repair_attempts = cache.get("repairAttempts") or {}
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
                    time.sleep(0.35)  # Be considerate of exchange history endpoints.
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

        recovered, checked, repair_attempts, repair_warnings = repair_individual_bar_gaps(
            days, roster, download, repair_attempts
        )
        warnings.extend(repair_warnings)
        print(f"Daily OHLCV gap repair: checked {checked} official reports; "
              f"recovered {recovered} valid missing stock bars")
        cutoff = (end - timedelta(days=LOOKBACK_CALENDAR_DAYS)).isoformat()
        days = {k: v for k, v in days.items() if k >= cutoff}
        # Avoid accidentally retaining out-of-order / impossible future sessions.
        days = {k: v for k, v in days.items() if k <= newest}
    write("vcp_daily.json", {"days": days, "skipped": skipped, "repairAttempts": repair_attempts})
    covered, candidates, diagnostics = scan_all(days, roster)
    # Report each market's actual last verified quote day.
    by_market_date = {}
    for market in ("上市", "上櫃"):
        ds = [d for d in days if sum(1 for code in days[d]
              if code in roster and roster[code].get("market") == market) >= 200]
        by_market_date[market] = max(ds, default=None)
    # Drop stale symbols if one market is behind, and do not mix different dates.
    candidates = [r for r in candidates if r["date"] == by_market_date.get(r["market"])]
    for code, item in diagnostics.items():
        market = roster[code]["market"]
        if item.get("date") != by_market_date.get(market):
            item["status"] = "行情落後"
            item["strict"] = False
            item["reasons"] = [f"此股行情{item.get('date', '缺失')}，市場最新{by_market_date.get(market) or '未知'}"]
    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "marketAsOf": by_market_date, "storedSessions": len(days),
        "eligibleStocks": covered, "candidateCount": len(candidates),
        "strictCandidateCount": sum(1 for c in candidates if c["strict"]),
        "model": "近樞紐縮量觀察：末段振幅≤12%、量縮比<0.9；嚴格三段版再要求逐段收縮且量縮比<0.7；不是完整波段 VCP",
        "warnings": warnings[:25], "candidates": candidates,
        "assessments": diagnostics
    }
    write("vcp_signals.json", result)
    return result
