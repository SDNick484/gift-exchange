// Frontend unit tests: `node --test tests/`. The modules under static/js/ are ES modules with no top-level DOM
// access, so they load in Node as they are; only the DOM-free helpers are tested here.
import assert from "node:assert/strict";
import { test } from "node:test";

import { cleanMe, meCookie, parseMe } from "../static/js/whoami.js";
import { factsOf, ideasLabel, personHash, renderHome, youFirst, youreGetting } from "../static/js/home.js";
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

test("who am I: the cookie round-trips per exchange", () => {
  const set = meCookie("cousins", { person_id: 3, name: "Sam" }, true);
  assert.match(set, /^gx_me_cousins=[^;]+; Path=\/; Max-Age=34560000; SameSite=Lax; Secure$/);
  const jar = `gx_me_adults=x; ${set.split(";")[0]}; other=1`;
  assert.deepEqual(parseMe(jar, "cousins"), { person_id: 3, name: "Sam" });
  assert.equal(parseMe(jar, "adults"), null);         // not JSON
  assert.equal(parseMe(jar, "family"), null);         // not set
  assert.doesNotMatch(meCookie("cousins", { person_id: 3, name: "Sam" }, false), /Secure/);
});

test("who am I: just looking keeps a name and no person", () => {
  const set = meCookie("cousins", { person_id: null, name: "  Pat; <b>  " }, false).split(";")[0];
  assert.deepEqual(parseMe(set, "cousins"), { person_id: null, name: "Pat; <b>" });
});

test("who am I: bad values are refused", () => {
  for (const bad of [null, {}, { person_id: null, name: " " }, { person_id: "3", name: "Sam" }, { person_id: 0, name: "Sam" },
    { person_id: 1.5, name: "Sam" }, { person_id: 3 }]) {
    assert.equal(cleanMe(bad), null, JSON.stringify(bad));
  }
  assert.equal(cleanMe({ person_id: null, name: "x".repeat(80) }).name.length, 60);
  assert.match(meCookie("cousins", null, false), /^gx_me_cousins=; Path=\/; Max-Age=0;/);
});

const HOME = {
  exchange: { slug: "cousins", name: "Cousins <b>", accent_color: null },
  edition: { id: 7, label: "2026", year: 2026, budget_cents: 5000, event_date: "2026-12-24", location: "Riley's house",
    rules: "One gift <script>", status: "paired", days_until: 41 },
  editions: [{ id: 7, label: "2026", status: "paired" }, { id: 6, label: "2025", status: "closed" }],
  people: [{ id: 1, name: "Alex", item_count: 4, has_amazon: true }, { id: 2, name: "Sam <i>", item_count: 0, has_amazon: false }],
  pairings: [{ giver_id: 1, giver: "Alex", recipient_id: 2, recipient: "Sam <i>" }, { giver_id: 2, giver: "Sam <i>", recipient_id: 1, recipient: "Alex" }],
};

test("home: the facts line", () => {
  assert.deepEqual(factsOf(HOME.edition), ["Thu, Dec 24", "Riley's house", "$50 limit", "in 41 days"]);
  assert.deepEqual(factsOf({ days_until: 0 }), ["today"]);
  assert.deepEqual(factsOf({ days_until: -2, budget_cents: null }), ["2 days ago"]);
});

test("home: you're getting, only for a person on the roster", () => {
  assert.equal(youreGetting(HOME.pairings, { person_id: 1, name: "Alex" }).recipient_id, 2);
  assert.equal(youreGetting(HOME.pairings, { person_id: null, name: "Pat" }), null);
  assert.equal(youreGetting(null, { person_id: 1, name: "Alex" }), null);
  assert.equal(youreGetting(HOME.pairings, null), null);
});

test("home: labels and order", () => {
  assert.equal(ideasLabel(0), "No ideas yet");
  assert.equal(ideasLabel(1), "1 idea");
  assert.equal(ideasLabel(4), "4 ideas");
  assert.deepEqual(youFirst(HOME.people, { person_id: 2, name: "Sam" }).map(p => p.id), [2, 1]);
  assert.equal(personHash("cousins", 2, "6"), "#/x/cousins/p/2?e=6");
  assert.equal(personHash("cousins", 2, null), "#/x/cousins/p/2");
});

test("home: renders escaped, with the banner and who has whom", () => {
  const html = renderHome(HOME, { person_id: 1, name: "Alex" }, null);
  assert.ok(html.includes("Cousins &lt;b&gt; · 2026"));
  assert.ok(html.includes("One gift &lt;script&gt;"));
  assert.ok(html.includes("You're getting") && html.includes("See Sam &lt;i&gt;'s list"));
  assert.ok(html.includes("Alex → Sam &lt;i&gt;"));
  assert.ok(!html.includes("<b>") && !html.includes("<i>") && !html.includes("<script>"));
  assert.ok(html.includes("2025 (closed)"));
});

test("home: names not drawn yet, and no banner for just looking", () => {
  const html = renderHome({ ...HOME, pairings: null }, { person_id: null, name: "Pat" }, null);
  assert.ok(html.includes("Names not drawn yet."));
  assert.ok(!html.includes("You're getting"));
  assert.ok(html.includes("(just looking)"));
});
