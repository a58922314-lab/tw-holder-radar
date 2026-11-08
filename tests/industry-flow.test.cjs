const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'../index.html'),'utf8');
const source=html.split('// INDUSTRY_MODEL_START')[1].split('// INDUSTRY_MODEL_END')[0].split('\n').slice(1).join('\n');
const context=vm.createContext({});vm.runInContext(source,context);
const summary=(rows,market='全部',investor='all',extra={})=>context.industrySummary({type:'auto',compareDate:'2026-10-30',date:'2026-11-06',records:rows,...extra},market,investor);
const row=(code,industry,extra={})=>({code,industry,market:'上市',foreignWeekly:1,trustWeekly:2,dealerWeekly:-1,weeklyClose:100,weeklyCloseDate:'2026-11-06',instExpected:5,instCoverage:5,...extra});

test('weights shares by each stock price, nets within industries, uses whole universe',()=>{
  const m=summary([row('2330','半導體',{weeklyClose:1000}),row('2337','半導體',{foreignWeekly:-4,trustWeekly:0,dealerWeekly:0}),row('1234','食品',{foreignWeekly:-5,trustWeekly:0,dealerWeekly:0,market:'上櫃'})]);
  assert.equal(m.included,3);assert.equal(m.sectors[0].net,1600000);
  assert.equal(m.inflow,1600000);assert.equal(m.outflow,500000);assert.equal(m.net,1100000);
  assert.equal(m.sectors[0].share,1);assert.equal(m.sectors[1].share,1);
  assert.equal(m.sectors[0].buyers,1);assert.equal(m.sectors[0].sellers,1);
});
test('market and investor selectors change the population and amount',()=>{
  const rows=[row('2330','半導體'),row('1234','食品',{market:'上櫃'})];
  assert.equal(summary(rows,'上櫃','trust').net,200000);
  assert.equal(summary(rows,'上市','dealer').net,-100000);
  assert.equal(summary(rows,'全部','foreign').included,2);
});
test('missing classification, incomplete sessions and wrong-date prices never become zeros',()=>{
  const m=summary([row('1',null),row('2','食品',{instCoverage:4}),row('3','食品',{weeklyCloseDate:'2026-11-09'}),row('4','食品',{foreignWeekly:null}),row('5','食品',{weeklyClose:NaN})]);
  assert.equal(m.included,0);assert.equal(m.net,null);
  assert.equal(m.unknown,1);assert.equal(m.missingFlow,2);assert.equal(m.missingPrice,2);
  assert.ok(m.sectors.every(g=>g.net===null));
});
test('zero flow is valid, missing input is not and partial sectors report their coverage',()=>{
  const m=summary([row('1','食品',{foreignWeekly:0,trustWeekly:0,dealerWeekly:0}),row('2','食品',{trustWeekly:null})]);
  assert.equal(m.net,0);assert.equal(m.included,1);assert.equal(m.sectors[0].total,2);assert.equal(m.sectors[0].covered,1);
  assert.equal(m.sectors[0].share,0);assert.equal(m.sectors[0].stocks[1].amount,null);
});
test('built-in/imported or first-week samples cannot masquerade as official flows',()=>{
  for(const extra of [{type:'built-in'},{type:'import'},{compareDate:null}])assert.equal(summary([row('1','食品')],'全部','all',extra).included,0);
});
test('treemap areas equal directional net shares and remain inside bounds',()=>{
  const groups=[{name:'A',net:60},{name:'B',net:30},{name:'C',net:10}];
  const tiles=context.industryTiles(groups);
  for(const t of tiles){assert.ok(Math.abs(t.w*t.h/(1000*400)-t.net/100)<1e-9);assert.ok(t.x>=0&&t.y>=0&&t.x+t.w<=1000.001&&t.y+t.h<=400.001);}
  assert.equal(context.industryTiles([]).length,0);
});

test('published snapshots preserve industry amount reconciliation across investor filters',()=>{
  const payload=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../data/auto_snapshots.json'),'utf8'));
  for(const s of payload.snapshots){
    const results=['all','foreign','trust','dealer'].map(i=>context.industrySummary(s,'全部',i));
    if(!results[0].included)continue;
    const expected=results.slice(1).reduce((n,r)=>n+r.net,0);
    assert.ok(Math.abs(results[0].net-expected)<0.01);
    assert.equal(results[0].included,results[1].included);
    for(const m of results)assert.equal(m.total,m.included+m.unknown+m.missingFlow+m.missingPrice);
  }
});
