// Minimal IndexedDB wrapper for the offline queue and the offline read cache.
const DB_NAME = "hc-offline";
const DB_VERSION = 1;
let dbPromise = null;
let userId = null;

/** Offline data is partitioned by user: set on login, cleared on logout. */
export const setOfflineUserId = (id) => { userId = id == null ? null : Number(id); };
export const getOfflineUserId = () => userId;

export function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) return reject(new Error("IndexedDB unavailable"));
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("queue")) {
        const s = db.createObjectStore("queue", { keyPath: "op_id" });
        s.createIndex("created_at", "created_at");
      }
      if (!db.objectStoreNames.contains("cache")) {
        const c = db.createObjectStore("cache", { keyPath: "key" });
        c.createIndex("saved_at", "saved_at");
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  dbPromise.catch(() => { dbPromise = null; });
  return dbPromise;
}

const wrap = (req) => new Promise((resolve, reject) => {
  req.onsuccess = () => resolve(req.result);
  req.onerror = () => reject(req.error);
});

export async function idbGet(store, key) {
  const db = await openDb();
  return wrap(db.transaction(store).objectStore(store).get(key));
}

export async function idbPut(store, value) {
  const db = await openDb();
  return wrap(db.transaction(store, "readwrite").objectStore(store).put(value));
}

export async function idbDelete(store, key) {
  const db = await openDb();
  return wrap(db.transaction(store, "readwrite").objectStore(store).delete(key));
}

export async function idbAll(store) {
  const db = await openDb();
  return wrap(db.transaction(store).objectStore(store).getAll());
}

export async function idbClear(store) {
  const db = await openDb();
  return wrap(db.transaction(store, "readwrite").objectStore(store).clear());
}
