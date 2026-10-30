/* A1: evidence-based concentration screen, not a determination of market manipulation. */
(function(root,build){
 const api=build();
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
 if(root)root.A1Screening=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const VERSION='2026.10.2';
 const finite=x=>typeof x==='number'&&Number.isFinite(x);
 const STATES={CANDIDATE:'候選待公告',PENDING:'資料待補',REJECTED:'條件未通過'};
 const price=(x,unit)=>finite(x)?(x>0?'+':'')+x.toFixed(unit||2):'待補';
 function evaluate(r){
   if(!r||r.top!=='gain')return null;
   const checks=[
     {key:'big',label:'400張以上大戶集中',state:!finite(r.delta)?'pending':r.delta>=1?'pass':'fail',text:price(r.delta)+'pp（門檻 ≥1pp）'},
     {key:'kilo',label:'千張級距同步增加',state:!finite(r.kilo)?'pending':r.kilo>0?'pass':'fail',text:price(r.kilo)+'pp（需 >0pp）'},
     {key:'retail',label:'散戶持股下降',state:!finite(r.retail)?'pending':r.retail<0?'pass':'fail',text:price(r.retail)+'pp（需 <0pp；散戶=集保第1～5級）'},
   ];
   let capital;
   if(!finite(r.inventoryChangePct))capital={key:'capital',label:'集保庫存總股數穩定',state:'pending',text:'前後週總股數不足，無法判斷股本調整'};
   else if(Math.abs(r.inventoryChangePct)>0.5)capital={key:'capital',label:'集保庫存總股數穩定',state:'fail',text:'集保庫存總股數變動 '+price(r.inventoryChangePct)+'%（超過0.5%，需優先檢查增減資、換股等）'};
   else capital={key:'capital',label:'集保庫存總股數穩定',state:'pass',text:'集保庫存總股數變動 '+price(r.inventoryChangePct)+'%（代理檢查，不是公司公告查核）'};
   checks.push(capital);
   const f=r.foreignWeekly,t=r.trustWeekly,complete=finite(r.instCoverage)&&finite(r.instExpected)&&r.instCoverage===r.instExpected&&r.instExpected>0;
   let inst;
   if(!finite(f)||!finite(t)||!complete)inst={key:'institution',label:'外資＋投信同週淨買超',state:'pending',text:'法人資料或完整交易日覆蓋不足（'+String(r.instCoverage??'待補')+'/'+String(r.instExpected??'待補')+'天）'+(Array.isArray(r.instMissingDates)&&r.instMissingDates.length?'，缺少 '+r.instMissingDates.map(d=>d+(r.instMissingReasons?.[d]==='report_not_listed'?'（官方日報未列此股，不視為零）':r.instMissingReasons?.[d]==='report_unavailable'?'（市場日報未取得）':'')).join('、'):'')};
   else inst={key:'institution',label:'外資＋投信同週淨買超',state:f+t>0?'pass':'fail',text:'外資 '+price(f,1)+'張；投信 '+price(t,1)+'張；合計 '+price(f+t,1)+'張（需 >0）'};
   checks.push(inst);
   const failed=checks.some(x=>x.state==='fail');
   const pending=checks.some(x=>x.state==='pending');
   const status=failed?STATES.REJECTED:pending?STATES.PENDING:STATES.CANDIDATE;
   return {status,checks,version:VERSION,
     // no public dataset can conclusively identify accounting cosmetics/manipulation
     announcementReviewed:false,
     caution:'僅為結構與法人交易條件通過；股本／重大訊息／關係人交易尚需人工公告核查，無法證明不是公司或關係人調整。',
     dataComplete:!pending,
     supplementary:{holdersChange:finite(r.owners)?r.owners:null,foreignWeekly:f,trustWeekly:t}};
 }
 function summarize(records){
   const arr=(records||[]).map(r=>({record:r,result:evaluate(r)})).filter(x=>x.result);
   return {all:arr,candidates:arr.filter(x=>x.result.status===STATES.CANDIDATE),pending:arr.filter(x=>x.result.status===STATES.PENDING),rejected:arr.filter(x=>x.result.status===STATES.REJECTED)};
 }
 return Object.freeze({VERSION,STATES,evaluate,summarize});
});
