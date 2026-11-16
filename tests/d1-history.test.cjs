const test = require('node:test');
const assert = require('node:assert/strict');
const D1 = require('../rules/d1-screening.js');
const History = require('../rules/d1-history.js');

const regular = (code, name) => ({
  code, name, delta: 1.25, returnPct: -1.2, marginChange: -12, marginBalance: 160
});
const strong = (code, name) => ({
  code, name, delta: 2.6, returnPct: -1.1, marginChange: -20, marginBalance: 80
});
const invalid = {code: '7777', name: '缺值', delta: 2, returnPct: null, marginChange: -1};
const ordinary = {code: '6666', name: '未入選', delta: 0.2, returnPct: 1, marginChange: 2};

const week = (date, records, type = 'auto') => ({
  type, date, compareDate: '2026-10-01', records
});

test('returns latest official week plus previous five, newest first', () => {
  const weeks = Array.from({length: 9}, (_, i) => week(
    '2026-10-' + String(i + 1).padStart(2, '0'),
    [regular('6101', '一般'), strong('6201', '強勢'), invalid]
  ));
  const res = History.summarize([...weeks].reverse(), D1);
  assert.equal(res.length, 6);
  assert.deepEqual(res.map(x => x.date), weeks.slice(3).map(x => x.date).reverse());
  assert.equal(res[0].d1.length, 1);
  assert.equal(res[0].d1plus.length, 1);
  assert.equal(res[0].covered, 2);
  assert.equal(res[0].total, 3);
});

test('never treats image, manually imported, or missing-data week as qualified', () => {
  const values = [
    week('2026-11-06', [regular('6101','歷史D1')]),
    week('2026-11-13', [strong('6201','歷史D1+'), invalid, ordinary]),
    week('2026-11-14', [strong('7771','範例')], 'built-in'),
    week('2026-11-15', [strong('7772','匯入')], 'import'),
    week('2026-11-20', [invalid])
  ];
  const res = History.summarize(values, D1);
  assert.deepEqual(res.map(x => x.date), ['2026-11-20','2026-11-13','2026-11-06']);
  assert.equal(res[0].d1.length + res[0].d1plus.length, 0);
  assert.equal(res[0].covered, 0);
  assert.equal(res[1].d1plus[0].code,'6201');
  assert.equal(res[2].d1[0].code,'6101');
});

test('with fewer than six official reports, returns only real reports', () => {
  assert.deepEqual(History.summarize([], D1), []);
  assert.deepEqual(History.summarize([week('2026-11-13', [regular('1010', '有效')])], D1)
    .map(x => x.date), ['2026-11-13']);
  assert.equal(History.summarize([week('2026-11-13',[regular('1010','有效')])], null).length,0);
});

test('same date is not counted twice; exact D1 rules remain authoritative', () => {
  const dates = [week('2026-11-13', [regular('1010','被取代')]),
    week('2026-11-13', [strong('1030','新快照')])];
  const res=History.summarize(dates,D1);
  assert.equal(res.length,1);
  assert.equal(res[0].d1.length,0);
  assert.deepEqual(res[0].d1plus.map(x=>x.code),['1030']);
});
