// Offline READ cache: last payloads of GETs requested with {cache: true}.
// Used ONLY when the network is unavailable; the UI must label such data (see components/states.js
// offlineCopyBanner). Never authoritative. Partitioned per user; cleared on logout.
import { idbAll, idbDelete, idbGet, idbPut, getOfflineUserId, idbClear } from "./idb.js";

const MAX_ENTRIES = 300;
let writes = 0;

const keyFor = (url) => `${getOfflineUserId() ?? "anon"}|${url}`;

export async function cachePut(url, data) {
  if (getOfflineUserId() == null) return;
  try {
    await idbPut("cache", { key: keyFor(url), user_id: getOfflineUserId(), url, data, saved_at: Date.now() });
    if (++writes % 25 === 0) await prune();
  } catch (e) {
    console.warn("offline cache write failed", e);
  }
}

export async function cacheGet(url) {
  if (getOfflineUserId() == null) return null;
  try {
    return (await idbGet("cache", keyFor(url))) || null;
  } catch {
    return null;
  }
}

async function prune() {
  const all = await idbAll("cache");
  if (all.length <= MAX_ENTRIES) return;
  all.sort((a, b) => a.saved_at - b.saved_at);
  for (const e of all.slice(0, all.length - MAX_ENTRIES)) await idbDelete("cache", e.key);
}

/** Remove cached payloads of every user except `keepUserId` (null = remove all). */
export async function clearCache(keepUserId = null) {
  try {
    if (keepUserId == null) return await idbClear("cache");
    for (const e of await idbAll("cache")) if (e.user_id !== keepUserId) await idbDelete("cache", e.key);
  } catch (e) {
    console.warn("offline cache clear failed", e);
  }
}
