"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const rules=require("../rules/d1-screening.js");
const make=(delta,ret,marginChange=null,marginBalance=null)=>({delta,returnPct:ret,marginChange,marginBalance});

test("D1+ exactly matches existing D1 Radar: >=2pp and financing drop >=5%",()=>{
 const x=rules.qualify(make(2,0,-5,95));
 assert.equal(x.tier,"D1+");
 assert.equal(x.marginDropPct,5);
 assert.equal(x.rulesVersion,"2026.09.1");
});
test("D1 conditions are strict on decreasing margin",()=>{
 assert.equal(rules.qualify(make(1,0,-1,99)).tier,"D1");
 assert.notEqual(rules.qualify(make(1,0,0,100))?.tier,"D1");
 assert.equal(rules.qualify(make(1,0,-1,99.1)).tier,"D1");
});
test("C2+ with no margin increase, and C1 when financing missing",()=>{
 assert.equal(rules.qualify(make(1,3,0,100)).tier,"C2+");
 assert.equal(rules.qualify(make(0.5,5)).tier,"C1");
 assert.equal(rules.qualify(make(1,0))?.tier,"C1");
});
test("boundary values and missing values cannot generate invented data",()=>{
 assert.equal(rules.qualify(make(0.49,0)),null);
 assert.equal(rules.qualify(make(0.5,5.01)),null);
 assert.equal(rules.qualify(make(1,null,-5,95)),null);
 assert.equal(rules.qualify(make(null,-5,-5,95)),null);
 assert.equal(rules.qualify(make(2,0,-5,null)).tier,"D1"); // unknown denominator
});
test("highest tier only: D1 includes D1+ in filter, but counts do not double-count",()=>{
 const fixtures=[make(2,0,-5,95),make(1,0,-1,99),make(1,3,0,100),make(0.5,5)];
 assert.deepEqual(fixtures.map(x=>rules.qualify(x).tier),["D1+","D1","C2+","C1"]);
 assert.equal(rules.filterRecords(fixtures,"D1").length,2);
 assert.equal(rules.filterRecords(fixtures,"D1+").length,1);
 assert.equal(rules.filterRecords(fixtures,"全部").length,4);
});
test("original rules are not silently excluding above 10pp moves, but flag review",()=>{
 const x=rules.qualify(make(11,0,-5,95));
 assert.equal(x.tier,"D1+");
 assert.equal(x.capitalChangeReview,true);
});
test("static integration and independently hosted script present",()=>{
 const html=fs.readFileSync(path.join(__dirname,"../index.html"),"utf8");
 assert.match(html,/rules\/d1-screening\.js/);
 assert.match(html,/function renderSignals\(\)/);
 assert.match(html,/D1\+/);
 assert.doesNotMatch(html,/https:\/\/.*lovable\.app/);
});
