/* D1 Radar (Lovable) signal rules, version 2026.09.1
 * Reproduces the tier ordering of src/lib/d1-rules.ts in the user's
 * Lovable D1 Radar app. No live prices are fabricated. These snapshots are
 * dated TDCC/TWSE/TPEx data, NOT the Lovable app's Supabase signal database.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.LovableRules = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const RULES_VERSION = '2026.09.1';
  const SETTINGS = Object.freeze({
    d1WhaleMinPp: 1.0,
    d1WeeklyReturnMaxPct: 0,
    d1PlusWhaleMinPp: 2.0,
    d1PlusMarginDropMinPct: 5,
    c1WhaleMinPp: 0.5,
    c1WeeklyReturnMaxPct: 5,
    c2WhaleMinPp: 1.0,
    c2WeeklyReturnMaxPct: 3
  });
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  function qualify(row, params = SETTINGS) {
    // raw_snapshot fields: delta is percentage points; returnPct is %;
    // marginChange is lots/張. Calculating margin % requires both balances.
    if (!row || !finite(row.delta) || !finite(row.returnPct)) return null;
    const whale = row.delta, ret = row.returnPct;
    const marginChange = finite(row.marginChange) ? row.marginChange : null;
    const current = finite(row.marginBalance) ? row.marginBalance : null;
    const previous = current !== null && marginChange !== null ? current - marginChange : null;
    const dropPct = previous !== null && previous > 0 && marginChange !== null
      ? -100 * marginChange / previous : null;
    const d1 = whale >= params.d1WhaleMinPp && ret <= params.d1WeeklyReturnMaxPct
      && marginChange !== null && marginChange < 0;
    let tier = null;
    if (d1) tier = whale >= params.d1PlusWhaleMinPp && dropPct !== null
      && dropPct >= params.d1PlusMarginDropMinPct ? 'D1+' : 'D1';
    else if (whale >= params.c2WhaleMinPp && ret <= params.c2WeeklyReturnMaxPct
      && marginChange !== null && marginChange <= 0) tier = 'C2+';
    else if (whale >= params.c1WhaleMinPp && ret <= params.c1WeeklyReturnMaxPct) tier = 'C1';
    if (!tier) return null;
    return {tier, whaleChangePp: whale, weeklyReturnPct: ret,
      marginChange, marginBalance: current, previousMarginBalance: previous,
      marginDropPct: dropPct, rulesVersion: RULES_VERSION,
      // very large jumps could indicate capital changes; flag, don't change Lovable's rules
      capitalChangeReview: Math.abs(whale) > 10};
  }
  function matches(signal, filter) {
    if (!signal) return false;
    if (filter === '全部') return true;
    if (filter === 'D1') return signal.tier === 'D1' || signal.tier === 'D1+';
    return filter === signal.tier;
  }
  function filterRecords(records, filter = '全部') {
    if (!Array.isArray(records)) return [];
    return records.filter(r => matches(qualify(r), filter));
  }
  return Object.freeze({RULES_VERSION, SETTINGS, qualify, matches, filterRecords});
});
