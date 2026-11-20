"""Gap, intraday trigger, ATR lookahead and identical-entry regression tests."""
import unittest
from datetime import date, timedelta
from scripts import momentum_exit_comparison as ex
from scripts.momentum_daily import assess


def bars(closes, opens=None, lows=None):
    out=[]
    start=date(2026,1,1)
    for i,close in enumerate(closes):
        op=opens[i] if opens else close
        low=lows[i] if lows else min(op,close)-1
        hi=max(op,close)+1
        out.append([(start+timedelta(days=i)).isoformat(),op,hi,low,close,600])
    return out


class ExitStudyTests(unittest.TestCase):
    def test_wilder_atr_not_based_on_future_bars(self):
        b=bars([100]*90+[200,300])
        a=ex.wilder_atr(b)
        self.assertEqual(a[13],2)
        self.assertEqual(a[89],2)
        self.assertGreater(a[90],2)
        self.assertEqual(ex.stop_level("ATR2",100,a[89]),96)
        self.assertAlmostEqual(ex.stop_level("FIXED5",100,a[89]),95)

    def test_signal_is_identical_to_production_assess(self):
        b=bars([100]*80+[105,105,105]+[100]*7)
        sig=ex.b_signals(b)
        for i in range(79,len(b)-1):
            self.assertEqual(sig[i],assess(b[:i+1])["passRecent3"],i)

    def test_gap_sells_at_open_not_stop_price(self):
        b=bars([100]*80+[100,90,90],opens=[100]*81+[91,90])
        fixed=ex.simulate_exit(b,80,"FIXED5",2)
        self.assertEqual(fixed["exitDate"],b[81][0])
        self.assertEqual(fixed["exitReason"],"stop_gap")
        self.assertEqual(fixed["exitRaw"],91)
        atr=ex.simulate_exit(b,80,"ATR2",2)
        self.assertEqual(atr["exitRaw"],91)
        self.assertEqual(ex.simulate_exit(b,80,"MA20",2)["exitDate"],None)

    def test_intraday_first_entry_day_can_stop(self):
        b=bars([100]*81,lows=[99]*80+[94])
        fixed=ex.simulate_exit(b,80,"FIXED5",2)
        self.assertEqual(fixed["exitIndex"],80)
        self.assertEqual(fixed["exitRaw"],95)
        self.assertEqual(fixed["exitReason"],"stop_intraday")
        ma=ex.simulate_exit(b,80,"MA20",2)
        self.assertIsNone(ma["exitRaw"])

    def test_third_close_below_ma_triggers_next_open_not_close(self):
        cls=[100]*81+[98,97,96,99]
        op=[100]*84+[101]
        b=bars(cls,opens=op)
        ma=ex.simulate_exit(b,80,"MA20",2)
        self.assertEqual(ma["exitIndex"],84)
        self.assertEqual(ma["exitRaw"],101)
        self.assertEqual(ma["exitReason"],"ma20_next_open")

    def test_expenses_deducted_and_can_exceed_fixed_five_pct(self):
        self.assertLess(ex.net_trade_return(100,100),0)
        self.assertLess(ex.net_trade_return(100,94),-5)
        self.assertAlmostEqual(ex.net_trade_return(100,100),
          100*((1-ex.EXIT_SLIPPAGE)*(1-ex.COMMISSION-ex.SELL_TAX)
                 / ((1+ex.ENTRY_SLIPPAGE)*(1+ex.COMMISSION))-1))

    def test_slot_limiting_identical_for_all_exits(self):
        b=bars([100]*90)
        candidates=[]
        for i in range(5):
            variants={"MA20":{"exitDate":b[85][0]},
                      "FIXED5":{"exitDate":b[82][0]},
                      "ATR2":{"exitDate":b[83][0]}}
            candidates.append({"code":str(2000+i),"entryDate":b[80][0],"variants":variants})
        accepted, blocked=ex.accept_common_slots(candidates,slots=2)
        self.assertEqual(len(accepted),2)
        self.assertEqual(blocked,3)

    def test_funded_portfolio_uses_unrealized_marks_and_no_leverage(self):
        b=bars([100]*80+[100,90,90],opens=[100]*82+[90])
        s=ex.simulate_exit(b,80,"FIXED5",2)
        item={"code":"3001","entryDate":b[80][0],"entryRaw":100,
              "variants":{"FIXED5":s}}
        daymap={bar[0]:{"3001":bar[1:]} for bar in b}
        result=ex.simulate_portfolio([item],daymap,"FIXED5",slots=2)
        self.assertEqual(result["entriesExecuted"],1)
        self.assertGreater(result["maxDrawdownPct"],0)
        self.assertGreaterEqual(result["minCash"],-0.01)
        self.assertEqual(result["openPositions"],0)
        self.assertGreater(result["equityReturnPct"],-10)
        self.assertLess(result["equityReturnPct"],0)
        self.assertLess(result["maxDrawdownPct"],10)

    def test_unrealized_close_uses_close_not_volume(self):
        b=bars([100]*81+[90,90])
        item={"code":"3001","entryDate":b[80][0],"entryRaw":100,
              "variants":{"MA20":{"exitDate":None,"exitRaw":None,"exitReason":"unclosed"}}}
        daymap={bar[0]:{"3001":bar[1:]} for bar in b}
        result=ex.simulate_portfolio([item],daymap,"MA20",slots=2)
        self.assertEqual(result["openPositions"],1)
        self.assertLess(result["equityReturnPct"],0)
        self.assertGreater(result["equityReturnPct"],-15)
        self.assertGreater(result["maxDrawdownPct"],3)
        self.assertLess(result["maxDrawdownPct"],15)

    def test_ma20_exit_on_gap_day_not_intraday_price(self):
        cls=[100]*81+[98,97,96,96]
        op=[100]*84+[88]
        b=bars(cls,opens=op)
        out=ex.simulate_exit(b,80,"MA20",5)
        self.assertEqual(out["exitReason"],"ma20_next_open")
        self.assertEqual(out["exitRaw"],88)


if __name__=="__main__":
    unittest.main()
