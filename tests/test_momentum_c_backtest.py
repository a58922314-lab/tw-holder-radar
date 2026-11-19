"""Tests that the weekly D1 gate cannot travel back before its data date."""
import unittest
from datetime import date, timedelta
from scripts import momentum_c_backtest as c


def make_week(day, records, previous="2026-10-02", type_="auto"):
    fill = [{"code":str(3000+i), "name":"填充", "delta":0.0,
             "returnPct":1.0, "marginChange":12, "marginBalance":100}
            for i in range(1201)]
    return {"type":type_, "date":day, "compareDate":previous,
            "records":fill + records}


def good(code="6257", whale=1.2, weekly=-1.0, margin=-10, current=110):
    return {"code":code,"name":"測試", "delta":whale,
            "returnPct":weekly,"marginChange":margin,"marginBalance":current}


def candles(days=110):
    start = date(2026, 9, 1)
    closes=[100] * 91 + [105] + [105]*18
    return [[(start+timedelta(days=i)).isoformat(), v, v+1, v-1, v, 600]
            for i,v in enumerate(closes[:days])]


class D1MomentumCBacktestTests(unittest.TestCase):
    def test_d1_qualify_matches_js_rules(self):
        self.assertEqual(c.tier(good()),"D1")
        self.assertEqual(c.tier(good(whale=2.5, margin=-10, current=90)),"D1+")
        self.assertEqual(c.tier(good(margin=1)),None)
        self.assertEqual(c.tier(good(weekly=0.1)),None)
        self.assertEqual(c.tier(good(whale=0.9)),None)
        self.assertEqual(c.tier(good(whale=2.5,current=0,margin=-10)),"D1+")
        self.assertIsNone(c.tier({"delta":1.5,"returnPct":-1,"marginChange":None}))
        self.assertEqual(c.tier(good(whale=2.1,current=95,margin=-1)),"D1")

    def test_snapshot_embargo_and_expiry(self):
        week = make_week("2026-10-09",[good()],"2026-10-02")
        windows=c.make_windows({"snapshots":[week]})
        self.assertEqual(len(windows),1)
        self.assertEqual(windows[0]["start"],"2026-10-16")
        self.assertEqual(windows[0]["endExclusive"],"2026-10-30")
        ix=c.calendar_index(windows)
        self.assertNotIn("2026-10-15",ix)
        self.assertIn("2026-10-16",ix)
        self.assertNotIn("2026-10-30",ix)
        self.assertEqual(ix["2026-10-16"]["tiers"]["6257"],"D1")

    def test_newer_week_replaces_older_no_overlap(self):
        payload={"snapshots":[
            make_week("2026-10-09",[good("6257")],"2026-10-02"),
            make_week("2026-10-16",[good("2233")],"2026-10-09")]}
        windows=c.make_windows(payload)
        ix=c.calendar_index(windows)
        self.assertEqual(ix["2026-10-16"]["tiers"].get("6257"),"D1")
        self.assertEqual(ix["2026-10-23"]["tiers"].get("2233"),"D1")
        self.assertNotIn("6257",ix["2026-10-23"]["tiers"])

    def test_rejects_example_incomplete_and_missing_week_comparison(self):
        payload={"snapshots":[
            make_week("2026-10-09",[good()],"2026-10-02","import"),
            make_week("2026-10-16",[good()],"2026-09-01"),
            {"date":"2026-10-23","type":"auto","compareDate":"2026-10-16",
             "records":[good()]}]}
        self.assertEqual(c.make_windows(payload),[])

    def test_B_signal_eligible_but_C_cannot_read_future_week(self):
        bars=candles()
        event=bars[91][0]
        # One Monday signal, position remains open. Future weekly snapshot
        # should never unlock C on the event date.
        future=date.fromisoformat(event)+timedelta(days=1)
        future_week={ "date": future, "tiers":{"6257":"D1"},
                      "start": (future+timedelta(days=7)).isoformat(),
                      "endExclusive":(future+timedelta(days=14)).isoformat()}
        index=c.calendar_index([future_week])
        trades,opens,signals,entries=c.simulate(bars,index,"6257")
        self.assertEqual(entries["C"],0)
        self.assertEqual(entries["Cplus"],0)
        # The signal falls before the assumed publication date.
        self.assertEqual(entries["B"],0)

    def test_fixed_horizon_excludes_unknown_future_close(self):
        bars=candles(100)
        event=bars[91][0]
        day=date.fromisoformat(event)
        index={event: {"date":day,"tiers":{"6257":"D1"}}}
        results,missing,entered=c.simulate_fixed_horizon(bars,index,"6257",hold_sessions=10)
        self.assertEqual(entered["C"],1)
        self.assertEqual(entered["B"],1)
        self.assertEqual(missing["C"],1)
        self.assertEqual(results["C"],[])

    def test_fixed_horizon_sells_only_after_prespecified_holding(self):
        bars=candles(110)
        event=bars[91][0]
        day=date.fromisoformat(event)
        index={event: {"date":day,"tiers":{"6257":"D1"}}}
        results,missing,entered=c.simulate_fixed_horizon(bars,index,"6257",hold_sessions=5)
        self.assertEqual(missing["C"],0)
        self.assertEqual(entered["C"],1)
        self.assertEqual(results["C"][0]["entry"],bars[92][0])
        self.assertEqual(results["C"][0]["exit"],bars[97][0])

    def test_net_costs_deducted(self):
        result=c.net_return(100,100)
        self.assertLess(result,0)
        self.assertGreater(result,-1)

if __name__=="__main__":
    unittest.main()
