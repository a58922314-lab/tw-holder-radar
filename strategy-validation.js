"use strict";
const byId = id => document.getElementById(id);
const safeObj = value => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const arr = value => Array.isArray(value) ? value : [];
const finite = value => typeof value === "number" && Number.isFinite(value);
const num = (value, digits = 2) => finite(value) ? value.toLocaleString("zh-TW", {maximumFractionDigits: digits, minimumFractionDigits: digits}) : "無法計算";
const pct = value => finite(value) ? num(value * 100, 1) + "%" : "無法計算";
const txt = value => typeof value === "string" && value.trim() ? value.trim() : "未提供";
function clear(id) { const node = byId(id); node.replaceChildren(); return node; }
function line(target, message) {
  const d = document.createElement("div");
  d.textContent = String(message);
  target.append(d);
}
function card(target, label, value) {
  const node = document.createElement("div");
  node.className = "card";
  const heading = document.createElement("div");
  heading.className = "label";
  heading.textContent = label;
  const body = document.createElement("div");
  body.className = "value";
  body.textContent = value;
  node.append(heading, body);
  target.append(node);
}
function cell(row, value) {
  const td = document.createElement("td");
  td.textContent = String(value);
  row.append(td);
}
function fail(message) {
  byId("report").hidden = true;
  byId("error").textContent = message;
  byId("error").hidden = false;
}
function render(report, filename) {
  const verdict = safeObj(report.verdict);
  const metrics = safeObj(verdict.metrics);
  if (!["gambling", "insufficient", "luck_suspected", "fragile_edge", "statistical_edge"].includes(verdict.level) || !finite(metrics.total_trades) || !finite(metrics.win_rate) || !finite(metrics.expectancy)) {
    throw new Error("檔案不是可辨識的 Anti-Gambling Trader analyze JSON（缺少 verdict.level 或 metrics）。");
  }
  const currency = txt(metrics.pnl_currency);
  const amount = value => num(value) + " " + currency;
  byId("filename").textContent = "本機報告：" + filename + " · 交易筆數：" + metrics.total_trades;
  byId("headline").textContent = txt(verdict.headline);
  byId("headline").className = verdict.should_discourage ? "bad" : "good";
  const stage = safeObj(report.stage);
  byId("stage").textContent = "系統階段：" + txt(stage.title) + (stage.reason ? " · " + stage.reason : "");
  const kpis = clear("kpis");
  card(kpis, "已平倉交易數", num(metrics.total_trades, 0));
  card(kpis, "勝率", pct(metrics.win_rate));
  card(kpis, "單筆樣本期望值", amount(metrics.expectancy));
  card(kpis, "累積已實現淨損益", amount(metrics.total_pnl));
  card(kpis, "獲利因子", num(metrics.profit_factor));
  card(kpis, "盈虧比", num(metrics.payoff_ratio));
  card(kpis, "最大回撤金額", metrics.sequence_metrics_reliable === false ? "無法計算" : amount(metrics.max_drawdown));
  card(kpis, "最大回撤比例", metrics.drawdown_pct_reliable === true ? pct(metrics.max_drawdown_pct) : "無法計算");
  const reasons = clear("reasons");
  line(reasons, "裁決等級：" + verdict.level);
  const significance = safeObj(verdict.significance);
  if (finite(significance.p_value_t)) line(reasons, "t 檢定 p 值：" + num(significance.p_value_t, 4));
  if (finite(significance.p_value_bootstrap)) line(reasons, "Bootstrap p 值：" + num(significance.p_value_bootstrap, 4));
  for (const reason of arr(verdict.reasons).slice(0, 15)) if (typeof reason === "string") line(reasons, reason);
  for (const flag of arr(verdict.red_flags).slice(0, 12)) {
    const data = safeObj(flag);
    line(reasons, "風險警訊：" + txt(data.message || data.description || data.name || data.code));
  }
  for (const advice of arr(verdict.advice).slice(0, 8)) if (typeof advice === "string") line(reasons, "建議：" + advice);
  const holdout = clear("holdout");
  const oos = safeObj(report.out_of_sample);
  if (oos.available !== true) {
    line(holdout, "樣本外尚未確認：" + txt(oos.unavailable_reason));
  } else {
    line(holdout, "歷史後段顯示優勢延續：" + (oos.edge_persisted === true ? "是（仍非未來保證）" : "否／未確認"));
    const before = safeObj(oos.in_sample), after = safeObj(oos.out_sample);
    line(holdout, "前段樣本：" + num(before.n_trades, 0) + " 筆，期望值 " + amount(before.expectancy));
    line(holdout, "後段樣本：" + num(after.n_trades, 0) + " 筆，期望值 " + amount(after.expectancy));
    if (typeof oos.headline === "string") line(holdout, oos.headline);
  }
  line(holdout, "此處是已完成交易依時間切分的單次 holdout；不是前瞻交易，也不是 D1 自動回測。");
  const tags = clear("tags");
  for (const item of arr(report.tag_verdicts).slice(0, 100)) {
    const t = safeObj(item);
    const tr = document.createElement("tr");
    cell(tr, txt(t.tag));
    cell(tr, num(t.n_trades, 0));
    cell(tr, pct(t.win_rate));
    cell(tr, amount(t.expectancy));
    cell(tr, amount(t.total_pnl));
    tags.append(tr);
  }
  if (!tags.children.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5; td.textContent = "沒有策略標籤資料。";
    tr.append(td); tags.append(tr);
  }
  const integrity = clear("integrity");
  const data = safeObj(report.integrity);
  if (Object.keys(data).length) {
    for (const [key, value] of Object.entries(data).slice(0, 25)) {
      if (["string", "number", "boolean"].includes(typeof value) || value === null) line(integrity, key + "：" + String(value));
    }
  }
  for (const field of ["sequence_note", "return_note", "currency_note", "drawdown_note", "timing_note"]) {
    if (metrics[field]) line(integrity, metrics[field]);
  }
  if (metrics.currency_reliable !== true) line(integrity, "幣別可靠性不足，請勿把金額合併當成可信績效。");
  line(integrity, "本頁只有本機報告展示，不連接券商、不存檔、不下單。");
  byId("error").hidden = true;
  byId("report").hidden = false;
}
byId("reportFile").addEventListener("change", async event => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 4 * 1024 * 1024) throw new Error("檔案超過 4 MB，請改用較小的分析報告。");
    const parsed = JSON.parse(await file.text());
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("報告格式不正確。");
    render(parsed, file.name);
  } catch (error) {
    fail(error instanceof Error ? error.message : "報告無法讀取。");
  }
});
