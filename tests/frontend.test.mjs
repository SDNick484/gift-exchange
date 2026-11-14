// Frontend unit tests: `node --test tests/`. The modules under static/js/ are ES modules with no top-level DOM
// access, so they load in Node as they are; only the DOM-free helpers are tested here.
import assert from "node:assert/strict";
import { test } from "node:test";

import { cleanMe, meCookie, parseMe } from "../static/js/whoami.js";
import {
  freshValues, lastText, lastUpdate, mergeFresh, profileBody, renderBasicsView, renderConflict, renderItemView, renderReloaded,
  savedRows, stamps, UNDO_MS, renderUndo,
} from "../static/js/person.js";
import { choicesFor, chosenOf, drawBlocked, pairsBody, renderChecks, renderDrawLink, rosterOf } from "../static/js/admin-pairings.js";
import {
  drawBody, exclusionPairs, LOOKBACKS, pairProblem, personChoices, renderBlocked, renderExclusions, renderPreview, renderScreen as renderDrawScreen,
  withoutIndex, withPair,
} from "../static/js/admin-draw.js";
import { centsToText, moved, nextYear, renderAdminHome, renderLogin, rosterChoices } from "../static/js/admin.js";
import { ADMIN_SIGN_IN } from "../static/js/unlock.js";
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

const STALE = "Someone else just changed this list. Reload to see it.";
const NOW = Math.floor(Date.now() / 1000);
const PAGE = {
  person: { id: 2, name: "Sam" }, edition_id: 7, about: "Likes <tea>", amazon_url: "https://www.amazon.com/hz/wishlist/ls/ABC123",
  version: 3, updated_at: NOW - 3 * 86400, updated_by: "Sam",
  profile: [
    { field_id: 11, label: "Shirt size", hint: null, value: "M", updated_at: NOW - 200 * 86400, updated_by: "Sam" },
    { field_id: 12, label: "Shoe size", hint: null, value: "9 <b>", updated_at: NOW - 10 * 86400, updated_by: "Alex" },
    { field_id: 13, label: "Please avoid", hint: "dislikes", value: null, updated_at: null, updated_by: null },
  ],
  items: [{ id: 5, title: "Socks <x>", url: "https://shop.example.com/s", note: "wool", version: 2, updated_at: NOW - 86400, updated_by: "Riley" }],
};

test("person: the basics show filled fields, dimmed when stale", () => {
  const html = renderBasicsView(PAGE);
  assert.ok(html.includes("Shirt size") && html.includes("Shoe size") && !html.includes("Please avoid"));
  assert.ok(html.includes("9 &lt;b&gt;") && !html.includes("<b>"));
  assert.match(html, /<div class="stale"><dt>Shirt size<\/dt>.*may be out of date/);
  assert.match(html, /<div class=""><dt>Shoe size<\/dt><dd>9 &lt;b&gt;<\/dd><dd class="when">updated [A-Z][a-z]{2} \d{4}<\/dd>/);
});

test("person: an idea links out by host, escaped", () => {
  const html = renderItemView(PAGE.items[0], false, 0, 1);
  assert.ok(html.includes('target="_blank" rel="noopener noreferrer">Open link · shop.example.com</a>'));
  assert.ok(html.includes("Socks &lt;x&gt;") && !html.includes("<x>"));
  assert.ok(html.includes('data-act="delete"') && !html.includes('data-act="up"') && !html.includes('data-act="down"'));
  assert.ok(!renderItemView(PAGE.items[0], true, 0, 1).includes("data-act"));
});

test("person: the last change on the page", () => {
  assert.deepEqual(lastUpdate(PAGE), { at: NOW - 86400, by: "Riley" });
  assert.match(lastText(PAGE), /^Last updated by Riley, [A-Z][a-z]{2} \d{1,2}$/);
  assert.equal(lastText({ ...PAGE, updated_at: null, items: [], profile: [] }), "");
});

test("person: a profile save sends only the fields typed in", () => {
  const orig = { f11: "M", f12: "9 <b>", f13: "" };
  const body = profileBody({ f11: "L", f12: "9 <b>", f13: "" }, orig, stamps(PAGE.profile));
  assert.deepEqual(body, { values: { 11: "L" }, expected: { 11: NOW - 200 * 86400 } });
  assert.deepEqual(profileBody({ f13: "nuts" }, orig, stamps(PAGE.profile)), { values: { 13: "nuts" }, expected: { 13: null } });
  assert.deepEqual(profileBody(orig, orig, {}), { values: {}, expected: {} });
});

test("person: Reload keeps typed fields and refreshes the untouched ones", () => {
  const orig = { title: "Socks", url: "", note: "wool" };
  const typed = { title: "Warm socks", url: "", note: "wool" };
  const fresh = { title: "Socks", url: "https://shop.example.com/s", note: "merino" };
  const m = mergeFresh(typed, orig, fresh);
  assert.deepEqual(m.set, { url: "https://shop.example.com/s", note: "merino" });
  assert.deepEqual(m.orig, { title: "Socks", url: "https://shop.example.com/s", note: "merino" });
  assert.deepEqual(m.touched, ["title"]);
  assert.deepEqual(freshValues("item", PAGE, 5), { title: "Socks <x>", url: "https://shop.example.com/s", note: "wool" });
  assert.equal(freshValues("item", PAGE, 99), null);
  assert.deepEqual(freshValues("details", PAGE), { about: "Likes <tea>", amazon_url: "https://www.amazon.com/hz/wishlist/ls/ABC123" });
  assert.deepEqual(savedRows("basics", PAGE, freshValues("basics", PAGE), ["f12"]), [{ label: "Shoe size", value: "9 <b>" }]);
});

test("person: the 409 box shows the server's message and Reload, escaped", () => {
  const html = renderConflict(STALE, true);
  assert.ok(html.includes(STALE) && html.includes('data-act="reload"') && html.includes("Your typing is still in the form below"));
  assert.ok(renderConflict("<i>", false, "reload-list").includes('&lt;i&gt;</p>'));
  assert.ok(!renderConflict(STALE, false).includes("Your typing"));
  const reloaded = renderReloaded([{ label: "Note", value: "<img src=x>" }, { label: "Link", value: "" }], false);
  assert.ok(reloaded.includes("Here's what's saved now") && reloaded.includes("&lt;img src=x&gt;") && reloaded.includes("(empty)"));
  assert.ok(reloaded.includes('data-act="use-saved"') && !reloaded.includes("<img"));
  assert.ok(renderReloaded([], true).includes("deleted on another phone"));
});

test("admin: budget text, next year, roster choices, field order", () => {
  assert.equal(centsToText(5000), "50");
  assert.equal(centsToText(2999), "29.99");
  assert.equal(centsToText(5), "0.05");
  assert.equal(centsToText(null), "");
  assert.equal(nextYear([{ year: 2025 }, { year: 2026 }]), 2027);
  assert.equal(nextYear([], new Date(2026, 10, 13)), 2026);
  const people = [{ id: 1, active: true }, { id: 2, active: false }, { id: 3, active: false }];
  assert.deepEqual(rosterChoices(people, { person_ids: [3] }).map(p => p.id), [1, 3]);
  assert.deepEqual(moved([1, 2, 3], 2, -1), [2, 1, 3]);
  assert.deepEqual(moved([1, 2, 3], 3, 1), null);
  assert.deepEqual(moved([1, 2, 3], 1, 1), [2, 1, 3]);
});

test("admin: exchange names are escaped", () => {
  const html = renderAdminHome([{ id: 1, slug: "x", name: "<b>Adults</b>", active: false }]);
  assert.ok(html.includes("&lt;b&gt;Adults&lt;/b&gt; (closed to the family)") && !html.includes("<b>"));
});

test("pairings: roster, choices and the draft body", () => {
  const people = [{ id: 3, name: "jordan" }, { id: 1, name: "Alex" }, { id: 2, name: "Sam" }, { id: 9, name: "Off roster" }];
  const roster = rosterOf(people, { person_ids: [1, 2, 3] });
  assert.deepEqual(roster.map(p => p.name), ["Alex", "jordan", "Sam"]);
  assert.deepEqual(choicesFor(roster[0], roster, undefined).map(c => c.label), ["Not entered yet", "jordan", "Sam"]);
  assert.deepEqual(choicesFor(roster[0], roster, 1).map(c => c.label), ["Not entered yet", "Alex", "jordan", "Sam"]);
  assert.deepEqual(chosenOf([{ giver_id: 1, recipient_id: 2 }, { giver_id: 2, recipient_id: null }]), { 1: 2 });
  assert.deepEqual(pairsBody({ 1: "2", 2: "", 3: "1" }), [{ giver_id: 1, recipient_id: 2 }, { giver_id: 3, recipient_id: 1 }]);
});

test("pairings: problems and warnings are escaped", () => {
  const html = renderChecks({ problems: ["<b>Sam</b> isn't getting a gift."], warnings: ["Alex had <i>Sam</i> last year too."] });
  assert.ok(html.includes("&lt;b&gt;Sam&lt;/b&gt;") && html.includes("&lt;i&gt;Sam&lt;/i&gt;") && !html.includes("<b>Sam"));
  assert.ok(renderChecks({ problems: [], warnings: [] }).includes("Everyone gives once and gets once."));
});

test("admin sign-in: the box a phone keyboard leaves alone, and a way to it from home", () => {
  const html = renderLogin();
  assert.match(html, /autocapitalize="none"/);
  assert.match(html, /spellcheck="false"/);
  assert.match(html, /name="show" type="checkbox"/);
  assert.match(ADMIN_SIGN_IN, /href="#\/admin"/);
});

test("renderUndo says Deleted, offers Undo and escapes the title", () => {
  const html = renderUndo({ id: 7, title: `<b>"Socks"</b>` });
  assert.match(html, /Deleted · <button[^>]*data-act="undo"[^>]*>Undo<\/button>/);
  assert.match(html, /data-undo="7"/);
  assert.ok(!html.includes("<b>"));
  assert.equal(UNDO_MS, 8000);
});

// ---------------------------------------------------------------- the in-app draw (admin-draw.js)
test("drawBlocked: only an open year with nothing entered can draw", () => {
  assert.equal(drawBlocked({ status: "open", pairs: [] }), "");
  assert.match(drawBlocked({ status: "open", pairs: [{ giver_id: 1, recipient_id: null }] }), /already entered/);
  assert.match(drawBlocked({ status: "paired", pairs: [] }), /marked paired/);
  assert.match(drawBlocked({ status: "closed", pairs: [] }), /closed/);
});

test("renderDrawLink links to the draw or says why not", () => {
  assert.match(renderDrawLink(7, { status: "open", pairs: [] }), /href="#\/admin\/e\/7\/draw"/);
  const no = renderDrawLink(7, { status: "closed", pairs: [] });
  assert.doesNotMatch(no, /href=/);
  assert.match(no, /closed/);
});

test("drawBody", () => {
  assert.deepEqual(drawBody("2", true), { lookback: 2, single_loop: true });
  assert.deepEqual(drawBody("", "on"), { lookback: 1, single_loop: false });
  assert.deepEqual(LOOKBACKS.map(o => o.value), [1, 2, 3]);
});

test("exclusion bodies add and remove pairs", () => {
  const list = [{ a_id: 1, a: "Alex", b_id: 2, b: "Sam" }, { a_id: 3, a: "Jordan", b_id: 4, b: "Riley" }];
  assert.deepEqual(exclusionPairs(list), [[1, 2], [3, 4]]);
  assert.deepEqual(withPair(list, 5, 1), [[1, 2], [3, 4], [5, 1]]);
  assert.deepEqual(withoutIndex(list, 0), [[3, 4]]);
  assert.equal(pairProblem(list, 0, 2), "Pick two people.");
  assert.equal(pairProblem(list, 2, 2), "Pick two different people.");
  assert.equal(pairProblem(list, 2, 1), "That pair is already on the list.");
  assert.equal(pairProblem(list, 1, 3), "");
});

test("personChoices puts a blank first", () => {
  assert.deepEqual(personChoices([{ id: 1, name: "Alex" }]), [{ value: "", label: "Choose someone" }, { value: 1, label: "Alex" }]);
});

test("draw markup escapes every name", () => {
  const bad = "<img src=x onerror=1>";
  const x = { id: 1, name: bad };
  const edition = { id: 2, label: bad };
  const roster = [{ id: 3, name: bad }];
  const list = [{ a_id: 3, a: bad, b_id: 4, b: bad }];
  for (const html of [renderExclusions(list), renderPreview({ preview: [{ giver: bad, recipient: bad }] }),
    renderDrawScreen(x, edition, roster, list), renderBlocked(x, edition, bad)]) {
    assert.doesNotMatch(html, /<img/);
    assert.match(html, /&lt;img/);
  }
  assert.match(renderExclusions([]), /None yet/);
});
