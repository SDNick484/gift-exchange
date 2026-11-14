// Entry point: hash routing and the shared header. Screens load on demand; each exports `render(ctx)` with
// ctx = { view, parts, query, alive, rerender }: `view` is a fresh element for this visit, `alive()` is false once the
// person has moved on, and `rerender()` draws the same route again.
import { ApiError, events, get } from "./api.js";
import { applyAccent, esc, parseHash } from "./core.js";

const SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/;
const ID = /^[0-9]{1,15}$/;

// The screen module for a route, or null when there is nothing at that address.
function pick(parts) {
  if (parts.length === 0) return () => import("./unlock.js");
  if (parts[0] === "x" && SLUG.test(parts[1] ?? "")) {
    if (parts.length === 2) return () => import("./home.js");
    if (parts.length === 4 && parts[2] === "p" && ID.test(parts[3])) return () => import("./person.js");
  }
  if (parts[0] === "admin") {
    if (parts.length === 4 && parts[1] === "e" && ID.test(parts[2]) && parts[3] === "pairings") return () => import("./admin-pairings.js");
    if (parts.length === 4 && parts[1] === "e" && ID.test(parts[2]) && parts[3] === "draw") return () => import("./admin-draw.js");
    if (parts.length === 1 || (parts.length === 3 && parts[1] === "x" && ID.test(parts[2]))) return () => import("./admin.js");
  }
  return null;
}

// The exchange a route belongs to (#/x/<slug>...), for the password box a locked one shows.
const slugOf = parts => (parts[0] === "x" && SLUG.test(parts[1] ?? "") ? parts[1] : null);

const host = document.getElementById("app");
const appName = document.getElementById("appName");
const adminLink = document.getElementById("adminLink");
let visit = 0;
let drawing = 0; // screens being drawn: a locked GET then shows the password box in place of the screen

const renderFailure = message => `<div class="notice error" role="alert"><p>${esc(message)}</p><p><button class="btn" type="button" data-act="retry">Try again</button></p></div>`;
const renderNotFound = () => `<div class="notice"><p>There's nothing at this address.</p><p><a class="btn" href="#/">Go to the start</a></p></div>`;

export function route() {
  const mine = ++visit;
  const { parts, query } = parseHash(location.hash);
  const view = document.createElement("div");
  view.className = "view";
  host.replaceChildren(view);
  applyAccent(null);
  window.scrollTo(0, 0);
  const ctx = { view, parts, query, alive: () => visit === mine && view.isConnected, rerender: route };
  view.addEventListener("click", e => {
    if (e.target.closest?.("[data-act]")?.dataset.act === "retry") route();
  });
  return draw(ctx);
}

async function draw(ctx) {
  const { view } = ctx;
  drawing++;
  try {
    const session = await get("/api/session");
    document.title = session.app_name;
    appName.textContent = session.app_name;
    adminLink.hidden = !session.admin;
    const load = pick(ctx.parts);
    if (!load) {
      view.innerHTML = renderNotFound();
      return;
    }
    const screen = await load();
    if (!ctx.alive()) return;
    await screen.render(ctx);
  } catch (e) {
    if (!ctx.alive()) return;
    if (e instanceof ApiError && e.locked) (await import("./unlock.js")).lockedView(ctx, slugOf(ctx.parts));
    else if (e instanceof ApiError && e.status === 404) view.innerHTML = renderNotFound();
    else view.innerHTML = renderFailure(e instanceof ApiError ? e.error : "Something went wrong. Reload the page.");
    if (!(e instanceof ApiError)) console.error(e);
  } finally {
    drawing--;
  }
}

// A save, or a Reload after one, that finds this phone signed out: ask for the password over the page, so the form
// and its typing stay put. The form shows the error and the person presses the button again.
events.addEventListener("locked", async () => {
  if (drawing) return; // draw() shows the password box in place of the screen
  const { askPassword } = await import("./unlock.js");
  askPassword();
});

window.addEventListener("hashchange", route);
route();
