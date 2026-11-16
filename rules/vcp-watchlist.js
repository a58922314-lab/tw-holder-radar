/* Join the full official D1 universe to VCP diagnostics, never to candidates. */
(function (root, factory) {
  const api = factory(typeof module !== 'undefined' && module.exports
    ? require('./d1-screening.js') : root.D1Screening);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.VCPWatchlist = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (d1) {
  'use strict';
  function latestOfficial(payload) {
    const snapshot = (Array.isArray(payload?.snapshots) ? payload.snapshots : [])
      .filter(s => s.type === 'auto' && /^\d{4}-\d{2}-\d{2}$/.test(s.date))
      .sort((a, b) => a.date.localeCompare(b.date)).at(-1);
    if (!snapshot || !Array.isArray(snapshot.records)) throw Error('最新官方週集保快照缺失或格式不正確');
    return snapshot;
  }
  function build(snapshot, report, error = '') {
    if (!d1) throw Error('D1 資格規則無法載入');
    if (snapshot?.type !== 'auto' || !Array.isArray(snapshot.records)) return [];
    const diagnostics = new Map((report?.evaluations || []).map(r => [String(r.code), r]));
    return d1.filterRecords(snapshot.records, 'D1').map(record => {
      const signal = d1.qualify(record);
      const diagnostic = diagnostics.get(String(record.code));
      const row = {date: null, close: null, pivot: null, distancePct: null, depthsPct: [],
        dryRatio: null, volumeLots: null, bars: 0, checks: {}, reasons: [], dataIssues: [],
        strict: false, candidate: false, status: 'insufficient', grade: '資料不足', ...diagnostic,
        code: record.code, name: record.name, market: record.market,
        d1Tier: signal.tier, holderDate: snapshot.date, d1Signal: signal};
      row.dataIssues = [...(row.dataIssues || [])];
      if (!diagnostic) row.dataIssues.push(error || '尚無此股的 VCP 逐股檢查資料，等待排程更新');
      else {
        const expected = report?.marketAsOf?.[row.market];
        if (!expected || row.date !== expected) row.dataIssues.push('個股行情未更新至市場最新日期：' + (expected || '待補'));
      }
      if (row.dataIssues.length) Object.assign(row, {status: 'insufficient', candidate: false, grade: '資料不足'});
      return row;
    });
  }
  return Object.freeze({latestOfficial, build});
});
