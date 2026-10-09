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
  assert.match(fs.readFileSync("city.html", "utf8"), /city-research\.html#backtestView/);
});

test("shadow remains behind the scenes and paper is primary in feed", () => {
  assert.match(html, /id="backgroundShadowEvidence" hidden/);
  assert.match(html, /<option value="PAPER" selected>/);
  assert.match(source, /renderResearchLab\(/);
});

test("unknown view does not discard the current active panel", () => {
  api.setView("backtest");
  api.setView("not-a-real-panel");
  assert.equal(nodes.get("backtestView").classList.active, true);
});
