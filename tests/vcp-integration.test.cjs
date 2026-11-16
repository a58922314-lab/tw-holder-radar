const test = require("node:test");
const assert = require("node:assert/strict");
const D1 = require("../rules/d1-screening.js");
const VCP = require("../rules/vcp-integration.js");

const d1 = {code:"6257",name:"矽格",market:"上櫃",delta:1.4,
  returnPct:-1, marginChange:-5, marginBalance:95, retail:-0.5};
const d1plus = {code:"4566",name:"時碩工業",market:"上市",delta:2.4,
  returnPct:-2, marginChange:-10, marginBalance:90, retail:-1};
const other = {code:"2330",name:"台積電",market:"上市",delta:0.4,
  returnPct:1, marginChange:2, marginBalance:200, retail:0};
const snapshot = {date:"2026-11-13",type:"auto",records:[d1,d1plus,other]};

test("all D1/D1+ stocks are transferred even if VCP failed or data are missing", ()=>{
  const report={candidates:[],assessments:{
    "6257":{status:"未符合",bars:170,date:"2026-11-13",
      close:105,pivot:109,distancePct:3.81,dryRatio:1.12,
      depthsPct:[25,15,13],reasons:["距樞紐不在突破前1%～3%","未縮量"]}}};
  const rows=VCP.merge(report,snapshot,"d1",D1);
  assert.equal(rows.length,2);
  assert.deepEqual(new Set(rows.map(x=>x.code)),new Set(["6257","4566"]));
  assert.equal(rows.find(x=>x.code==="6257").status,"未符合");
  assert.equal(rows.find(x=>x.code==="6257").d1Tier,"D1");
  assert.equal(rows.find(x=>x.code==="4566").status,"資料不足");
  assert.equal(rows.find(x=>x.code==="4566").d1Tier,"D1+");
  assert.equal(rows.find(x=>x.code==="4566").pivot,undefined);
});

test("D1+ mode excludes ordinary D1, retains unqualified technical row", ()=>{
  const rows=VCP.merge({candidates:[],assessments:{}} ,snapshot,"d1plus",D1);
  assert.deepEqual(rows.map(x=>x.code),["4566"]);
});

test("VCP-only list still works independently and labels any D1 status", ()=>{
  const report={candidates:[
    {code:"4566",name:"時碩工業",status:"縮量近樞紐"},
    {code:"2330",name:"台積電",status:"嚴格三段收縮"}
  ]};
  const rows=VCP.merge(report,snapshot,"vcp",D1);
  assert.equal(rows.length,2);
  assert.equal(rows[0].d1Tier,"D1+");
  assert.equal(rows[1].d1Tier,null);
});

test("D1 mode rejects picture samples and missing screening module", ()=>{
  assert.throws(()=>VCP.merge({candidates:[]},{type:"built-in",records:[d1]},"d1",D1),/官方/);
  assert.throws(()=>VCP.merge({candidates:[]},snapshot,"d1",null),/規則/);
});

test("D1 mode keeps failures unless user explicitly filters their technical status", ()=>{
  const rows=VCP.merge({candidates:[],assessments:{
    "6257":{status:"未符合",distancePct:8,strict:false},
    "4566":{status:"嚴格三段收縮",distancePct:2,strict:true}
  }},snapshot,"d1",D1);
  assert.equal(VCP.filter(rows).length,2);
  assert.deepEqual(VCP.filter(rows,{status:"strict"}).map(x=>x.code),["4566"]);
  assert.deepEqual(VCP.filter(rows,{status:"failed"}).map(x=>x.code),["6257"]);
  assert.deepEqual(VCP.filter(rows,{distance:"far"}),[]);
});
