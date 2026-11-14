// #/admin/e/<edition id>/pairings  Typing in the bowl's result: one dropdown per giver, what still stops Mark paired
// (problems, by name) and what is only worth a look (warnings), Save draft, Mark paired and Unpair, and a link to the
// in-app draw (admin-draw.js) while the year is open with nothing entered.
// A half-entered draft is saved as it stands, so nothing typed in is lost; the family sees nothing until Mark paired.
import { get, send } from "./api.js";
import { esc, renderDisabled, renderError, renderOptions, toast } from "./core.js";

// ---------------------------------------------------------------- DOM-free helpers (tests/frontend.test.mjs)
// The roster in name order: [{id, name}] of the edition's person_ids.
export function rosterOf(people, edition) {
  return people.filter(p => edition.person_ids.includes(p.id))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || a.id - b.id);
}

// {giver_id: recipient_id} from the overview's pairs (draft rows with no recipient left out).
export const chosenOf = pairs => Object.fromEntries((pairs ?? []).filter(p => p.recipient_id !== null).map(p => [p.giver_id, p.recipient_id]));

// The dropdown for one giver: everyone else on the roster, plus the giver themselves only when a saved draft already
// says so (so the problem shows rather than vanishing).
export function choicesFor(giver, roster, chosen) {
  const others = roster.filter(p => p.id !== giver.id || chosen === giver.id);
  return [{ value: "", label: "Not entered yet" }, ...others.map(p => ({ value: p.id, label: p.name }))];
}

// The PUT body from the dropdowns' values {giver_id: "recipient id" or ""}: only givers with someone chosen.
export function pairsBody(values) {
  return Object.entries(values).filter(([, r]) => r !== "").map(([g, r]) => ({ giver_id: Number(g), recipient_id: Number(r) }));
}

// Why the in-app draw (#/admin/e/<id>/draw) can't run for this overview, or "" when it can: it needs an open year with
// no names entered, not even a half-entered draft.
export function drawBlocked(o) {
  if (o.status === "paired") return "The names are already marked paired.";
  if (o.status !== "open") return "This year is closed.";
  if ((o.pairs ?? []).length) return "Names are already entered for this year. To draw instead, set everyone back to Not entered yet and save.";
  return "";
}

// ---------------------------------------------------------------- markup
const STATUS_NOTE = {
  open: "Type in the bowl's result. Save draft keeps what you've entered, even half of it. The family sees nothing until you press Mark paired.",
  paired: "Paired. The family can see these names. Unpair to change them.",
  closed: "This year is closed. Reopen it on the exchange's page to change anything.",
};
const renderRow = (giver, roster, chosen, locked) => `
  <div class="pair-row">
    <label for="giver-${esc(giver.id)}">${esc(giver.name)} gives to</label>
    <select id="giver-${esc(giver.id)}" name="giver" data-giver="${esc(giver.id)}"${renderDisabled(locked)}>${renderOptions(choicesFor(giver, roster, chosen[giver.id]), chosen[giver.id] ?? "")}</select>
  </div>`;
const renderRows = (roster, chosen, locked) => roster.map(g => renderRow(g, roster, chosen, locked)).join("");
const renderItem = text => `<li>${esc(text)}</li>`;
const renderItems = list => list.map(renderItem).join("");
const renderProblemList = problems => (problems.length
  ? `<div class="msg error"><p><strong>Still to sort out before Mark paired:</strong></p><ul class="problems">${renderItems(problems)}</ul></div>`
  : `<p class="msg ok">Everyone gives once and gets once.</p>`);
const renderWarnings = warnings => (warnings.length
  ? `<div class="msg warn"><p><strong>Worth a look (these don't stop Mark paired):</strong></p><ul class="problems">${renderItems(warnings)}</ul></div>`
  : "");
export const renderChecks = o => `${renderProblemList(o.problems)}${renderWarnings(o.warnings)}`;
export const renderDrawLink = (eid, o) => (drawBlocked(o)
  ? `<p class="small muted">In-app draw: ${esc(drawBlocked(o))}</p>`
  : `<p><a class="btn" href="#/admin/e/${esc(eid)}/draw">Draw names in the app instead</a></p>`);
const renderActions = status => {
  if (status === "open") return `<button class="btn" type="button" data-act="save-draft">Save draft</button><button class="btn primary" type="button" data-act="mark-paired">Mark paired</button>`;
  if (status === "paired") return `<button class="btn" type="button" data-act="unpair">Unpair</button>`;
  return "";
};
export const renderScreen = (x, edition, roster, o) => `
  <a class="back" href="#/admin/x/${esc(x.id)}">← Back to ${esc(x.name)}</a>
  <section class="card head">
    <h1>Pairings · ${esc(x.name)} ${esc(edition.label)}</h1>
    <p>${esc(STATUS_NOTE[o.status] ?? "")}</p>
  </section>
  <section class="card">
    <div data-slot="msg"></div>
    <form data-form="pairs" novalidate>${renderRows(roster, chosenOf(o.pairs), o.status !== "open")}</form>
    <div data-slot="problems">${renderChecks(o)}</div>
    <div class="btn-row">${renderActions(o.status)}</div>
  </section>
  <section class="card" data-slot="draw">${renderDrawLink(edition.id, o)}</section>`;

const renderNotFound = () => `<div class="notice"><p>No such year.</p><p><a class="btn" href="#/admin">All exchanges</a></p></div>`;
const renderNeedsAdmin = () => `<div class="notice"><p>Sign in as admin first.</p><p><a class="btn primary" href="#/admin">Admin sign-in</a></p></div>`;

// ---------------------------------------------------------------- the screen
// The exchange and edition an edition id belongs to (the admin API lists editions per exchange).
export async function findEdition(eid) {
  const list = await get("/api/admin/exchanges");
  const all = await Promise.all(list.map(x => get(`/api/admin/exchanges/${x.id}/editions`)));
  for (const [i, editions] of all.entries()) {
    const edition = editions.find(e => e.id === eid);
    if (edition) return { x: list[i], edition };
  }
  return null;
}

export async function render(ctx) {
  const { view } = ctx;
  const eid = Number(ctx.parts[2]);
  const session = await get("/api/session");
  if (!ctx.alive()) return;
  if (!session.admin) {
    view.innerHTML = renderNeedsAdmin();
    return;
  }
  const found = await findEdition(eid);
  if (!ctx.alive()) return;
  if (!found) {
    view.innerHTML = renderNotFound();
    return;
  }
  const { x, edition } = found;
  const [people, first] = await Promise.all([get(`/api/admin/exchanges/${x.id}/people`), get(`/api/admin/editions/${eid}/pairings`)]);
  if (!ctx.alive()) return;
  const roster = rosterOf(people, edition);
  const values = () => Object.fromEntries([...view.querySelectorAll("select[data-giver]")].map(s => [s.dataset.giver, s.value]));
  let saved = "{}"; // the dropdowns as last loaded or saved
  const remember = () => { saved = JSON.stringify(values()); };
  const draw = o => {
    view.innerHTML = renderScreen(x, edition, roster, o);
    remember();
  };
  draw(first);

  // Leaving the page (closing the tab, reloading) while the dropdowns differ from what's saved asks first.
  const warnOnLeave = e => {
    if (!ctx.alive()) window.removeEventListener("beforeunload", warnOnLeave);
    else if (JSON.stringify(values()) !== saved) {
      e.preventDefault();
      e.returnValue = "";
    }
  };
  window.addEventListener("beforeunload", warnOnLeave);

  const slot = () => view.querySelector("[data-slot=msg]");
  const overview = () => get(`/api/admin/editions/${eid}/pairings`);
  const saveDraft = async () => {
    const sent = values();
    await send("PUT", `/api/admin/editions/${eid}/pairings`, { pairs: pairsBody(sent) });
    saved = JSON.stringify(sent);
  };
  const showChecks = o => {
    view.querySelector("[data-slot=problems]").innerHTML = renderChecks(o);
    view.querySelector("[data-slot=draw]").innerHTML = renderDrawLink(eid, o);
  };

  view.addEventListener("click", async e => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    slot().innerHTML = "";
    btn.disabled = true;
    try {
      if (act === "save-draft") {
        await saveDraft();
        showChecks(await overview());
        toast("Draft saved");
      } else if (act === "mark-paired") {
        await saveDraft(); // what's on screen is what gets checked
        try {
          await send("POST", `/api/admin/editions/${eid}/mark-paired`, {});
        } finally {
          showChecks(await overview());
        }
        draw(await overview());
        toast("Marked paired");
      } else if (act === "unpair") {
        await send("POST", `/api/admin/editions/${eid}/unpair`, {});
        draw(await overview());
        toast("Unpaired");
      }
    } catch (err) {
      slot().innerHTML = renderError(err?.error ?? "Something went wrong. Try again.");
      slot().scrollIntoView({ block: "nearest" });
    } finally {
      if (btn.isConnected) btn.disabled = false;
    }
  });
}
