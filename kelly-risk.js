"use strict";
const el=id=>document.getElementById(id);
const inputIds=["price","capital","usedCapital","winRate","takeProfitPct","stopLossPct","costPct","sampleSize","fraction","riskPct","maxPositionPct","maxPortfolioPct","lotSize"];
const pct=n=>Number.isFinite(n)?n.toLocaleString("zh-TW",{minimumFractionDigits:2,maximumFractionDigits:2})+"%":"—";
const money=n=>Number.isFinite(n)?"NT$ "+Math.floor(n+0.000001).toLocaleString("zh-TW"):"—";
const fnum=(n,d=2)=>Number.isFinite(n)?n.toLocaleString("zh-TW",{minimumFractionDigits:d,maximumFractionDigits:d}):"—";
const put=(id,value)=>{el(id).textContent=String(value);};
const params=new URLSearchParams(location.search);
const query={
 code:params.get("code"),name:params.get("name"),
 price:params.get("price"), date:params.get("date"),signal:params.get("signal")
};
if(query.code && /^[\w.-]{1,10}$/.test(query.code))el("stockCode").value=query.code;
if(query.name)el("stockName").value=query.name.slice(0,35);
if(query.signal && [...el("signal").options].some(x=>x.value===query.signal))el("signal").value=query.signal;
if(query.price && Number.isFinite(Number(query.price)) && Number(query.price)>0) {
 el("price").value=Number(query.price);
 el("quoteNote").textContent="股價由雷達個股快照帶入"+(query.date?"（資料日期："+query.date.slice(0,20)+"）":"")+"；非即時交易報價。";
}
function resetOutput(){
 for(const id of ["fullKelly","fractionalKelly","budget","shares","actualCapital","expectation","breakEven","targetPrice","stopPrice","maxLoss","potentialProfit","exposure","effectiveRisk"])put(id,"—");
 el("budgetBar").style.width="0";
 put("bindingNote","請先修正輸入參數。");
}
function render(){
 const o=Object.fromEntries(inputIds.map(id=>[id,Number(el(id).value)]));
 // Empty controls are invalid; Number("") would incorrectly turn them into 0.
 for(const id of inputIds)if(el(id).value.trim()==="")o[id]=NaN;
 const r=window.KellyRisk.calculate(o);
 const status=el("status");
 if(!r.valid){
  resetOutput();status.className="status error";status.textContent="資料無法計算：\n"+r.errors.join("；");return;
 }
 const signal=el("signal").value,stock=el("stockCode").value.trim();
 let prefix=stock?stock+" · ":"";
 let note=prefix+signal+" 的回測勝率尚未經本站確認。";
 if(r.sampleSize===0)note+="目前使用示範假設，不能視為入場建議。";
 else if(r.sampleSize<30)note+="輸入的交易筆數少於 30 筆，估計非常不穩定。";
 else note+="筆數為自行填寫，尚未核對交易明細或樣本外績效。";
 if(!r.positiveEdge)note+=" 扣除交易成本後沒有正期望值，此情境不建立部位。";
 if(r.positiveEdge && r.shares===0)note+=" 風控上限或整張交易單位使可買股數為零，可改用零股檢視。";
 status.className=r.positiveEdge?"status":"status error";
 status.textContent=note;
 put("fullKelly",pct(r.fullKellyPct));
 put("fractionalKelly",money(r.theoreticalCapital));
 put("budget",money(r.capitalBudget));
 el("budgetBar").style.width=Math.min(100,100*r.capitalBudget/o.capital)+"%";
 const bind={fractionalKelly:"分數凱利",risk:"單筆帳戶風險",singlePosition:"單股集中度",portfolio:"整體持股曝險",cash:"剩餘可用資金"};
 put("bindingNote",!r.positiveEdge?"勝率及賺賠比不足以支持正期望值。":r.binding?r.binding.split(",").map(x=>bind[x]||x).join("、")+"限制了最高投入金額。":"經過風控限制；尚未達到理論凱利金額。");
 put("shares",r.shares.toLocaleString("zh-TW")+" 股"+(o.lotSize===1000?"（"+fnum(r.lots,0)+" 張）":""));
 put("actualCapital",money(r.actualCapital));
 put("expectation",pct(r.expectation*100));
 put("breakEven",pct(r.breakEvenWinRate));
 put("targetPrice",fnum(r.takeProfitPrice,2)+" 元");
 put("stopPrice",fnum(r.stopPrice,2)+" 元");
 put("maxLoss",money(r.maxLoss));
 put("potentialProfit",money(r.potentialNetProfit));
 put("exposure",pct(r.actualExposurePct));
 put("effectiveRisk",pct(r.actualRiskPct));
}
for(const id of inputIds)el(id).addEventListener("input",render);
el("signal").addEventListener("change",render);
el("stockCode").addEventListener("input",render);
render();
