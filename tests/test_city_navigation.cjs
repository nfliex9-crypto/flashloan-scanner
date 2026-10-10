"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");

// Execute the real navigation logic without running its unrelated data polling.
// A text search for the buttons alone would not catch inaccessible sections.
const html = fs.readFileSync("city-research.html", "utf8");
const source = fs.readFileSync("city.js", "utf8");
const start = source.indexOf("const VIEW_IDS=");
const end = source.indexOf("function openDrawer(", start);
assert.ok(start >= 0 && end > start, "navigation block exists");
const section = source.slice(start, end);
const sectionIds = ["cityView", "payrollView", "evolutionView", "labView", "backtestView", "intelView"];
const tabs = ["city", "payroll", "evolution", "lab", "backtest", "intel"];
const nodes = new Map(sectionIds.map(id => [id, {
  classList: {
    active: false,
    add(k) { if (k === "active") this.active = true; },
    remove(k) { if (k === "active") this.active = false; }
  }
}]));
const buttons = tabs.map(view => ({
  dataset: { view },
  classList: {
    active: false,
    toggle(k, value) { if (k === "active") this.active = Boolean(value); }
  }
}));
const windowMock = {
  location: { hash: "#backtestView" },
  history: {
    replaceState(_data, _unused, hash) { windowMock.location.hash = hash; }
  },
  scrollTo() {}
};
const context = { window: windowMock, document: {
  getElementById(id) { return nodes.get(id); },
  querySelectorAll() { return buttons; }
}};
const api = vm.runInNewContext(
  "const $ = id => document.getElementById(id);\n" + section +
  "\n({setView,viewFromHash,VIEW_IDS})", context);

test("every tab has its real visible panel and selects it", () => {
  for (const view of tabs) {
    assert.match(html, new RegExp('data-view="' + view + '"'));
    assert.match(html, new RegExp('id="' + api.VIEW_IDS[view] + '"'));
    api.setView(view);
    const active = sectionIds.filter(id => nodes.get(id).classList.active);
    assert.deepEqual(active, [api.VIEW_IDS[view]]);
    assert.equal(windowMock.location.hash, "#" + api.VIEW_IDS[view]);
    assert.equal(buttons.find(b => b.dataset.view === view).classList.active, true);
  }
});

test("command-center deep links open Backtest and Research Lab", () => {
  for (const view of ["backtest", "lab"]) {
    windowMock.location.hash = "#" + api.VIEW_IDS[view];
    assert.equal(api.viewFromHash(), view);
    api.setView(api.viewFromHash(), false);
    assert.equal(nodes.get(api.VIEW_IDS[view]).classList.active, true);
  }
  const main = fs.readFileSync("city.html", "utf8");
  assert.match(main, /city-research\.html#backtestView/);
  assert.match(main, /href="\/city-research\.html#backtestView"/);
  assert.match(main, /id="paperBotFleet"/);
  assert.match(main, /id="botFleetRows"/);
});

test("advanced research remains functional while trading desk is Paper/Demo only", () => {
  assert.match(html, /<option value="PAPER" selected>/);
  assert.match(source, /renderResearchLab\(/);
  const main=fs.readFileSync("city.html","utf8");
  assert.doesNotMatch(main, /backgroundShadowEvidence|SHADOW DISTRICT/);
  assert.match(main, /Kraken Paper/);
});

test("unknown view does not discard the current active panel", () => {
  api.setView("backtest");
  api.setView("not-a-real-panel");
  assert.equal(nodes.get("backtestView").classList.active, true);
});


test("MT5 demo ledger excludes BTC exchange demo and displays real BTC paper state", () => {
  const start=source.indexOf("function renderDemoBrokerLedger(");
  const end=source.indexOf("function renderMicroEngine(",start);
  assert.ok(start>=0 && end>start);
  const content=source.slice(start,end);
  const elements={
    demoBrokerSummary:{innerHTML:""},
    demoBrokerStatus:{textContent:""},
    demoBrokerFeed:{innerHTML:""}
  };
  const context={
    document:{getElementById:id=>elements[id]},
    safe:value=>String(value??""),
    utc:value=>String(value??""),
    currency:value=>String(value??""),
    fixed:value=>String(value??"")
  };
  const fn=vm.runInNewContext("const $=id=>document.getElementById(id);\n"+
    content+"\nrenderDemoBrokerLedger",context);
  fn({
    connected_accounts:[
      {provider:"MT5_DEMO",sync_status:"SYNCED_DEMO",market:"XAUUSD"},
      {provider:"BINANCE_SPOT_DEMO",sync_status:"SYNCED_DEMO",market:"BTCUSDT"}
    ],
    recent_fills:[
      {provider:"MT5_DEMO",symbol:"XAUUSD",external_id:"gold-deal",
       side:"BUY",price:2200,qty:0.01},
      {provider:"BINANCE_SPOT_DEMO",symbol:"BTCUSDT",external_id:"btc-deal",
       side:"BUY",price:50000,qty:0.01}
    ]
  },{agents:[{symbol:"BTC",agent_id:"btc-paper-1"}],active_intervals_minutes:[1,5]});
  assert.match(elements.demoBrokerSummary.innerHTML,/BTC · KRAKEN PAPER/);
  assert.match(elements.demoBrokerSummary.innerHTML,/2 FRESH FEEDS/);
  assert.match(elements.demoBrokerFeed.innerHTML,/gold-deal/);
  assert.doesNotMatch(elements.demoBrokerFeed.innerHTML,/btc-deal/);
  assert.doesNotMatch(elements.demoBrokerSummary.innerHTML,/BINANCE SPOT BTC/);
  assert.match(fs.readFileSync("mission.js","utf8"),/Kraken Paper/);
  assert.match(fs.readFileSync("city.html","utf8"),/Pepperstone Demo/);
});


test("Gold market desk exposes source attribution and Pepperstone Demo TradingView steps", () => {
  const main=fs.readFileSync("city.html","utf8");
  const bridge=fs.readFileSync("gold-desk.js","utf8");
  assert.doesNotThrow(() => new vm.Script(bridge));
  for (const id of ["goldDemo","goldSpotPrice","goldSpotTime","goldSpotSource",
    "goldDemoPositions","goldDemoTrades","goldIntegrationNote","goldTradingViewSteps"])
    assert.match(main,new RegExp('id="'+id+'"'));
  assert.match(main,/href="https:\/\/www\.tradingview\.com\/chart\/"/);
  assert.match(main,/Pepperstone/);
  assert.match(main,/src="\/gold-desk\.js"/);
  assert.match(bridge,/\/api\/stage3\?gold_desk=1/);
  assert.match(bridge,/INDICATIVE|last_known_price|STALE_SOURCE_QUOTE/);
  assert.doesNotMatch(main,/app\.metaapi\.cloud\/accounts|MT5 Demo|shadow positions/);
  assert.doesNotMatch(bridge,/order_send|placeOrder|createOrder|innerHTML/);
});

test("operational diagnostics render real source receipts, never strategy order controls", () => {
  const mission = fs.readFileSync("city.html","utf8");
  const script = fs.readFileSync("ops-health.js","utf8");
  assert.doesNotThrow(() => new vm.Script(script));
  assert.match(mission, /id="opsHealthPanel"/);
  assert.match(mission, /id="healthDatabase"/);
  assert.match(mission, /id="healthKraken"/);
  assert.match(mission, /id="healthForward"/);
  assert.match(mission, /src="\/ops-health\.js"/);
  assert.match(script, /\/api\/stage3\?diagnostics=1/);
  assert.match(script, /missing_intervals_minutes/);
  assert.match(script, /NO_EVIDENCE/);
  assert.doesNotMatch(script, /order_send|createOrder|placeOrder|POST/);
});


test("external risk critics have explicit owner controls and no broker execution", () => {
  const page = fs.readFileSync("city.html","utf8");
  const js = fs.readFileSync("research-advisors.js","utf8");
  assert.doesNotThrow(() => new vm.Script(js));
  for(const id of [
    "externalResearchPanel","advisorOwnerKey","advisorGrokReview",
    "advisorGrok","advisorJev","advisorRefresh","advisorStatus","advisorResult"
  ]) assert.match(page,new RegExp('id="'+id+'"'));
  assert.match(page,/src="\/research-advisors\.js"/);
  assert.match(js,/\/api\/stage3\?research_advisors=1/);
  assert.match(js,/\/api\/stage3\?grok_review=1/);
  assert.match(js,/key\.value\.trim\(\)\.length < 24/);
  assert.match(js,/output\.textContent/);
  assert.doesNotMatch(js,/innerHTML|order_send|placeOrder|walletKey/);
});
