// Connectivity + sync status (spec §75):
//   online | offline ("Offline — changes saved locally") | syncing | synced | issue ("Sync issue — requires attention")
import { emit } from "../core/events.js";

const s = { online: navigator.onLine !== false, pending: 0, issues: 0, syncing: false, justSynced: false };
let syncedTimer = null;

export function displayState() {
  if (s.issues > 0) return "issue";
  if (!s.online) return "offline";
  if (s.syncing) return "syncing";
  if (s.justSynced) return "synced";
  return "online";
}

export const getSyncStatus = () => ({ ...s, state: displayState() });

function publish() {
  emit("sync:status", getSyncStatus());
}

/** Called by the API client after every request: true = server reachable. */
export function setNetwork(ok) {
  if (s.online === ok) return;
  s.online = ok;
  publish();
  if (ok) emit("net:restored");
}

export function setCounts({ pending, issues }) {
  if (pending != null) s.pending = pending;
  if (issues != null) s.issues = issues;
  publish();
}

export function setSyncing(on, { applied = 0 } = {}) {
  s.syncing = on;
  if (!on && applied > 0) {
    s.justSynced = true;
    clearTimeout(syncedTimer);
    syncedTimer = setTimeout(() => {
      s.justSynced = false;
      publish();
    }, 5000);
  }
  publish();
}

window.addEventListener("online", () => setNetwork(true));
window.addEventListener("offline", () => setNetwork(false));
