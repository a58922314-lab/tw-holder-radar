"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const Kelly=require("../rules/kelly-risk.js");
const base={capital:1000000,price:50,winRate:35,takeProfitPct:10,stopLossPct:5,
  costPct:0,fraction:0.5,riskPct:0.5,maxPositionPct:20,maxPortfolioPct:60,
  usedCapital:0,lotSize:1000,sampleSize:0};
const calc=p=>Kelly.calculate({...base,...p});
test("35% win, 10% profit, 5% loss => 50% full / 25% half Kelly",()=>{
  const x=calc({});
  assert.equal(x.valid,true);
  assert.ok(Math.abs(x.fullKelly-0.5)<1e-10);
  assert.ok(Math.abs(x.chosenKelly-0.25)<1e-10);
  assert.equal(x.capitalBudget,100000);
  assert.equal(x.shares,2000);
  assert.equal(x.maxLoss,5000);
  assert.equal(x.needsEvidence,true);
});
test("zero or negative after-cost edge never creates exposure",()=>{
  const x=calc({winRate:30});
  assert.equal(x.positiveEdge,false);
  assert.equal(x.shares,0);
  assert.equal(x.capitalBudget,0);
  const y=calc({winRate:35,costPct:0.6});
  assert.equal(y.positiveEdge,false);
  assert.equal(y.shares,0);
});
test("portfolio and cash caps are enforced",()=>{
  const x=calc({riskPct:20,maxPositionPct:100,maxPortfolioPct:60,usedCapital:550000});
  assert.equal(x.capitalBudget,50000);
  assert.equal(x.shares,1000);
  const y=calc({riskPct:20,maxPositionPct:100,maxPortfolioPct:100,usedCapital:980000});
  assert.equal(y.capitalBudget,20000);
  assert.equal(y.shares,0);
});
test("risk uses actual loss including round-trip cost",()=>{
  const x=calc({winRate:60,costPct:0.6});
  assert.equal(x.valid,true);
  assert.ok(Math.abs(x.loss-0.056)<1e-12);
  assert.ok(x.actualRiskPct<=0.5+1e-10);
  assert.ok(x.maxLoss<=5000);
});
test("odd-lot sizing and position prices are separated from sizing",()=>{
  const x=calc({price:150,lotSize:1});
  assert.equal(x.valid,true);
  assert.equal(x.shares,Math.floor(x.capitalBudget/150));
  assert.ok(Math.abs(x.stopPrice-142.5)<1e-10);
  assert.equal(x.takeProfitPrice,165);
});
test("bad inputs and impossible cost assumptions are rejected",()=>{
  assert.equal(calc({price:0}).valid,false);
  assert.equal(calc({usedCapital:1200000}).valid,false);
  assert.equal(calc({winRate:101}).valid,false);
  assert.equal(calc({sampleSize:-1}).valid,false);
  assert.equal(calc({costPct:12}).valid,false);
});
test("no history and signal names do not change expected results",()=>{
  const a=calc({sampleSize:0,signal:"D1"});
  const b=calc({sampleSize:400,signal:"A1"});
  assert.equal(a.fullKelly,b.fullKelly);
  assert.equal(b.verifiedHistory,false);
  assert.equal(b.needsEvidence,false);
});

test("website links planner and both workflows package it",()=>{
 const fs=require("node:fs");
 const path=require("node:path");
 const root=path.resolve(__dirname,"..");
 const index=fs.readFileSync(path.join(root,"index.html"),"utf8");
 assert.match(index,/href="\.\/kelly-risk\.html"/);
 assert.match(index,/使用凱利資金控管試算/);
 for(const file of ["deploy.yml","refresh.yml"]){
   const workflow=fs.readFileSync(path.join(root,".github/workflows",file),"utf8");
   assert.match(workflow,/cp kelly-risk\.html _site\/kelly-risk\.html/);
   assert.match(workflow,/node --test tests\/kelly-risk\.test\.cjs/);
 }
});
