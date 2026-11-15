"""Official TWSE/TPEx daily OHLCV collection and approximate VCP pre-breakout scan.

Only completed daily bars are used. All VCP rows require actual historical OHLCV;
weekly holder snapshots are joined at presentation time, never fabricated.
"""
import json
import math
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


def evaluate_one(bars):
    """A 3x25-session fixed-window proxy, NOT subjective swing-based VCP.

    Bars are chronological [date, open, high, low, close, volume_lots].
    Excludes today's price and volume from pivot / volume dry-up reference.
    Keeps failed and unavailable checks so a holder watchlist never loses rows.
    """
    result = {"date": None, "close": None, "pivot": None, "distancePct": None,
              "depthsPct": [], "dryRatio": None, "volumeLots": None,
              "bars": len(bars), "strict": False, "candidate": False,
              "status": "insufficient", "grade": "資料不足", "checks": {},
              "reasons": [], "dataIssues": []}
    if any(len(b) != 6 or any(not isinstance(x, (int, float)) or not math.isfinite(x)
                              for x in b[1:]) or min(b[1:5]) <= 0 or b[5] < 0
           or b[2] < max(b[1], b[3], b[4]) or b[3] > min(b[1], b[4]) for b in bars):
        result["dataIssues"] = ["日 K 價量欄位無效，無法驗證"]
        return result
    if bars:
        result.update(date=bars[-1][0], close=round(bars[-1][4], 2),
                      volumeLots=round(bars[-1][5], 1))
    if len(bars) < MIN_BARS:
        result["dataIssues"] = [f"有效日 K {len(bars)} 根，至少需要 {MIN_BARS} 根"]
        return result
    today = bars[-1]
    prev = bars[:-1]
    day, _, _, _, close, volume = today
    checks = result["checks"]
    checks["liquidity"] = volume >= 500
    ma50 = _mean([x[4] for x in bars[-50:]])
    checks["trend"] = close > ma50
    # A more rigorous trend template is required once 220+ bars exist.
    if len(bars) >= 220:
        ma150 = _mean([x[4] for x in bars[-150:]])
        ma200 = _mean([x[4] for x in bars[-200:]])
        old200 = _mean([x[4] for x in bars[-220:-20]])
        checks["trend"] = checks["trend"] and ma50 > ma150 > ma200 and ma200 > old200
    if len(bars) >= 250:
        low52 = min(x[3] for x in bars[-250:])
        high52 = max(x[2] for x in bars[-250:])
        checks["trend"] = checks["trend"] and close >= low52 * 1.3 and close >= high52 * 0.75

    segments = [prev[-75:-50], prev[-50:-25], prev[-25:]]
    depths = []
    for seg in segments:
        h = max(x[2] for x in seg)
        l = min(x[3] for x in seg)
        depths.append((h - l) / h * 100)
    d1, d2, d3 = depths
    v50 = _mean([x[5] for x in prev[-50:]])
    v10 = _mean([x[5] for x in prev[-10:]])
    dry = v10 / v50 if v50 > 0 else None
    # Separate a strict three-stage pattern from a looser but still contracting
    # watchlist. Never describe the looser tier as a confirmed VCP.
    checks["contraction"] = d3 <= 12
    checks["dry"] = dry < 0.9 if dry is not None else None
    checks["strictContraction"] = d1 >= 10 and d1 > d2 > d3 and d3 <= 10
    checks["strictDry"] = dry < 0.7 if dry is not None else None
    strict = checks["strictContraction"] and checks["strictDry"] is True
    pivot = max(x[2] for x in segments[-1])
    distance = (pivot / close - 1) * 100
    checks["distance"] = 1 <= distance <= 3 and close < pivot
    candidate = all(checks[k] is True for k in ("liquidity", "trend", "contraction", "dry", "distance"))
    labels = {"liquidity": "當日成交量未達 500 張", "trend": "目前歷史長度適用的趨勢條件未達標",
              "contraction": "末段振幅超過 12%", "dry": "10／50 日均量比未低於 0.9",
              "distance": "距樞紐不在 1%～3% 待突破區間"}
    result["reasons"] = [text for key, text in labels.items() if checks[key] is False]
    if dry is None:
        result["dataIssues"].append("前 50 日均量為零，無法計算量縮比")
    result.update({
        "date": day, "close": round(close, 2), "pivot": round(pivot, 2),
        "distancePct": round(distance, 2),
        "depthsPct": [round(x, 2) for x in depths],
        "dryRatio": round(dry, 3) if dry is not None else None,
        "volumeLots": round(volume, 1),
        "bars": len(bars),
        "grade": ("嚴格三段收縮" if strict else "縮量近樞紐") if candidate else "尚未達標",
        "strict": strict,
        "candidate": candidate,
        "status": "insufficient" if result["dataIssues"] else ("passed" if candidate else "not_met"),
        "trendGrade": "完整趨勢" if len(bars) >= 250 else ("均線趨勢" if len(bars) >= 220 else "初步趨勢"),
        "trendNote": "" if len(bars) >= 250 else ("52 週位置需 250 根日 K" if len(bars) >= 220
                       else "完整均線／52 週條件需 220／250 根日 K"),
    })
    if result["dataIssues"]:
        result["grade"] = "資料不足"
    return result


def scan_one(bars):
    """Compatibility API: the independent VCP radar still returns only candidates."""
    result = evaluate_one(bars)
    return result if result["candidate"] else None


def evaluate_all(days, roster, market_as_of=None):
    by_code = defaultdict(list)
    dates = sorted(days)[-MAX_SESSIONS:]
    for day in dates:
        for code, row in days[day].items():
            if code in roster:
                by_code[code].append([day] + row)
    results = []
    evaluations = []
    covered = 0
    for code, stock in roster.items():
        bars = by_code[code]
        covered += len(bars) >= MIN_BARS
        result = {"code": code, "name": stock["name"], "market": stock["market"],
                  **evaluate_one(bars)}
        if market_as_of is not None:
            expected = market_as_of.get(stock["market"])
            if not expected or result["date"] != expected:
                result["dataIssues"].append("缺少市場最新行情：" + (expected or "市場日期待補"))
                result.update(candidate=False, status="insufficient", grade="資料不足")
        evaluations.append(result)
        if result["candidate"]:
            results.append(result)
    results.sort(key=lambda x: (x["distancePct"], x["dryRatio"], x["code"]))
    return covered, results, evaluations


def scan_all(days, roster):
    covered, candidates, _ = evaluate_all(days, roster)
    return covered, candidates


def build_report(days, roster, warnings=()):
    by_market_date = {}
    for market in ("上市", "上櫃"):
        ds = [d for d in days if sum(1 for code in days[d]
              if code in roster and roster[code].get("market") == market) >= 200]
        by_market_date[market] = max(ds, default=None)
    covered, candidates, evaluations = evaluate_all(days, roster, by_market_date)
    return {
        "schemaVersion": 2, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "marketAsOf": by_market_date, "storedSessions": len(days),
        "eligibleStocks": covered, "candidateCount": len(candidates),
        "strictCandidateCount": sum(1 for c in candidates if c["strict"]),
        "model": "近樞紐縮量觀察：末段振幅≤12%、量縮比<0.9；嚴格三段版再要求逐段收縮且量縮比<0.7；不是完整波段 VCP",
        "warnings": list(warnings)[:25], "candidates": candidates, "evaluations": evaluations,
    }


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

        cutoff = (end - timedelta(days=LOOKBACK_CALENDAR_DAYS)).isoformat()
        days = {k: v for k, v in days.items() if k >= cutoff}
        # Avoid accidentally retaining out-of-order / impossible future sessions.
        days = {k: v for k, v in days.items() if k <= newest}
    write("vcp_daily.json", {"days": days, "skipped": skipped})
    result = build_report(days, roster, warnings)
    write("vcp_signals.json", result)
    return result


def rebuild_saved_report(data_dir=DATA):
    """Re-evaluate verified saved candles at deploy time without fetching quotes."""
    def read(name):
        return json.loads((data_dir / name).read_text(encoding="utf-8"))
    old_path = data_dir / "vcp_signals.json"
    previous = read("vcp_signals.json") if old_path.exists() else {}
    report = build_report(read("vcp_daily.json")["days"], read("universe.json"),
                          previous.get("warnings", []))
    old_path.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n",
                        encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", required=True,
                        help="Rebuild diagnostics from saved official candles; no network requests")
    parser.parse_args()
    rebuilt = rebuild_saved_report()
    print(f"VCP: {len(rebuilt['evaluations'])} diagnostics; {rebuilt['candidateCount']} candidates")
