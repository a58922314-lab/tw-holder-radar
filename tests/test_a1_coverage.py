import json
import unittest
from unittest.mock import Mock
from scripts.a1_institutional import (parse_holidays, expected_sessions,
    collect_institutional, weekly_institutional)


class A1CoverageTests(unittest.TestCase):
    def test_calendar_excludes_only_explicit_closures_not_first_trading_day(self):
        payload={'stat':'ok','queryYear':2026,'data':[
            ['2026-01-02','國曆新年開始交易日','國曆新年開始交易。'],
            ['2026-10-09','國慶日','國慶日為10月10日適逢星期六，於10月9日（星期五）補假。'],
            ['2026-02-12','市場無交易，僅辦理結算交割作業','']]}
        closed=parse_holidays(payload,2026)
        self.assertNotIn('2026-01-02',closed)
        self.assertIn('2026-02-12',closed)
        self.assertEqual(expected_sessions('2026-10-08','2026-10-16',{'2026':{'closedDates':closed}}),
                         ['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'])
        with self.assertRaises(ValueError):parse_holidays(payload,2025)

    def test_missing_one_weekday_is_not_silently_assumed_a_holiday(self):
        dates=['2026-10-19','2026-10-20','2026-10-21']
        hist={d:{'上市':{'2330':{'foreign':1000,'trust':0,'dealer':0}}} for d in dates}
        prices={d:{str(i):1 for i in range(1000)} for d in dates}
        r=weekly_institutional('2026-10-16','2026-10-22','2330','上市',hist,prices)
        self.assertEqual((r['instCoverage'],r['instExpected']),(3,4))
        self.assertIsNone(r['foreignWeekly'])
        self.assertEqual(r['instMissingReasons'],{'2026-10-22':'report_unavailable'})

    def test_complete_reports_do_not_require_prices_or_round_away_net_buying(self):
        hist={'2026-10-19':{'上櫃':{'7806':{'foreign':1,'trust':0,'dealer':0}}}}
        r=weekly_institutional('2026-10-16','2026-10-19','7806','上櫃',hist,{})
        self.assertEqual(r['foreignWeekly'],0.001)
        self.assertEqual((r['instCoverage'],r['instExpected']),(1,1))
        absent=weekly_institutional('2026-10-16','2026-10-19','9999','上櫃',hist,{})
        self.assertIsNone(absent['foreignWeekly'])
        self.assertEqual(absent['instMissingReasons'],{'2026-10-19':'report_not_listed'})

    def test_collect_backfills_all_displayed_weeks_without_price_cache(self):
        weeks={d:{} for d in ['2026-09-25','2026-10-02','2026-10-08','2026-10-16','2026-10-22']}
        download=Mock(return_value=b'{"stat":"ok","date":"19000101"}')
        saved={}
        hist,warnings=collect_institutional(weeks,{}, {},download,
            lambda n,default:default,lambda n,v:saved.update({n:v}),
            {'2026':{'closedDates':['2026-09-28','2026-10-09']}})
        urls=[call.args[0] for call in download.call_args_list]
        self.assertTrue(any('20260929' in url for url in urls))
        self.assertTrue(any('20261012' in url for url in urls))
        self.assertFalse(any('20261009' in url or '2026%2F10%2F09' in url for url in urls))
        self.assertTrue(all(not row for row in hist.values()))
        self.assertTrue(all('date/status mismatch' in warning for warning in warnings))

    def test_wrong_date_response_cannot_preserve_unverified_legacy_cache(self):
        legacy={'2026-10-19':{'上市':{str(i):{'foreign':1,'trust':0,'dealer':0} for i in range(1000,2000)}}}
        hist,warnings=collect_institutional({'2026-10-16':{},'2026-10-19':{}},{},{},
            lambda url:b'{"stat":"OK","date":"20261020"}',
            lambda name,default:legacy if name=='institutional_daily.json' else default,
            lambda *args:None)
        self.assertEqual(hist['2026-10-19'],{})
        self.assertEqual(len(warnings),2)

    def test_cache_retains_report_stock_before_roster_adds_it(self):
        fields=['證券代號','外陸資買賣超股數(不含外資自營商)',
                '投信買賣超股數','自營商買賣超股數(自行買賣)',
                '自營商買賣超股數(避險)','三大法人買賣超股數']
        codes=[str(i) for i in range(1000,1200)]
        payload={'stat':'OK','date':'20261019','fields':fields,
                 'data':[[c,'1','0','0','0','1'] for c in codes+['1299']]}
        roster={c:{'market':'上市'} for c in codes}
        saved={}
        read=lambda name,default:saved.get(name,default)
        write=lambda name,value:saved.update({name:value})
        download=Mock(return_value=json.dumps(payload).encode())
        weeks={'2026-10-16':{},'2026-10-19':{}}
        hist,_=collect_institutional(weeks,{},roster,download,read,write)
        self.assertIn('1299',hist['2026-10-19']['上市'])
        roster['1299']={'market':'上市'}
        download.reset_mock()
        hist,_=collect_institutional(weeks,{},roster,download,read,write)
        self.assertFalse(any('twse.com.tw' in c.args[0] for c in download.call_args_list))
        self.assertEqual(weekly_institutional('2026-10-16','2026-10-19','1299','上市',hist,{})['foreignWeekly'],.001)


if __name__=='__main__':unittest.main()
