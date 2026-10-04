// USB barcode/QR scanners act as keyboards: a fast burst of characters ending with Enter (spec §59).
/**
 * listenBarcode(onCode, {minLength: 4, maxGapMs: 40, target: document, allowInInputs: true}) -> stop()
 * When a scan ends inside an input, the scanned characters are removed from that input and the
 * Enter is suppressed (so it doesn't submit forms), unless the input has data-barcode="keep".
 */
export function listenBarcode(onCode, { minLength = 4, maxGapMs = 40, target = document, allowInInputs = true } = {}) {
  let buf = "";
  let last = 0;
  let startEl = null;
  const handler = (e) => {
    const now = performance.now();
    if (now - last > maxGapMs) {
      buf = "";
      startEl = e.target;
    }
    last = now;
    if (e.key === "Enter") {
      if (buf.length >= minLength) {
        const el = e.target;
        const inInput = el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
        if (inInput && !allowInInputs) {
          buf = "";
          return;
        }
        e.preventDefault();
        e.stopPropagation();
        if (inInput && el === startEl && el.dataset.barcode !== "keep" && typeof el.value === "string" && el.value.endsWith(buf)) {
          el.value = el.value.slice(0, -buf.length);
        }
        const code = buf;
        buf = "";
        onCode(code, e);
      }
      buf = "";
      return;
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) buf += e.key;
  };
  target.addEventListener("keydown", handler, true);
  return () => target.removeEventListener("keydown", handler, true);
}
