"""Tests for honest daily-data completeness and bounded official gap recovery."""
import json
import unittest
from datetime import date, timedelta

from scripts import momentum_daily as momentum
from scripts import vcp_daily as vcp


def fixture():
    roster={str(3000+i):{"name":"測試股","market":"上市"} for i in range(250)}
    roster["1218"]={"name":"泰山","market":"上市"}
    dates=[(date(2026,4,1)+timedelta(days=i)).isoformat() for i in range(82)]
    days={d:{code:[100,101,99,100,600] for code in roster} for d in dates}
    gap=dates[44]
    del days[gap]["1218"]
    days[dates[-1]]["1218"]=[105,106,104,105,600]
    return roster,dates,days,gap


class CoverageTests(unittest.TestCase):
    def test_single_missing_market_day_keeps_reference_indicators_but_no_signal(self):
        roster,dates,days,gap=fixture()
        result=momentum.build(days,roster,{"上市":dates[-1]})
        item=result["assessments"]["1218"]
        self.assertEqual(item["status"],"資料不足")
        self.assertEqual(item["dataQuality"],"gap")
        self.assertEqual(item["missingDatesSample"],[gap])
        self.assertEqual(item["date"],dates[-1])
        self.assertEqual(item["close"],105)
        self.assertTrue(item["referenceOnly"])
        self.assertIn("macdOsc",item)
        self.assertFalse(item["passOriginal"])
        self.assertFalse(item["passRecent3"])
        self.assertEqual(result["coverage"]["byReason"]["gap"],1)
        self.assertEqual(result["coverage"]["ready"],250)

    def test_no_data_never_turns_into_price_or_buy_signal(self):
        roster,dates,days,gap=fixture()
        roster["9999"]={"name":"無成交","market":"上市"}
        result=momentum.build(days,roster,{"上市":dates[-1]})
        item=result["assessments"]["9999"]
        self.assertEqual(item["dataQuality"],"no_history")
        self.assertNotIn("close",item)
        self.assertFalse(item["passOriginal"])
        self.assertTrue(item["referenceOnly"])

    def test_repair_official_missing_row_only(self):
        roster,dates,days,gap=fixture()
        payload={"stat":"OK","tables":[{"fields":["證券代號","開盤價","最高價","最低價","收盤價","成交股數"],
                                      "data":[["1218","99","102","97","100","600000"]]}]}
        fetches=[]
        def download(url):
            fetches.append(url)
            return json.dumps(payload).encode("utf-8")
        filled,checked,attempts,warnings=vcp.repair_individual_bar_gaps(
            days,roster,download,per_market_limit=3)
        self.assertEqual(filled,1)
        self.assertEqual(checked,1)
        self.assertFalse(warnings)
        self.assertEqual(days[gap]["1218"],[99,102,97,100,600])
        self.assertEqual(attempts["上市:"+gap],1)
        after=momentum.build(days,roster,{"上市":dates[-1]})
        self.assertEqual(after["assessments"]["1218"]["dataQuality"],"ready")
        self.assertEqual(after["coverage"]["ready"],251)
        self.assertTrue(any(gap.replace("-","/") not in u for u in fetches))  # TWSE uses YYYYMMDD.

    def test_zero_volume_not_synthesized_and_retry_is_bounded(self):
        roster,dates,days,gap=fixture()
        payload={"stat":"OK","tables":[{"fields":["證券代號","開盤價","最高價","最低價","收盤價","成交股數"],
                                      "data":[["1218","99","102","97","100","0"]]}]}
        def download(url):
            return json.dumps(payload).encode("utf-8")
        attempts={}
        for attempt in range(2):
            filled,checked,attempts,_=vcp.repair_individual_bar_gaps(
                days,roster,download,attempts,per_market_limit=3)
            self.assertEqual(filled,0)
            self.assertEqual(checked,1)
        filled,checked,attempts,_=vcp.repair_individual_bar_gaps(
            days,roster,download,attempts,per_market_limit=3)
        self.assertEqual((filled,checked),(0,0))
        self.assertNotIn("1218",days[gap])


if __name__=="__main__":
    unittest.main()
