// The only place that talks to the server. Every call sends same-origin credentials; every mutation also sends
// X-Exchange: 1 and a JSON object body (the server's request guard insists on both, DELETE included; the browser
// adds the same-host Origin itself).
//
// Failures throw an ApiError with `status` and `error` (the server's message). A 403 with `locked` (this browser has
// no access to the exchange, or it was revoked by a password change) also dispatches a "locked" event on `events`:
// main.js answers it by showing the unlock screen. For a GET that screen takes over the view; for a save it opens
// over the page, so a form that was being filled in keeps its text.

export const events = new EventTarget();

export class ApiError extends Error {
  constructor(status, error, data = null) {
    super(error);
    this.name = "ApiError";
    this.status = status;
    this.error = error;
    this.data = data;
    this.locked = status === 403 && data?.locked === true;
  }
}

export const SIGNED_OUT = "This phone needs the password again. Your typing is still here: enter the password, then press Save again.";

async function request(method, path, body) {
  const headers = { Accept: "application/json" };
  const init = { method, headers, credentials: "same-origin", cache: "no-store" };
  if (method !== "GET") {
    headers["X-Exchange"] = "1";
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body ?? {});
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Can't reach the server. Check the phone's connection and try again.");
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (res.ok) {
    if (data === null) throw new ApiError(res.status, "Something went wrong. Reload the page.");
    return data;
  }
  if (res.status === 403 && data?.locked === true) {
    events.dispatchEvent(new CustomEvent("locked", { detail: { method, path } }));
    throw new ApiError(403, method === "GET" ? "This exchange needs its password." : SIGNED_OUT, data);
  }
  throw new ApiError(res.status, data?.error ?? `Something went wrong (${res.status}). Try again.`, data);
}

export const get = path => request("GET", path);
export const send = (method, path, body) => request(method, path, body);
