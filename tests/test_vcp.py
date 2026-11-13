"""Tests for VCP official OHLCV collection and pre-breakout screening."""
import unittest
from scripts import vcp_daily


class VCPTests(unittest.TestCase):
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
        self.assertEqual(result["grade"], "初步觀察")

    def test_history_date_is_checked_by_source(self):
        source = [{"Code": "2001", "Date": "1151111", "OpeningPrice": 10,
                   "HighestPrice": 12, "LowestPrice": 9, "ClosingPrice": 11,
                   "TradeVolume": 200000}]
        self.assertIsNone(vcp_daily._parse_row(source[0], "2026-11-12"))


if __name__ == "__main__":
    unittest.main()
