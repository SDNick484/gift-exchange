// Frontend unit tests: `node --test tests/`. The modules under static/js/ are ES modules with no top-level DOM
// access, so they load in Node as they are; only the DOM-free helpers are tested here.
import assert from "node:assert/strict";
import { test } from "node:test";

import { dayLabel, daysLabel, esc, eventDateLabel, hostLabel, inkFor, isStale, monthLabel, money, parseHash, validAccent } from "../static/js/core.js";

test("esc", () => assert.equal(esc(`<a href="x">'&`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;"));
test("money", () => { assert.equal(money(5000), "$50"); assert.equal(money(2999), "$29.99"); assert.equal(money(null), ""); });
test("daysLabel", () => { assert.equal(daysLabel(41), "41 days"); assert.equal(daysLabel(1), "1 day"); assert.equal(daysLabel(0), "today"); assert.equal(daysLabel(-2), "2 days ago"); });
test("hostLabel", () => { assert.equal(hostLabel("https://www.amazon.com/hz/x"), "amazon.com"); assert.equal(hostLabel("bad"), ""); });
test("isStale", () => { const now = 1_800_000_000; assert.equal(isStale(now - 183 * 86400, now), true); assert.equal(isStale(now - 30 * 86400, now), false); });

test("esc leaves nothing out", () => {
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
  assert.equal(esc(0), "0");
  assert.equal(esc("&amp;"), "&amp;amp;");
  assert.equal(esc("<img src=x onerror=alert(1)>"), "&lt;img src=x onerror=alert(1)&gt;");
});

test("money edge cases", () => {
  assert.equal(money(0), "$0");
  assert.equal(money(5), "$0.05");
  assert.equal(money(100000), "$1,000");
  assert.equal(money(undefined), "");
  assert.equal(money("50"), "");
});

test("hostLabel only names web links", () => {
  assert.equal(hostLabel("http://shop.example.com/a?b=1"), "shop.example.com");
  assert.equal(hostLabel("javascript:alert(1)"), "");
  assert.equal(hostLabel(null), "");
});

test("isStale without a date is not stale", () => {
  assert.equal(isStale(null, 1_800_000_000), false);
  assert.equal(isStale(1_800_000_000 - 182 * 86400, 1_800_000_000), false);
});

test("monthLabel and dayLabel", () => {
  const mid = Date.UTC(2025, 10, 15, 12) / 1000; // Nov 15 2025, noon UTC: the same date in every time zone
  assert.equal(monthLabel(mid), "Nov 2025");
  assert.equal(dayLabel(mid), "Nov 15");
  assert.equal(monthLabel(null), "");
  assert.equal(dayLabel(null), "");
});

test("validAccent accepts #rrggbb only", () => {
  assert.equal(validAccent("#1a2B3c"), "#1a2B3c");
  for (const bad of [null, "", "red", "#123", "#1234567", "#12345g", "#123456;x:y", " #123456"]) {
    assert.equal(validAccent(bad), null, String(bad));
  }
});

test("parseHash", () => {
  assert.deepEqual(parseHash("#/x/cousins/p/3?e=7"), { parts: ["x", "cousins", "p", "3"], query: { e: "7" } });
  assert.deepEqual(parseHash(""), { parts: [], query: {} });
  assert.deepEqual(parseHash("#/admin"), { parts: ["admin"], query: {} });
});

test("inkFor picks readable text for an accent", () => {
  assert.equal(inkFor("#1d4f3c"), "#ffffff");
  assert.equal(inkFor("#ffee88"), "#15191a");
  assert.equal(inkFor("#000000"), "#ffffff");
  assert.equal(inkFor("#ffffff"), "#15191a");
});

test("eventDateLabel reads a calendar day", () => {
  assert.equal(eventDateLabel("2026-12-24"), "Thu, Dec 24");
  assert.equal(eventDateLabel(null), "");
  assert.equal(eventDateLabel("12/24"), "");
});
