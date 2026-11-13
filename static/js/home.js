// #/x/<slug>[?e=<edition id>]  The exchange home: the year's date, place, budget and rules, "You're getting ...",
// who has whom (or "Names not drawn yet."), and everyone's lists. The first visit asks "Which one are you?".
import { get } from "./api.js";
import { applyAccent, daysLabel, esc, eventDateLabel, money, renderOptions } from "./core.js";
import { me, showPicker } from "./whoami.js";

export const homePath = (slug, editionId) =>
  `/api/x/${encodeURIComponent(slug)}${editionId ? `?edition=${encodeURIComponent(editionId)}` : ""}`;

// The hash of a person's page, keeping the year when one was picked.
export const personHash = (slug, pid, editionId) =>
  `#/x/${encodeURIComponent(slug)}/p/${encodeURIComponent(pid)}${editionId ? `?e=${encodeURIComponent(editionId)}` : ""}`;

// The pairing whose giver is this phone's person, or null (just looking, not drawn yet, not on this year's roster).
export function youreGetting(pairings, who) {
  if (!Array.isArray(pairings) || !who || who.person_id === null) return null;
  return pairings.find(p => p.giver_id === who.person_id && p.recipient_id !== null) ?? null;
}

// "Thu, Dec 24", "Riley's house", "$50 limit", "in 41 days": the facts that are set, in that order.
export function factsOf(edition) {
  const out = [];
  if (edition.event_date) out.push(eventDateLabel(edition.event_date));
  if (edition.location) out.push(edition.location);
  if (Number.isInteger(edition.budget_cents)) out.push(`${money(edition.budget_cents)} limit`);
  const n = edition.days_until;
  if (Number.isInteger(n)) out.push(n > 0 ? `in ${daysLabel(n)}` : daysLabel(n));
  return out;
}

export function ideasLabel(count) {
  if (!count) return "No ideas yet";
  return `${count} ${count === 1 ? "idea" : "ideas"}`;
}

// Everyone's lists with this phone's person first.
export function youFirst(people, who) {
  const mine = people.filter(p => who && p.id === who.person_id);
  return [...mine, ...people.filter(p => !mine.includes(p))];
}

const renderFact = f => `<span>${esc(f)}</span>`;
const renderFacts = edition => factsOf(edition).map(renderFact).join("");
const renderRules = edition => (edition.rules ? `<p class="rules"><strong>Rules:</strong> ${esc(edition.rules)}</p>` : "");
const renderClosed = edition => (edition.status === "closed" ? `<p class="msg warn">This year is closed. You can look, but the lists can't change.</p>` : "");
const yearOptions = editions => editions.map(e => ({ value: e.id, label: e.status === "closed" ? `${e.label} (closed)` : e.label }));
const renderYearPicker = (editions, edition) => (editions.length > 1
  ? `<label class="field"><span>Year</span><select data-act="year">${renderOptions(yearOptions(editions), edition.id)}</select></label>`
  : "");

const renderHead = h => `
  <section class="card head">
    <h1>${esc(h.exchange.name)} · ${esc(h.edition.label)}</h1>
    ${renderYearPicker(h.editions, h.edition)}
    <p class="facts">${renderFacts(h.edition)}</p>
    ${renderRules(h.edition)}
    ${renderClosed(h.edition)}
  </section>`;

const renderWhoName = who => (who.person_id === null ? `<strong>${esc(who.name)}</strong> (just looking)` : `<strong>${esc(who.name)}</strong>`);
const renderWho = who => (who
  ? `<p class="who"><span>You're ${renderWhoName(who)}</span><button class="linkish" type="button" data-act="notme">Not you?</button></p>`
  : `<p class="who"><button class="linkish" type="button" data-act="notme">Tell us which one you are</button></p>`);

const renderBanner = (pair, slug, editionId) => (pair ? `
  <section class="banner" aria-label="Who you're getting">
    <p>You're getting</p>
    <p class="big">${esc(pair.recipient)}</p>
    <p><a href="${esc(personHash(slug, pair.recipient_id, editionId))}">See ${esc(pair.recipient)}'s list</a></p>
  </section>` : "");

const renderPair = p => `<li>${esc(p.giver)} → ${esc(p.recipient ?? "?")}</li>`;
const renderPairRows = pairings => pairings.map(renderPair).join("");
const renderPairs = pairings => (pairings === null || pairings.length === 0
  ? `<p>Names not drawn yet.</p>`
  : `<ul class="pairs">${renderPairRows(pairings)}</ul>`);

const renderAmazon = p => (p.has_amazon ? " · Amazon list" : "");
const renderYou = (p, who) => (who && p.id === who.person_id ? " (you)" : "");
const renderPersonRow = (p, slug, editionId, who) => `
  <li class="link-row"><a href="${esc(personHash(slug, p.id, editionId))}">
    <span><span class="title">${esc(p.name)}${renderYou(p, who)}</span><br><span class="muted small">${esc(ideasLabel(p.item_count))}${renderAmazon(p)}</span></span>
    <span class="go">See list</span></a></li>`;
const renderPersonRows = (people, slug, editionId, who) => people.map(p => renderPersonRow(p, slug, editionId, who)).join("");
const renderPeople = (people, slug, editionId, who) => (people.length
  ? `<ul class="rows">${renderPersonRows(people, slug, editionId, who)}</ul>`
  : `<p>Nobody is on this year's list yet.</p>`);

export const renderHome = (h, who, editionId) => `
  ${renderHead(h)}
  ${renderWho(who)}
  ${renderBanner(youreGetting(h.pairings, who), h.exchange.slug, editionId)}
  <section class="card"><h2>Who has whom</h2>${renderPairs(h.pairings)}</section>
  <section class="card"><h2>Everyone's lists</h2>${renderPeople(youFirst(h.people, who), h.exchange.slug, editionId, who)}</section>`;

const renderNoEdition = h => `
  <section class="card head"><h1>${esc(h.exchange.name)}</h1>
    <p>Nothing is set up for this exchange yet. Check back once the organizer has added this year.</p></section>`;

export async function render(ctx) {
  const { view } = ctx;
  const slug = ctx.parts[1];
  const editionId = /^[0-9]+$/.test(ctx.query.e ?? "") ? ctx.query.e : null;
  const h = await get(homePath(slug, editionId));
  if (!ctx.alive()) return;
  applyAccent(h.exchange.accent_color);
  if (!h.edition) {
    view.innerHTML = renderNoEdition(h);
    return;
  }
  const who = me(slug);
  view.innerHTML = renderHome(h, who, editionId);
  view.querySelector("[data-act=year]")?.addEventListener("change", e => {
    location.hash = `#/x/${encodeURIComponent(slug)}?e=${encodeURIComponent(e.target.value)}`;
  });
  view.addEventListener("click", async e => {
    if (!e.target.closest("[data-act=notme]")) return;
    if (await showPicker(slug, h.people)) ctx.rerender();
  });
  // The first visit asks who this is; the page is already drawn behind the picker.
  if (!who && h.people.length) showPicker(slug, h.people).then(value => { if (value && ctx.alive()) ctx.rerender(); });
}
