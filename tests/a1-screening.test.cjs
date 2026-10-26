"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs");
const A1=require("../rules/a1-screening.js");
const sample={code:"6278",top:"gain",delta:2.2,kilo:0.6,retail:-0.8,foreignWeekly:120,trustWeekly:10,inventoryChangePct:0,instCoverage:4,instExpected:4,owners:-100};
test("A1 requires member of actual current weekly gain TOP50",()=>{
 assert.equal(A1.evaluate({...sample,top:"loss"}),null);
});
test("A1 quant criteria passing never asserts absence of accounting manipulations",()=>{
 const r=A1.evaluate(sample);assert.equal(r.status,"候選待公告");assert.equal(r.announcementReviewed,false);assert.match(r.caution,/人工公告查核/);
});
test("A1 exact thresholds and weaker thousand increase rejected",()=>{
 assert.equal(A1.evaluate({...sample,delta:1,kilo:0.01,retail:-0.01}).status,"候選待公告");
 assert.equal(A1.evaluate({...sample,kilo:0}).status,"條件未通過");
 assert.equal(A1.evaluate({...sample,retail:0}).status,"條件未通過");
 assert.equal(A1.evaluate({...sample,delta:0.99}).status,"條件未通過");
});
test("Company inventory count abnormal flagged, never treated as confirmed",()=>{
 assert.equal(A1.evaluate({...sample,inventoryChangePct:0.51}).status,"條件未通過");
 assert.equal(A1.evaluate({...sample,inventoryChangePct:null}).status,"資料待補");
});
test("Institution weekly foreign plus trust must be net buying and full period covered",()=>{
 assert.equal(A1.evaluate({...sample,foreignWeekly:-40,trustWeekly:42}).status,"候選待公告");
 assert.equal(A1.evaluate({...sample,foreignWeekly:-40,trustWeekly:20}).status,"條件未通過");
 assert.equal(A1.evaluate({...sample,trustWeekly:null}).status,"資料待補");
 assert.equal(A1.evaluate({...sample,instCoverage:3}).status,"資料待補");
});
test("No fabricated signal from screenshot sample, and stable shares is a proxy",()=>{
 assert.equal(A1.evaluate({top:"gain",delta:5,kilo:1,retail:-0.5}).status,"資料待補");
});
test("A1 view and independent script integrated",()=>{
 const html=fs.readFileSync("index.html","utf8");
 assert.match(html,/function renderA1\(\)/);
 assert.match(html,/a1:renderA1/);
 assert.match(html,/\.\/rules\/a1-screening\.js/);
});
