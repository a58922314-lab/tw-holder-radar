"""Regression checks for the isolated D1 momentum scanner."""
import unittest
from scripts import momentum_daily as momentum


def bars(closes, start=0):
    out = []
    for i, close in enumerate(closes):
        out.append([f"2026-sample-{i+start:03d}", close, close+1, close-1, close, 600])
    return out


class MomentumTests(unittest.TestCase):
    def test_missing_history_is_not_false_signal(self):
        r = momentum.assess(bars([100] * 79))
        self.assertEqual(r["status"], "資料不足")
        self.assertNotIn("passOriginal", r)

    def test_flat_stock_does_not_pass(self):
        r = momentum.assess(bars([100] * 80))
        self.assertFalse(r["macdFlipToday"])
        self.assertFalse(r["bbStrict"])
        self.assertFalse(r["maUp"]["1"])
        self.assertFalse(r["passOriginal"])

    def test_first_positive_bar_and_two_sided_bollinger(self):
        r = momentum.assess(bars([100] * 79 + [105]))
        self.assertTrue(r["macdFlipToday"])
        self.assertTrue(r["bbStrict"])
        self.assertTrue(r["aboveMA20"])
        self.assertTrue(r["maUp"]["1"])
        self.assertTrue(r["passOriginal"])

    def test_momentum_later_than_macd_cross_rejected_by_original(self):
        r = momentum.assess(bars([100] * 77 + [105, 105, 105]))
        self.assertFalse(r["macdFlipToday"])
        self.assertTrue(r["macdFlip3"])
        self.assertTrue(r["passRecent3"])
        self.assertFalse(r["passOriginal"])

    def test_three_day_mode_requires_oscillator_still_positive(self):
        r = momentum.assess(bars([100] * 77 + [105, 100, 90]))
        self.assertLess(r["macdOsc"], 0)
        self.assertFalse(r["macdFlip3"])

    def test_exit_warning_after_three_daily_closes_below_ma(self):
        r = momentum.assess(bars([100] * 77 + [95, 94, 93]))
        self.assertTrue(r["belowMA20ThreeDays"])
        self.assertFalse(r["aboveMA20"])

    def test_latest_market_date_and_stale_price(self):
        data = {f"d{i:03}":{"6257":[100,101,99,100,600]} for i in range(80)}
        roster = {"6257":{"name":"矽格","market":"上櫃"}}
        latest = momentum.build(data, roster, {"上櫃":"missing-date"})
        r = latest["assessments"]["6257"]
        self.assertEqual(r["status"], "行情落後")
        self.assertFalse(r["passOriginal"])
        self.assertFalse(r["passRecent3"])


if __name__ == "__main__":
    unittest.main()
