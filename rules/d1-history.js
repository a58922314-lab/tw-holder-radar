/* Official D1 / D1+ selection history. The site's original D1Screening.qualify
 * is the sole source of tier rules; never infer missing weeks or use sample CSV.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.D1History = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const valid = x => typeof x === 'number' && Number.isFinite(x);
  const isDay = s => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s);

  function summarize(snapshots, engine, previousWeeks = 5) {
    if (!engine || typeof engine.qualify !== 'function') return [];
    if (!Array.isArray(snapshots)) return [];
    const dates = new Map();
    for (const s of snapshots) {
      if (s && s.type === 'auto' && isDay(s.date) && Array.isArray(s.records) && s.records.length) {
        // Later official duplicate of this exact TDCC week replaces earlier.
        dates.set(s.date, s);
      }
    }
    const count = Math.max(1, Math.min(53, Math.trunc(Number(previousWeeks) || 0) + 1));
    return [...dates.values()].sort((a, b) => b.date.localeCompare(a.date)).slice(0, count).map(s => {
      const qualified = {D1: [], 'D1+': []};
      let coverage = 0;
      for (const record of s.records) {
        if (valid(record.delta) && valid(record.returnPct) && valid(record.marginChange)) coverage++;
        const info = engine.qualify(record);
        if (info && (info.tier === 'D1' || info.tier === 'D1+')) {
          qualified[info.tier].push({
            code: String(record.code), name: String(record.name),
            delta: record.delta, returnPct: record.returnPct,
            marginChange: record.marginChange,
            capitalChangeReview: !!info.capitalChangeReview
          });
        }
      }
      for (const tier of ['D1', 'D1+']) {
        qualified[tier].sort((a, b) => b.delta - a.delta || a.code.localeCompare(b.code));
      }
      return {
        date: s.date,
        compareDate: isDay(s.compareDate) ? s.compareDate : null,
        covered: coverage,
        total: s.records.length,
        d1: qualified.D1,
        d1plus: qualified['D1+']
      };
    });
  }

  return Object.freeze({summarize});
});
