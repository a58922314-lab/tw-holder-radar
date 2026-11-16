/* VCP × D1 holder integration. Official latest D1 rules remain in d1-screening.js.
 * Never remove a qualified D1 stock just because its technical pattern fails.
 */
(function(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.VCPIntegration = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function() {
  "use strict";
  const isNum = x => typeof x === "number" && Number.isFinite(x);
  const D1_TIERS = new Set(["D1", "D1+"]);
  const RANK = {"嚴格三段收縮":0, "縮量近樞紐":1, "未符合":2, "資料不足":3, "行情落後":4};
  const mark = (value, fallback) => value == null ? fallback : value;

  function merge(report, snapshot, mode, d1Engine) {
    const validMode = ["vcp", "d1", "d1plus"].includes(mode) ? mode : "vcp";
    const records = snapshot && snapshot.type === "auto" && Array.isArray(snapshot.records)
      ? snapshot.records : [];
    const holders = new Map(records.map(r => [String(r.code), r]));
    const assessments = report && report.assessments && typeof report.assessments === "object"
      && !Array.isArray(report.assessments) ? report.assessments : {};
    const qualify = row => d1Engine && typeof d1Engine.qualify === "function"
      ? d1Engine.qualify(row) : null;
    if (validMode === "vcp") {
      return (Array.isArray(report?.candidates) ? report.candidates : []).map(row => ({
        ...row, d1Tier: qualify(holders.get(String(row.code)))?.tier ?? null
      }));
    }
    if (!d1Engine || typeof d1Engine.qualify !== "function") {
      throw new Error("D1 規則模組尚未載入，無法驗證 D1／D1+ 資格");
    }
    if (!records.length) {
      throw new Error("缺少最新官方週籌碼資料，不能使用範例資料冒充 D1");
    }
    const all = [];
    for (const r of records) {
      const info = qualify(r);
      if (!info || !D1_TIERS.has(info.tier)) continue;
      if (validMode === "d1plus" && info.tier !== "D1+") continue;
      const assessment = assessments[String(r.code)] ?? {
        status:"資料不足", reasons:["尚無此股的 VCP 技術評估資料"],
        strict:false, bars:0
      };
      // Preserve every D1 qualification, even if price data or the pattern fails.
      all.push({
        ...assessment, code:String(r.code), name:String(r.name),
        market:r.market, d1Tier:info.tier, holderDate:snapshot.date
      });
    }
    return all.sort((a,b) =>
      (RANK[a.status] ?? 9) - (RANK[b.status] ?? 9) ||
      (isNum(a.distancePct) && isNum(b.distancePct) ? Math.abs(a.distancePct-2)-Math.abs(b.distancePct-2) : 0) ||
      a.code.localeCompare(b.code)
    );
  }

  function filter(rows, params={}) {
    const {q="",market="all",distance="all",status="all",holder="all"}=params;
    const needle=String(q).trim().toLowerCase();
    const records=params.latest ?? {};
    return rows.filter(r=>{
      const c=records[String(r.code)] ?? {};
      const hasFlow=isNum(c.instExpected) && c.instExpected>0 &&
        c.instCoverage===c.instExpected &&
        isNum(c.foreignWeekly) && isNum(c.trustWeekly);
      const flow=hasFlow?c.foreignWeekly+c.trustWeekly:null;
      const common=isNum(c.delta) && c.delta>0 && isNum(c.retail) && c.retail<0;
      const capitalSafe=isNum(c.inventoryChangePct) && Math.abs(c.inventoryChangePct)<=0.5;
      if(market!=="all" && r.market!==market)return false;
      if(needle&&!String(r.code).includes(needle)&&!String(r.name).toLowerCase().includes(needle))return false;
      if(distance==="near"&&!(isNum(r.distancePct)&&r.distancePct>=1&&r.distancePct<=2))return false;
      if(distance==="far"&&!(isNum(r.distancePct)&&r.distancePct>2&&r.distancePct<=3))return false;
      if(status==="strict"&&r.status!=="嚴格三段收縮")return false;
      if(status==="watch"&&r.status!=="縮量近樞紐")return false;
      if(status==="failed"&&r.status!=="未符合")return false;
      if(status==="missing"&&!["資料不足","行情落後"].includes(r.status))return false;
      if(holder==="big"&&!(isNum(c.delta)&&c.delta>0))return false;
      if(holder==="both"&&!common)return false;
      if(holder==="strong"&&!(common&&capitalSafe&&isNum(flow)&&flow>0))return false;
      return true;
    });
  }
  return Object.freeze({merge,filter});
});
