// Offline mutation queue (spec §74). Ops: {op_id, user_id, method, url, body, label, created_at,
// status: "pending" | "issue", attempts, error}. Replayed in creation order with X-Op-Id (the server
// stores responses per op id, so retries never duplicate records). 409/422/403/404 -> "issue" (needs review).
import { idbAll, idbDelete, idbGet, idbPut, getOfflineUserId } from "./idb.js";
import { setCounts, setSyncing, setNetwork } from "./status.js";
import { emit, onEvent } from "../core/events.js";
import { send, parseBody, toApiError, refreshCsrf } from "../core/api.js";

const REPLAY_INTERVAL_MS = 30000;
let running = false;
let started = false;

async function myOps() {
  const uid = getOfflineUserId();
  if (uid == null) return [];
  try {
    return (await idbAll("queue")).filter((o) => o.user_id === uid).sort((a, b) => a.created_at - b.created_at);
  } catch {
    return [];
  }
}

export async function refreshCounts() {
  const ops = await myOps();
  setCounts({ pending: ops.filter((o) => o.status === "pending").length, issues: ops.filter((o) => o.status === "issue").length });
  return ops;
}

export async function enqueue({ op_id, method, url, body, label }) {
  const op = { op_id, user_id: getOfflineUserId(), method, url, body, label, created_at: Date.now(), status: "pending",
    attempts: 0, error: null };
  await idbPut("queue", op);
  await refreshCounts();
  emit("sync:queued", { op });
  return op;
}

/** All ops of the current user (pending + issues), oldest first. */
export const listOps = () => myOps();

export async function discardOp(opId) {
  await idbDelete("queue", opId);
  await refreshCounts();
}

export async function retryOp(opId) {
  const op = await idbGet("queue", opId);
  if (!op) return;
  op.status = "pending";
  op.error = null;
  await idbPut("queue", op);
  await refreshCounts();
  return replay();
}

/** Send queued ops in order. Stops at the first network/5xx/401 failure (keeps order). */
export async function replay() {
  if (running || getOfflineUserId() == null) return;
  const pending = (await myOps()).filter((o) => o.status === "pending");
  if (!pending.length) return;
  running = true;
  setSyncing(true);
  let applied = 0;
  try {
    for (const op of pending) {
      const outcome = await sendOp(op);
      if (outcome === "stop") break;
      if (outcome === "applied") applied += 1;
    }
  } finally {
    running = false;
    await refreshCounts();
    setSyncing(false, { applied });
  }
}

async function sendOp(op, csrfRetried = false) {
  let res;
  try {
    res = await send(op.method, op.url, { body: op.body ?? undefined, opId: op.op_id });
  } catch {
    setNetwork(false);
    return "stop"; // still offline
  }
  setNetwork(true);
  const data = await parseBody(res);
  if (res.ok) {
    await idbDelete("queue", op.op_id);
    emit("sync:applied", { op, data });
    return "applied";
  }
  const err = toApiError(res.status, data);
  if (res.status === 401) {
    emit("auth:lost", { code: err.code, message: err.message });
    return "stop";
  }
  if (res.status === 403 && err.code === "csrf_token" && !csrfRetried && (await refreshCsrf())) {
    return sendOp(op, true);
  }
  if (res.status >= 500 || res.status === 429 || (res.status === 409 && err.code === "op_in_progress")) {
    op.attempts += 1;
    await idbPut("queue", op);
    return "stop"; // transient: retry later, keep order
  }
  op.status = "issue";
  op.attempts += 1;
  op.error = { status: err.status, code: err.code, message: err.message, details: err.details };
  await idbPut("queue", op);
  emit("sync:issue", { op });
  return "issue";
}

/** Start automatic replay: on reconnect, periodically, and once now. Idempotent. */
export function startSync() {
  if (started) {
    refreshCounts().then(replay);
    return;
  }
  started = true;
  window.addEventListener("online", () => replay());
  onEvent("net:restored", () => replay());
  setInterval(() => replay(), REPLAY_INTERVAL_MS);
  refreshCounts().then(replay);
}
