"""Tests for VCP official OHLCV collection and pre-breakout screening."""
import unittest
import json
import tempfile
from pathlib import Path
from scripts import vcp_daily


class VCPTests(unittest.TestCase):
    @staticmethod
    def pattern_bars():
        return ([[f"{i:03d}", 90, 100, 80, 94, 1100] for i in range(25)]
                + [[f"{i:03d}", 93, 100, 87, 96, 950] for i in range(25, 50)]
                + [[f"{i:03d}", 97, 100, 95, 98, 300] for i in range(50, 75)]
                + [["075", 98, 99, 96, 98, 650]])

    def test_diagnostics_keep_failed_conditions_and_real_metrics(self):
        bars = self.pattern_bars()
        bars[-1] = ["075", 90, 99, 89, 90, 100]
        result = vcp_daily.evaluate_one(bars)
        self.assertIsNone(vcp_daily.scan_one(bars))
        self.assertEqual(result["status"], "not_met")
        self.assertEqual(result["pivot"], 100)
        self.assertAlmostEqual(result["distancePct"], 11.11)
        self.assertGreater(result["dryRatio"], 0)
        for key in ("distance", "liquidity", "trend"):
            self.assertFalse(result["checks"][key])
        self.assertEqual(len(result["reasons"]), 3)
        self.assertTrue(result["checks"]["strictContraction"])

    def test_partial_missing_and_invalid_bars_are_not_failures_or_zero_prices(self):
        for bars in ([], self.pattern_bars()[:75]):
            result = vcp_daily.evaluate_one(bars)
            self.assertEqual(result["status"], "insufficient")
            self.assertIsNone(result["distancePct"])
            self.assertIsNone(result["dryRatio"])
            self.assertTrue(result["dataIssues"])
        for bad in (float('nan'), None, -1):
            bars = self.pattern_bars()
            bars[-1][4] = bad
            self.assertEqual(vcp_daily.evaluate_one(bars)["status"], "insufficient")

    def test_zero_reference_volume_is_unavailable(self):
        bars = self.pattern_bars()
        for bar in bars[:-1]:
            bar[5] = 0
        result = vcp_daily.evaluate_one(bars)
        self.assertIsNone(result["dryRatio"])
        self.assertIsNone(result["checks"]["dry"])
        self.assertEqual(result["status"], "insufficient")

    def test_all_roster_stocks_survive_even_with_zero_candidates_and_stale_quotes(self):
        bars = self.pattern_bars()
        roster = {c: {"name": c, "market": "上市"} for c in ("2001", "2002", "2003")}
        days = {b[0]: {"2001": b[1:]} for b in bars}
        days[bars[-1][0]]["2002"] = bars[-1][1:]
        covered, candidates, rows = vcp_daily.evaluate_all(days, roster, {"上市": "076"})
        self.assertEqual(covered, 1)
        self.assertEqual(candidates, [])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["status"] == "insufficient" for r in rows))
        self.assertEqual(rows[0]["date"], "075")
        self.assertEqual(rows[0]["pivot"], 100)
        self.assertIsNone(rows[2]["close"])

    def test_diagnostics_and_original_candidate_api_agree(self):
        bars = self.pattern_bars()
        for close, volume in ((98, 650), (90, 650), (101, 650), (98, 499)):
            bars[-1] = ["075", close, close + 1, close - 1, close, volume]
            diagnostic = vcp_daily.evaluate_one(bars)
            candidate = vcp_daily.scan_one(bars)
            self.assertEqual(diagnostic["candidate"], candidate is not None)
        self.assertEqual(vcp_daily.evaluate_one(self.pattern_bars())["status"], "passed")

    def test_deploy_rebuild_uses_saved_dates_and_keeps_failed_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            roster = {str(code): {"name": str(code), "market": "上市"} for code in range(2000, 2200)}
            days = {bar[0]: {code: bar[1:] for code in roster} for bar in self.pattern_bars()}
            payloads = {"vcp_daily.json": {"days": days}, "universe.json": roster,
                        "vcp_signals.json": {"candidates": [], "warnings": ["source coverage warning"]}}
            for filename, payload in payloads.items():
                (data / filename).write_text(json.dumps(payload), encoding="utf-8")
            report = vcp_daily.rebuild_saved_report(data)
            self.assertEqual(report["marketAsOf"]["上市"], "075")
            self.assertEqual(report["warnings"], ["source coverage warning"])
            self.assertEqual(len(report["evaluations"]), 200)
            self.assertEqual(report["candidateCount"], 200)
            saved = json.loads((data / "vcp_signals.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, report)

    def test_parse_twse_latest_and_volume_lots(self):
        rows = [
            {"Date": "1151112", "Code": str(i), "OpeningPrice": "90.0",
             "HighestPrice": "105", "LowestPrice": "88", "ClosingPrice": "100",
             "TradeVolume": "1200000"}
            for i in range(2000, 2310)
        ]
        day, result = vcp_daily.parse_latest(rows, "上市")
        self.assertEqual(day, "2026-11-12")
        self.assertEqual(result["2000"], [90, 105, 88, 100, 1200])

    def test_parse_tpex_historical_with_named_fields(self):
        payload = {"stat": "ok", "tables": [{
            "fields": ["代號", "名稱", "開盤", "最高", "最低", "收盤", "成交股數"],
            "data": [["6488", "環球晶", "310", "314", "302", "312", "420000"]]
        }]}
        self.assertEqual(vcp_daily.parse_history(payload, "2026-11-12")["6488"],
                         [310, 314, 302, 312, 420])

    def test_no_signal_with_insufficient_candles(self):
        self.assertIsNone(vcp_daily.scan_one([[str(i), 10, 11, 9, 10, 600]
                                              for i in range(75)]))

    def test_no_signal_when_not_dry_or_too_far(self):
        bars = [["2026-01-01", 100, 105, 95, 100, 900] for _ in range(76)]
        self.assertIsNone(vcp_daily.scan_one(bars))

    def test_fixed_window_vcp_can_find_near_pivot(self):
        bars = []
        # Three declining high-low ranges: 20%, 13%, 5%; pivot 100.
        for i in range(25):
            bars.append([f"day{i}", 88, 100, 80, 94, 1100])
        for i in range(25, 50):
            bars.append([f"day{i}", 93, 100, 87, 96, 950])
        for i in range(50, 75):
            bars.append([f"day{i}", 97, 100, 95, 98, 300])
        bars.append(["today", 98, 99, 96, 98, 650])
        result = vcp_daily.scan_one(bars)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["distancePct"], 1)
        self.assertLessEqual(result["distancePct"], 3)
        self.assertEqual(result["grade"], "嚴格三段收縮")
        self.assertTrue(result["strict"])
        self.assertEqual(result["trendGrade"], "初步趨勢")

    def test_history_date_is_checked_by_source(self):
        source = [{"Code": "2001", "Date": "1151111", "OpeningPrice": 10,
                   "HighestPrice": 12, "LowestPrice": 9, "ClosingPrice": 11,
                   "TradeVolume": 200000}]
        self.assertIsNone(vcp_daily._parse_row(source[0], "2026-11-12"))


if __name__ == "__main__":
    unittest.main()
