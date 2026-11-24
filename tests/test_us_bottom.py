import sys, pathlib, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"scripts"))
from us_bottom import evaluate, parse_options

class BottomTests(unittest.TestCase):
    def test_option_ratio_and_scope(self):
        d={"ratios":[{"name":"TOTAL PUT/CALL RATIO","value":"1.10"}],
           "SPX + SPXW + SPXO":[{"name":"OPEN INTEREST","call":100,"put":140}]}
        self.assertAlmostEqual(parse_options(d)["oi"],1.4)
        self.assertEqual(parse_options(d)["oiScope"],"SPX + SPXW + SPXO")
    def test_missing_options_do_not_pass(self):
        rows=[{"date":str(i),"spx":100,"vix":20} for i in range(280)]
        r=evaluate(rows)
        self.assertEqual(r["coverage"],65)
        self.assertFalse(r["correctionGate"])
        self.assertIsNone(r["rules"][3]["pass"])
        self.assertIsNone(r["rules"][4]["pass"])
        self.assertIsNone(r["rules"][5]["pass"])
    def test_crash_and_rebound(self):
        rows=[{"date":str(i),"spx":100,"vix":20,"pcr":.8,"oi":1.5,"oiScope":"SPX + SPXW"} for i in range(280)]
        for j in range(-20,-3):
            rows[j].update(spx=85,vix=36,pcr=1.3)
        for j in range(-3,0):
            rows[j].update(spx=91+j,vix=24,pcr=.8,oi=1.2-j*.05)
        r=evaluate(rows)
        self.assertTrue(r["correctionGate"])
        self.assertEqual(r["score"],100)
        self.assertEqual(r["coverage"],100)
        rows[-1]["oiScope"]="SPX + SPXW + SPXO"
        self.assertIsNone(evaluate(rows)["rules"][5]["pass"])
if __name__=="__main__": unittest.main()
