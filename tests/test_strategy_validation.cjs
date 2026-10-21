"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const js = fs.readFileSync(path.join(root, "strategy-validation.js"), "utf8");
const html = fs.readFileSync(path.join(root, "strategy-validation.html"), "utf8");
const home = fs.readFileSync(path.join(root, "index.html"), "utf8");
assert.ok(html.includes('src="./strategy-validation.js"'));
assert.ok(home.includes('href="./strategy-validation.html"'));
assert.ok(!js.includes("innerHTML"), "avoid parsing imported report content as HTML");
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ""; this.hidden = false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  addEventListener(event, handler) { this[event] = handler; }
}
const elements = new Map();
const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  },
  createElement(tag) { return new Element(tag); }
};
const context = vm.createContext({document, console, JSON, Number, Object, Array, String});
vm.runInContext(js, context, {filename:"strategy-validation.js"});
const example = {
  verdict: {
    level:"gambling", headline:"樣本負期望，不建議繼續交易",
    should_discourage:true, metrics: {
      total_trades:38, win_rate:0.4, expectancy:-1200, total_pnl:-45600,
      pnl_currency:"TWD", profit_factor:0.7, payoff_ratio:1,
      sequence_metrics_reliable:false, drawdown_pct_reliable:false,
      currency_reliable:true
    },
    reasons:["非實際績效測試<script>alert(1)</script>"], red_flags:[], advice:[]
  },
  stage:{title:"停手檢查"},
  out_of_sample:{available:false,unavailable_reason:"不具備完整的出場時間"},
  tag_verdicts:[{tag:"D1 濾網",n_trades:38,win_rate:0.4,expectancy:-1200,total_pnl:-45600}],
  integrity:{rejected_rows:0}
};
vm.runInContext("render(" + JSON.stringify(example) + ", 'test.json')",context);
assert.equal(elements.get("report").hidden,false);
assert.equal(elements.get("kpis").children.length,8);
assert.equal(elements.get("tags").children.length,1);
assert.ok(elements.get("headline").textContent.includes("負期望"));
assert.equal(elements.get("kpis").children[7].children[1].textContent,"無法計算");
assert.ok(elements.get("reasons").children.some(x=>x.textContent.includes("<script>")));
assert.throws(()=>vm.runInContext("render({}, 'invalid.json')",context),/not|missing|缺少|辨識/);
console.log("Strategy validation UI contract tests passed");
