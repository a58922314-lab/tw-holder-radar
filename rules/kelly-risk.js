/* Kelly money management research engine.
 * This is a deterministic sizing calculator, NOT a backtester or a stock signal.
 * Input profit/stop percentages are returns on the whole stock position.
 * Round-trip cost includes estimated fees, tax and slippage in percentage points.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.KellyRisk = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const finite = x => typeof x === "number" && Number.isFinite(x);
  const nonneg = x => finite(x) && x >= 0;
  const positive = x => finite(x) && x > 0;
  const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

  function calculate(o) {
    const errors = [];
    if (!o || typeof o !== "object") return {valid:false, errors:["缺少參數"]};
    if (!positive(o.capital)) errors.push("總資金必須大於零");
    if (!positive(o.price)) errors.push("參考股價必須大於零");
    if (!finite(o.winRate) || o.winRate < 0 || o.winRate > 100) errors.push("勝率必須介於 0% 與 100%");
    if (!positive(o.takeProfitPct)) errors.push("平均獲利幅度必須大於零");
    if (!positive(o.stopLossPct) || o.stopLossPct >= 100) errors.push("平均虧損幅度必須介於 0% 與 100%");
    if (!nonneg(o.costPct)) errors.push("來回交易成本不能是負數");
    if (!positive(o.fraction) || o.fraction > 1) errors.push("凱利比例必須介於 0 與 1");
    for (const key of ["riskPct","maxPositionPct","maxPortfolioPct"]) {
      if (!nonneg(o[key]) || o[key] > 100) errors.push(key+" 必須介於 0% 與 100%");
    }
    if (!nonneg(o.usedCapital)) errors.push("已使用資金不能為負數");
    if (positive(o.capital) && nonneg(o.usedCapital) && o.usedCapital > o.capital) errors.push("已使用資金不能高於總資金");
    if (!Number.isInteger(o.lotSize) || ![1,1000].includes(o.lotSize)) errors.push("交易單位只能是 1 股或 1,000 股");
    if (!Number.isInteger(o.sampleSize) || o.sampleSize < 0) errors.push("歷史交易筆數不能為負數");
    if (errors.length) return {valid:false, errors};
    const p=o.winRate/100, q=1-p;
    const gain=(o.takeProfitPct-o.costPct)/100;
    const loss=(o.stopLossPct+o.costPct)/100;
    if (gain <= 0) {
      return {valid:false,errors:["交易成本已經大於或等於平均獲利，請重新檢查參數"]};
    }
    const expectation=p*gain-q*loss;
    const rawKelly=expectation/(gain*loss);
    const fullKelly=Math.max(0,rawKelly);
    const chosenKelly=fullKelly*o.fraction;
    const kellyCapital=o.capital*chosenKelly;
    const riskCapital=o.capital*(o.riskPct/100)/loss;
    const positionCapital=o.capital*o.maxPositionPct/100;
    const portfolioCapital=Math.max(0,o.capital*o.maxPortfolioPct/100-o.usedCapital);
    const cashCapital=Math.max(0,o.capital-o.usedCapital);
    const capitalBudget=Math.max(0,Math.min(kellyCapital,riskCapital,positionCapital,portfolioCapital,cashCapital,o.capital));
    const shares=Math.max(0,Math.floor(capitalBudget/(o.price*o.lotSize))*o.lotSize);
    const actualCapital=shares*o.price;
    const maxLoss=actualCapital*loss;
    const potentialNetProfit=actualCapital*gain;
    const constraints=[
      {key:"fractionalKelly",label:"分數凱利",value:kellyCapital},
      {key:"risk",label:"單筆風險",value:riskCapital},
      {key:"singlePosition",label:"單一股票",value:positionCapital},
      {key:"portfolio",label:"投資組合",value:portfolioCapital},
      {key:"cash",label:"可用資金",value:cashCapital}
    ];
    const binding=expectation<=0?"none":constraints.filter(x=>x.value<=capitalBudget+0.00001).map(x=>x.key).join(",");
    return {
      valid:true, sampleSize:o.sampleSize, verifiedHistory:false,
      p, gain, loss, expectation, breakEvenWinRate:loss/(gain+loss)*100,
      fullKelly, chosenKelly, fullKellyPct:fullKelly*100,
      theoreticalCapital:kellyCapital, capitalBudget, constraints, binding,
      shares, lots:shares/1000, actualCapital, maxLoss, potentialNetProfit,
      actualRiskPct:100*maxLoss/o.capital, actualExposurePct:100*actualCapital/o.capital,
      stopPrice:o.price*(1-o.stopLossPct/100),
      takeProfitPrice:o.price*(1+o.takeProfitPct/100),
      positiveEdge:expectation>0, needsEvidence:o.sampleSize<30
    };
  }
  return Object.freeze({calculate});
});
