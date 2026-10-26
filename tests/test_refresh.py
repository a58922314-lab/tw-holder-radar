"""Regression tests for official-market data and derived weekly classification."""
import unittest
from unittest.mock import patch
from scripts import refresh


class RadarTests(unittest.TestCase):
    def test_tdcc_big_holder_percentage_is_level_12_through_15(self):
        rows = [
            {'證券代號':'2330','資料日期':'1151022','持股分級':str(i),
             '占集保庫存數比例%':str(i),'人數':'1'}
            for i in range(1,16)
        ]
        rows.append({'證券代號':'2330','資料日期':'1151022','持股分級':'17','人數':'12789'})
        date, values=refresh.tdcc_parse(rows)
        self.assertEqual(date,'2026-10-22')
        self.assertEqual(values['2330']['big'],54.0) # 12+13+14+15
        self.assertEqual(values['2330']['thousand'],15)
        self.assertEqual(values['2330']['owners'],12789)

    def test_historical_price_parses_official_market_tables(self):
        twse={'stat':'OK','tables':[{'fields':['證券代號','證券名稱','收盤價'],
               'data':[['2330','台積電','1,135.00'],['0050','ETF','70.10'],
               ['2317','鴻海','--']]}]}
        tpex={'stat':'ok','tables':[{'fields':['代號','名稱','收盤'],
               'data':[['6488','環球晶','264.00'],['8446','華研','<span>87.5</span>']]}]}
        self.assertEqual(refresh._parse_history(twse,'上市'),{'2330':1135})
        self.assertEqual(refresh._parse_history(tpex,'上櫃'),{'6488':264,'8446':87.5})

    def test_incomplete_and_invalid_history_does_not_invent_returns(self):
        roster={'2330':{'name':'台積電','market':'上市'}}
        weeks={'2330':{'big':62.9,'thousand':30.2,'retail':13.1,'owners':500}}
        prior={'2330':{'big':61.2,'thousand':29.8,'retail':13.6,'owners':550}}
        older={'2330':{'big':60.3,'thousand':29.3,'retail':14.0,'owners':600}}
        rec=refresh.make_records('2026-10-22',weeks,prior,older,roster,{},'2026-10-16')[0]
        self.assertEqual(rec['delta'],1.7)
        self.assertEqual(rec['priorDelta'],0.9)
        self.assertIsNone(rec['returnPct'])
        self.assertIsNone(rec['margin'])

    def test_margin_uses_financing_today_not_short_selling(self):
        from scripts.margin import parse_margin
        fields=['股票代號','股票名稱','買進','賣出','現償','前日餘額','今日餘額','限額','買進','賣出','現償','前日餘額','今日餘額','限額']
        rows=[['2330','台積電','4','3','0','850','842','1000','8','2','0','200','999','1000']]
        payload={'stat':'OK','tables':[{'fields':fields,'data':rows}]}
        self.assertEqual(parse_margin(payload,'上市').get('2330'),842)
        otc=[{'SecuritiesCompanyCode':'6488','MarginBalance':'1,200'}]
        self.assertEqual(parse_margin(otc,'上櫃').get('6488'),1200)
        fields_otc=['代號','名稱','前資餘額']+[f'資料{i}' for i in range(3,20)]
        vals=['6488','環球晶','500','0','0','0','475']+['0']*13
        self.assertEqual(parse_margin({'stat':'OK','tables':[{'fields':fields_otc,'data':[vals]}]},'上櫃').get('6488'),475)

    def test_tdcc_denominator_total_comes_from_level17_real_share_count(self):
        rows=[{'證券代號':'2330','資料日期':'1151022','持股分級':str(i),
               '占集保庫存數比例%':'1','股數':'1000','人數':'10'}
              for i in range(1,16)]
        rows.append({'證券代號':'2330','資料日期':'1151022','持股分級':'17','股數':'25000000000','人數':'30000'})
        d,out=refresh.tdcc_parse(rows)
        self.assertEqual(out['2330']['totalShares'],25000000000)

    def test_a1_institution_parsers_check_accounting_identity(self):
        from scripts.a1_institutional import parse_twse,parse_tpex,weekly_institutional
        fields=['證券代號','外陸資買賣超股數(不含外資自營商)',
                '外資自營商買賣超股數','投信買賣超股數',
                '自營商買賣超股數(自行買賣)','自營商買賣超股數(避險)',
                '三大法人買賣超股數']
        good=['2330','2000','1','3000','-500','200','4700']
        self.assertEqual(parse_twse({'stat':'OK','tables':[{'fields':fields,'data':[good]}]})['2330']['foreign'],2000)
        bad=good.copy();bad[-1]='999999'
        self.assertEqual(parse_twse({'stat':'OK','tables':[{'fields':fields,'data':[bad]}]}),{})
        row=['0']*24
        row[0]='6257';row[4]='12000';row[13]='2000';row[16]='500';row[19]='-100';row[22]='400';row[23]='14400'
        self.assertEqual(parse_tpex({'aaData':[row]})['6257']['trust'],2000)
        row[23]='999'
        self.assertEqual(parse_tpex({'aaData':[row]}),{})
        self.assertIsNone(weekly_institutional('2026-10-16','2026-10-22','6257','上櫃',{}, {})['foreignWeekly'])

    def test_table_price_is_latest_dated_close_not_placeholder(self):
        roster={'2330':{'name':'台積電','market':'上市'},
                '6257':{'name':'矽格','market':'上櫃'}}
        holder={'2330':{'big':58,'thousand':18,'retail':22,'owners':800},
                '6257':{'big':42,'thousand':14,'retail':30,'owners':600}}
        previous={'2330':{'big':57,'thousand':17,'retail':23,'owners':850},
                  '6257':{'big':41,'thousand':13,'retail':32,'owners':620}}
        prices={'2026-10-16':{'2330':1020,'6257':69.5},
                '2026-10-22':{'2330':1030,'6257':71.0},
                '2026-10-23':{'2330':1050}}
        rows=refresh.make_records('2026-10-22',holder,previous,{},roster,prices,'2026-10-16')
        bycode={r['code']:r for r in rows}
        self.assertEqual(bycode['2330']['latestPrice'],1050)
        self.assertEqual(bycode['2330']['latestPriceDate'],'2026-10-23')
        self.assertEqual(bycode['6257']['latestPrice'],71)
        self.assertEqual(bycode['6257']['latestPriceDate'],'2026-10-22')
        self.assertEqual(bycode['2330']['returnPct'],0.98)
        self.assertIsNone(refresh.latest_close({},'2330')[1])

    def test_backfill_rejects_tiny_market_responses(self):
        prices={}
        roster={str(i):{'market':'上市','name':'測試'} for i in range(1100,2500)}
        roster.update({str(i):{'market':'上櫃','name':'測試'} for i in range(3000,4500)})
        with patch.object(refresh,'download',return_value=b'{"stat":"OK","tables":[]}'):
            warnings=refresh.backfill_week_closes(prices,['2026-10-22'],roster)
        self.assertEqual(len(warnings),2)
        self.assertEqual(prices['2026-10-22'],{})


if __name__=='__main__':unittest.main()
