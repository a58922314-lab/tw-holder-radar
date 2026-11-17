/* Historical D1/D1+ weekly selections intersected with current momentum indicators.
 * Weekly stock memberships are recalculated with D1History, never from current D1
 * tiers or from example/user-uploaded snapshots. This is NOT a historical backtest.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MomentumWeek = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function weeks(snapshots, d1Engine, historyEngine) {
    if (!historyEngine || typeof historyEngine.summarize !== "function") return [];
    // A full-market official weekly snapshot has over 1000 records.
    // Do not let incomplete snapshots or built-in examples appear as weeks.
    const official = Array.isArray(snapshots)
      ? snapshots.filter(s => s && s.type === "auto" &&
          Array.isArray(s.records) && s.records.length > 1000)
      : [];
    // The backend retains at most 12 weekly snapshots today. Show all that
    // actually exist (up to the D1History helper's supported 53).
    return historyEngine.summarize(official, d1Engine, 52);
  }

  function selected(available, requestedDate) {
    if (!Array.isArray(available) || !available.length) return null;
    return available.find(w => w.date === requestedDate) || available[0];
  }

  function membership(week) {
    const result = new Map();
    if (!week) return result;
    for (const record of week.d1 || []) {
      result.set(String(record.code), {...record, tier:"D1"});
    }
    for (const record of week.d1plus || []) {
      result.set(String(record.code), {...record, tier:"D1+"});
    }
    return result;
  }

  function merge(momentumAssessments, vcpAssessments, week, source="d1") {
    const assessments = momentumAssessments && typeof momentumAssessments === "object"
      && !Array.isArray(momentumAssessments) ? momentumAssessments : {};
    const vcps = vcpAssessments && typeof vcpAssessments === "object"
      && !Array.isArray(vcpAssessments) ? vcpAssessments : {};
    const holders = membership(week);
    const codes = source === "all" ? Object.keys(assessments) : [...holders.keys()];
    const out = [];
    for (const code of codes) {
      const holder = holders.get(code) || null;
      if (source === "d1plus" && holder?.tier !== "D1+") continue;
      const technical = assessments[code] || {
        status:"資料不足", bars:0, reason:"目前無此股的日K技術評估"
      };
      out.push({
        ...technical, code,
        name: technical.name || holder?.name || code,
        holder,
        vcp: vcps[code]?.status || "資料不足"
      });
    }
    return out;
  }
  return Object.freeze({weeks, selected, membership, merge});
});
