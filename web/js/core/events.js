// Tiny app-wide event bus.
// Core events: 'auth:lost' {code,message}, 'auth:changed', 'lang:changed' {lang},
// 'route:changed' {route,params}, 'sync:status' {state,pending,issues}, 'sync:applied' {op,data},
// 'notifications:changed'.
const handlers = new Map();

export function onEvent(name, fn) {
  if (!handlers.has(name)) handlers.set(name, new Set());
  handlers.get(name).add(fn);
  return () => handlers.get(name)?.delete(fn);
}

export function emit(name, detail) {
  for (const fn of [...(handlers.get(name) || [])]) {
    try {
      fn(detail);
    } catch (e) {
      console.error(`event handler for ${name} failed`, e);
    }
  }
}
