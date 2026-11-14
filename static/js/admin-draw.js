// #/admin/e/<edition id>/draw  The in-app draw, for a year the family isn't drawing from a bowl: who never draws whom
// (exclusions, saved as they change), how many years back to look, one big loop or any draw, then a preview with
// Redraw and Publish. Nothing about the pairings is saved until Publish; the server keeps the preview for 10 minutes.
// Hidden, with the reason, unless the year is open with no names entered.
import { get, send } from "./api.js";
import { esc, renderError, renderOptions, toast } from "./core.js";
import { drawBlocked, findEdition, rosterOf } from "./admin-pairings.js";

// ---------------------------------------------------------------- DOM-free helpers (tests/frontend.test.mjs)
export const LOOKBACKS = [
  { value: 1, label: "Last year" },
  { value: 2, label: "The last 2 years" },
  { value: 3, label: "The last 3 years" },
];

// The draw's request body from the form's values.
export const drawBody = (lookback, singleLoop) => ({ lookback: Number(lookback) || 1, single_loop: singleLoop === true });

// The exclusions PUT body from the GET's [{a_id, b_id}], with one pair added or one index left out.
export const exclusionPairs = list => list.map(p => [p.a_id, p.b_id]);
export const withPair = (list, a, b) => [...exclusionPairs(list), [a, b]];
export const withoutIndex = (list, i) => exclusionPairs(list).filter((_, j) => j !== i);

// Why two chosen ids can't be added, or "" when they can.
export function pairProblem(list, a, b) {
  if (!a || !b) return "Pick two people.";
  if (a === b) return "Pick two different people.";
  if (list.some(p => (p.a_id === a && p.b_id === b) || (p.a_id === b && p.b_id === a))) return "That pair is already on the list.";
  return "";
}

// The person dropdown: a blank choice, then the roster in name order.
export const personChoices = roster => [{ value: "", label: "Choose someone" }, ...roster.map(p => ({ value: p.id, label: p.name }))];

// ---------------------------------------------------------------- markup
const renderExclusion = (p, i) => `
  <li class="pair-line"><span>${esc(p.a)} and ${esc(p.b)}</span>
    <button class="btn quiet" type="button" data-act="drop-exclusion" data-index="${esc(i)}">Remove</button></li>`;
const renderExclusionItems = list => list.map(renderExclusion).join("");
export const renderExclusions = list => (list.length
  ? `<ul class="rows">${renderExclusionItems(list)}</ul>`
  : `<p class="muted">None yet.</p>`);

const renderPreviewRow = p => `<li><strong>${esc(p.giver)}</strong> gives to <strong>${esc(p.recipient)}</strong></li>`;
const renderPreviewRows = list => list.map(renderPreviewRow).join("");
export const renderPreview = got => `
  <div class="msg warn"><p><strong>Not saved yet.</strong> Nobody sees these names until you press Publish. This draw is good for 10 minutes.</p></div>
  <ul class="pairs">${renderPreviewRows(got.preview)}</ul>
  <div class="btn-row">
    <button class="btn" type="button" data-act="redraw">Redraw</button>
    <button class="btn primary" type="button" data-act="publish">Publish</button>
  </div>`;

const renderHead = (x, edition) => `
  <a class="back" href="#/admin/e/${esc(edition.id)}/pairings">← Back to the pairings</a>
  <section class="card head">
    <h1>Draw · ${esc(x.name)} ${esc(edition.label)}</h1>
    <p>For a year without the bowl: the app draws the names, you look them over, then Publish marks them paired.</p>
  </section>`;

export const renderBlocked = (x, edition, reason) => `${renderHead(x, edition)}
  <div class="notice"><p>${esc(reason)}</p><p><a class="btn" href="#/admin/e/${esc(edition.id)}/pairings">Go to the pairings</a></p></div>`;

export const renderScreen = (x, edition, roster, list) => `${renderHead(x, edition)}
  <section class="card">
    <h2>Never pair</h2>
    <p class="small muted">These two never draw each other, either way round. People in the same household, and last year's pairs, are kept apart already.</p>
    <div data-slot="exclusions">${renderExclusions(list)}</div>
    <form data-form="exclusion" novalidate>
      <div class="pair-row"><label for="ex-a">Person</label><select id="ex-a" name="a">${renderOptions(personChoices(roster), "")}</select></div>
      <div class="pair-row"><label for="ex-b">Never with</label><select id="ex-b" name="b">${renderOptions(personChoices(roster), "")}</select></div>
      <div class="btn-row"><button class="btn" type="submit">Add the pair</button></div>
    </form>
    <div data-slot="exclusion-msg"></div>
  </section>
  <section class="card">
    <h2>Draw</h2>
    <form data-form="draw" novalidate>
      <label class="field"><span>Nobody draws who they had in</span>
        <span class="hint">Nobody draws the person who had them last year either, however far back this looks.</span>
        <select name="lookback">${renderOptions(LOOKBACKS, 1)}</select></label>
      <label class="check"><input name="single_loop" type="checkbox"> One big loop: everyone in a single chain that comes back round to the start</label>
      <div class="btn-row"><button class="btn primary" type="submit">Draw names</button></div>
    </form>
    <div data-slot="msg"></div>
    <div data-slot="preview"></div>
  </section>`;

const renderNeedsAdmin = () => `<div class="notice"><p>Sign in as admin first.</p><p><a class="btn primary" href="#/admin">Admin sign-in</a></p></div>`;
const renderNotFound = () => `<div class="notice"><p>No such year.</p><p><a class="btn" href="#/admin">All exchanges</a></p></div>`;

// ---------------------------------------------------------------- the screen
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
  const [people, overview, first] = await Promise.all([
    get(`/api/admin/exchanges/${x.id}/people`),
    get(`/api/admin/editions/${eid}/pairings`),
    get(`/api/admin/editions/${eid}/exclusions`),
  ]);
  if (!ctx.alive()) return;
  const reason = drawBlocked(overview);
  if (reason) {
    view.innerHTML = renderBlocked(x, edition, reason);
    return;
  }
  const roster = rosterOf(people, edition);
  let list = first.pairs;
  let token = null;
  view.innerHTML = renderScreen(x, edition, roster, list);

  const slot = name => view.querySelector(`[data-slot=${name}]`);
  const showError = (name, err) => {
    slot(name).innerHTML = renderError(err?.error ?? "Something went wrong. Try again.");
    slot(name).scrollIntoView({ block: "nearest" });
  };
  // A preview drawn under other rules or options is no longer what Publish would check: take it away.
  const dropPreview = () => {
    token = null;
    slot("preview").innerHTML = "";
  };
  const saveExclusions = async pairs => {
    await send("PUT", `/api/admin/editions/${eid}/exclusions`, { pairs });
    list = (await get(`/api/admin/editions/${eid}/exclusions`)).pairs;
    if (!ctx.alive()) return;
    slot("exclusions").innerHTML = renderExclusions(list);
    dropPreview();
  };
  const drawForm = () => view.querySelector("form[data-form=draw]");
  const runDraw = async () => {
    const f = drawForm();
    slot("msg").innerHTML = "";
    dropPreview();
    const got = await send("POST", `/api/admin/editions/${eid}/draw`, drawBody(f.lookback.value, f.single_loop.checked));
    if (!ctx.alive()) return;
    token = got.token;
    slot("preview").innerHTML = renderPreview(got);
  };

  view.addEventListener("submit", async e => {
    const form = e.target.closest("form[data-form]");
    if (!form) return;
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      if (form.dataset.form === "exclusion") {
        slot("exclusion-msg").innerHTML = "";
        const a = Number(form.a.value) || 0;
        const b = Number(form.b.value) || 0;
        const problem = pairProblem(list, a, b);
        if (problem) {
          slot("exclusion-msg").innerHTML = renderError(problem);
          return;
        }
        try {
          await saveExclusions(withPair(list, a, b));
          form.reset();
          toast("Pair added");
        } catch (err) {
          showError("exclusion-msg", err);
        }
      } else if (form.dataset.form === "draw") {
        try {
          await runDraw();
        } catch (err) {
          showError("msg", err);
        }
      }
    } finally {
      if (btn.isConnected) btn.disabled = false;
    }
  });

  // Changing the look-back or the loop option takes the old preview away, so Publish never sends one drawn otherwise.
  view.addEventListener("change", e => {
    if (e.target.closest("form[data-form=draw]")) dropPreview();
  });

  view.addEventListener("click", async e => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    btn.disabled = true;
    try {
      if (act === "drop-exclusion") {
        slot("exclusion-msg").innerHTML = "";
        try {
          await saveExclusions(withoutIndex(list, Number(btn.dataset.index)));
          toast("Pair removed");
        } catch (err) {
          showError("exclusion-msg", err);
        }
      } else if (act === "redraw") {
        try {
          await runDraw();
        } catch (err) {
          showError("msg", err);
        }
      } else if (act === "publish" && token) {
        slot("msg").innerHTML = "";
        try {
          await send("POST", `/api/admin/editions/${eid}/draw/publish`, { token });
          toast("Published: the names are marked paired");
          location.hash = `#/admin/e/${eid}/pairings`;
        } catch (err) {
          showError("msg", err);
        }
      }
    } finally {
      if (btn.isConnected) btn.disabled = false;
    }
  });
}
