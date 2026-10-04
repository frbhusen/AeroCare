// API client: same-origin fetch, JSON, CSRF header, normalized ApiError, 401 handling,
// offline queue for mutations ({offline: true}) and offline read cache for GETs ({cache: true}).
import { emit } from "./events.js";
import { getCsrf, setCsrf } from "./state.js";
import { t, hasKey } from "./i18n.js";
import { enqueue } from "../offline/queue.js";
import { cacheGet, cachePut } from "../offline/cache.js";
import { setNetwork } from "../offline/status.js";

export const BASE = "/api/v1";
const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const cachedMarks = new WeakMap();

/** Normalized API error. status 0 = network failure. */
export class ApiError extends Error {
  constructor({ status = 0, code = "error", message = "", details = null, serverMessage = "" } = {}) {
    super(message || code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.serverMessage = serverMessage;
  }
  get isNetwork() { return this.status === 0; }
  get isValidation() { return this.status === 422 && this.code === "validation_error"; }
  get isConflict() { return this.status === 409; }
}

export function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const hx = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${hx.slice(0, 8)}-${hx.slice(8, 12)}-${hx.slice(12, 16)}-${hx.slice(16, 20)}-${hx.slice(20)}`;
}

/** "/patients" -> "/api/v1/patients?..." (absolute "/api/..." kept). Null/empty query values are skipped. */
export function apiUrl(url, query) {
  let u = url.startsWith("/api/") ? url : BASE + (url.startsWith("/") ? url : `/${url}`);
  if (query) {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v == null || v === "") continue;
      if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
      else sp.append(k, String(v));
    }
    const qs = sp.toString();
    if (qs) u += (u.includes("?") ? "&" : "?") + qs;
  }
  return u;
}

function localizedMessage(code, serverMessage, status) {
  if (hasKey(`core.error.${code}`)) return t(`core.error.${code}`);
  if (serverMessage) return serverMessage;
  return t(status >= 500 ? "core.error.server_error" : "core.error.generic");
}

export function toApiError(status, data) {
  const e = (data && data.error) || {};
  const code = e.code || (status >= 500 ? "server_error" : "error");
  return new ApiError({ status, code, details: e.details || null, serverMessage: e.message || "",
    message: localizedMessage(code, e.message, status) });
}

/** Low-level send (used by the client and by the offline replayer). Throws TypeError on network failure. */
export function send(method, url, { body, headers = {}, opId, signal } = {}) {
  const h = { Accept: "application/json", ...headers };
  const init = { method, credentials: "same-origin", headers: h, signal, cache: "no-store" };
  if (MUTATING.has(method)) {
    const csrf = getCsrf();
    if (csrf) h["X-CSRF-Token"] = csrf;
    if (opId) h["X-Op-Id"] = opId;
  }
  if (body !== undefined) {
    if (body instanceof FormData) init.body = body;
    else {
      h["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
  }
  return fetch(url, init);
}

export async function parseBody(res) {
  if (res.status === 204) return null;
  const ct = res.headers.get("Content-Type") || "";
  if (!ct.includes("json")) return null;
  try {
    return await res.json();
  } catch {
    return null;
  }
}

/** Re-read /auth/me to refresh the CSRF token (e.g. after a re-login in another tab). */
export async function refreshCsrf() {
  try {
    const res = await send("GET", apiUrl("/auth/me"));
    if (!res.ok) return false;
    const me = await parseBody(res);
    setCsrf(me?.csrf_token);
    return !!me?.csrf_token;
  } catch {
    return false;
  }
}

/**
 * request(method, url, opts) -> parsed JSON
 * opts: query, body, headers, signal,
 *       offline: true  -> mutation is queued in IndexedDB on network failure; resolves {queued: true, op_id}
 *       opId           -> explicit X-Op-Id (default: generated for offline mutations)
 *       cache: true    -> GET payload saved for offline reading; on network failure the saved copy is
 *                         returned and cachedAt(result) gives its timestamp (label it in the UI!)
 *       silent401: true -> do not broadcast auth:lost
 *       raw: true      -> return the Response
 */
export async function request(method, url, opts = {}) {
  method = method.toUpperCase();
  const full = apiUrl(url, opts.query);
  const mutating = MUTATING.has(method);
  const opId = mutating && (opts.opId || (opts.offline ? uuid() : null));
  let res;
  try {
    res = await send(method, full, { body: opts.body, headers: opts.headers, opId, signal: opts.signal });
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    setNetwork(false);
    if (mutating && opts.offline) {
      await enqueue({ op_id: opId, method, url: full, body: opts.body ?? null, label: opts.label || null });
      return { queued: true, op_id: opId };
    }
    if (method === "GET" && opts.cache) {
      const hit = await cacheGet(full);
      if (hit) {
        const data = hit.data;
        if (data && typeof data === "object") cachedMarks.set(data, hit.saved_at);
        return data;
      }
    }
    throw new ApiError({ status: 0, code: "network_error", message: t("core.error.network_error") });
  }
  setNetwork(true);
  if (opts.raw) return res;
  const data = await parseBody(res);
  if (!res.ok) {
    const e = toApiError(res.status, data);
    if (res.status === 403 && e.code === "csrf_token" && !opts._csrfRetried && (await refreshCsrf())) {
      return request(method, url, { ...opts, opId: opId || undefined, _csrfRetried: true });
    }
    if (res.status === 401 && !opts.silent401) emit("auth:lost", { code: e.code, message: e.message });
    throw e;
  }
  if (method === "GET" && opts.cache && data != null) cachePut(full, data);
  return data;
}

/** When a GET result came from the offline read cache: its saved timestamp (ms); else null. */
export const cachedAt = (obj) => (obj && typeof obj === "object" ? cachedMarks.get(obj) ?? null : null);

export const api = {
  get: (url, opts) => request("GET", url, opts),
  post: (url, body, opts) => request("POST", url, { ...opts, body }),
  put: (url, body, opts) => request("PUT", url, { ...opts, body }),
  patch: (url, body, opts) => request("PATCH", url, { ...opts, body }),
  del: (url, opts) => request("DELETE", url, opts),
};

/**
 * Multipart upload with progress (XHR). formData: FormData. onProgress(fraction 0..1).
 * Resolves parsed JSON; rejects ApiError. Not queued offline (files are too large for the queue).
 */
export function upload(url, formData, { onProgress, signal, method = "POST" } = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, apiUrl(url));
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    const csrf = getCsrf();
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
    if (onProgress) xhr.upload.addEventListener("progress", (e) => e.lengthComputable && onProgress(e.loaded / e.total));
    xhr.addEventListener("load", () => {
      setNetwork(true);
      let data = null;
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch { /* non-JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
      const e = toApiError(xhr.status, data);
      if (xhr.status === 401) emit("auth:lost", { code: e.code, message: e.message });
      reject(e);
    });
    xhr.addEventListener("error", () => {
      setNetwork(false);
      reject(new ApiError({ status: 0, code: "network_error", message: t("core.error.network_error") }));
    });
    xhr.addEventListener("abort", () => reject(new ApiError({ status: 0, code: "aborted", message: t("core.error.aborted") })));
    if (signal) signal.addEventListener("abort", () => xhr.abort());
    xhr.send(formData);
  });
}
