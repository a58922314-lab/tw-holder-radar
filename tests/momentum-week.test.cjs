"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const D1 = require("../rules/d1-screening.js");
const History = require("../rules/d1-history.js");
const MomentumWeek = require("../rules/momentum-week.js");

const record = (code, name, delta, marginChange=-12, marginBalance=160) =>
  ({code,name,delta,returnPct:-1.5,marginChange,marginBalance});
const filler=Array.from({length:1001},(_,i)=>({
  code:String(3000+i),name:"一般",delta:0,returnPct:1,marginChange:10,marginBalance:100
}));
const fullWeek=(date,entries, type="auto")=>({
  type,date,compareDate:"2026-10-02",records:[...filler,...entries]
});

test("lists every actual stored official week, newest first; ignores imported and incomplete",()=>{
  const history = MomentumWeek.weeks([
    fullWeek("2026-10-09",[record("2233","宇隆",1.17)]),
    fullWeek("2026-11-13",[record("6796","晉弘",1.02)]),
    fullWeek("2026-11-06",[record("4566","時碩",2.5,-20,80)]),
    {type:"auto",date:"2026-11-20",records:[record("9999","不完整",2.5)]},
    fullWeek("2026-11-27",[record("9998","匯入",2.5)],"import")
  ],D1,History);
  assert.deepEqual(history.map(x=>x.date),["2026-11-13","2026-11-06","2026-10-09"]);
  assert.equal(history[0].d1[0].code,"6796");
  assert.equal(history[1].d1plus[0].code,"4566");
});

test("historical D1 membership is independent of the latest D1 week",()=>{
  const old=fullWeek("2026-10-09",[record("2233","宇隆",1.17)]);
  const latest=fullWeek("2026-11-13",[record("6796","晉弘",1.02)]);
  const weeks=MomentumWeek.weeks([old,latest],D1,History);
  const technical={
    "2233":{name:"宇隆",status:"未通過",date:"2026-11-17"},
    "6796":{name:"晉弘",status:"未通過",date:"2026-11-17"}
  };
  const oldRows=MomentumWeek.merge(technical,{},MomentumWeek.selected(weeks,old.date),"d1");
  assert.deepEqual(oldRows.map(x=>x.code),["2233"]);
  assert.equal(oldRows[0].holder.tier,"D1");
  assert.equal(oldRows[0].date,"2026-11-17");
  assert.deepEqual(MomentumWeek.merge(technical,{},weeks[0],"d1").map(x=>x.code),["6796"]);
  assert.deepEqual(MomentumWeek.merge(technical,{},weeks[0],"all").map(x=>x.code),["2233","6796"]);
});

test("missing current technology retains historical stock with honest missing status",()=>{
  const history=MomentumWeek.weeks([fullWeek("2026-10-09",[record("2345","舊股",1.5)])],D1,History);
  const r=MomentumWeek.merge({}, {}, history[0],"d1");
  assert.equal(r.length,1);
  assert.equal(r[0].code,"2345");
  assert.equal(r[0].name,"舊股");
  assert.equal(r[0].status,"資料不足");
});

test("selected week falls back to newest if missing, D1+ restricts selected week",()=>{
  const w=MomentumWeek.weeks([
    fullWeek("2026-11-13",[record("2233","D1",1.1),record("2345","D1+",2.8,-20,80)])
  ],D1,History);
  assert.equal(MomentumWeek.selected(w,"1999-01-01").date,"2026-11-13");
  assert.deepEqual(MomentumWeek.merge({}, {},w[0],"d1plus").map(x=>x.code),["2345"]);
  assert.equal(MomentumWeek.selected([],"2026-11-13"),null);
});

test("momentum page loads historical D1 helper and selector with date notice",()=>{
  const html=fs.readFileSync(require("node:path").join(__dirname,"..","momentum-radar.html"),"utf8");
  assert.match(html, /id="week"/);
  assert.match(html, /rules\/d1-history\.js/);
  assert.match(html, /rules\/momentum-week\.js/);
  assert.match(html, /不是該歷史週當天的訊號/);
  assert.match(html, /籌碼週_/);
});
