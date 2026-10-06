// USB barcode/QR scanners act as keyboards: a fast burst of characters ending with Enter (spec §59).
// Also provides Code 128 barcode SVG rendering and printable patient card.
import { h } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { formatDate, ageFrom } from "../core/format.js";
import { getCenter } from "../core/state.js";
import { openModal } from "./modal.js";
import { printElement } from "./print.js";
import { icon } from "./icons.js";

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

// Code 128 Symbol Patterns (alternating bar/space module widths)
const C128_PATTERNS = [
  "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
  "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
  "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
  "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
  "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
  "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
  "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
  "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
  "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
  "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
  "114131", "311141", "411131", "211412", "211214", "211232", "2331112"
];

/**
 * Render a Code 128 (Subset B) barcode as an SVG DOM node.
 * @param {string} text The text/code to encode.
 * @param {object} options
 * @param {number} options.height Barcode bar height in px (default: 45)
 * @param {boolean} options.showText Whether to render human-readable text below bars (default: true)
 * @param {string} options.className CSS class for the SVG element
 * @returns {SVGSVGElement}
 */
export function renderBarcodeSVG(text, { height = 45, showText = true, className = "barcode-svg" } = {}) {
  const str = String(text || "").trim();
  if (!str) return document.createElementNS("http://www.w3.org/2000/svg", "svg");

  const values = [];
  for (let i = 0; i < str.length; i++) {
    const code = str.charCodeAt(i);
    // ASCII 32 to 126 map to symbol values 0 to 94 in Code B
    if (code >= 32 && code <= 126) values.push(code - 32);
    else values.push(0); // fallback space
  }

  // Checksum calculation for Code 128 B: start symbol 104
  let checksum = 104;
  for (let i = 0; i < values.length; i++) {
    checksum += (i + 1) * values[i];
  }
  checksum = checksum % 103;

  const symbols = [104, ...values, checksum, 106];

  // Build bars
  const quietZone = 10;
  let curX = quietZone;
  const barElements = [];

  for (let sIdx = 0; sIdx < symbols.length; sIdx++) {
    const sym = symbols[sIdx];
    const pattern = C128_PATTERNS[sym] || "212222";
    for (let pIdx = 0; pIdx < pattern.length; pIdx++) {
      const width = parseInt(pattern[pIdx], 10);
      const isBar = pIdx % 2 === 0;
      if (isBar) {
        barElements.push(
          `<rect x="${curX}" y="0" width="${width}" height="${height}" fill="currentColor" />`
        );
      }
      curX += width;
    }
  }

  const totalWidth = curX + quietZone;
  const totalHeight = showText ? height + 16 : height;

  const textElement = showText
    ? `<text x="${totalWidth / 2}" y="${height + 13}" font-family="monospace, monospace" font-size="11" text-anchor="middle" fill="currentColor" letter-spacing="1">${escapeXml(str)}</text>`
    : "";

  const svgStr = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${totalWidth} ${totalHeight}" width="${totalWidth}" height="${totalHeight}" class="${className}" style="display:inline-block;max-width:100%;height:auto;">
      ${barElements.join("")}
      ${textElement}
    </svg>
  `;

  const container = document.createElement("div");
  container.innerHTML = svgStr.trim();
  return container.firstElementChild;
}

function escapeXml(unsafe) {
  return unsafe.replace(/[<>&'"]/g, (c) => {
    switch (c) {
      case "<": return "&lt;";
      case ">": return "&gt;";
      case "&": return "&amp;";
      case "'": return "&apos;";
      case '"': return "&quot;";
    }
  });
}

/**
 * Open a modal displaying a standard printable Patient ID Card (CR80 format 85.6mm x 54mm)
 * with center branding, patient details, and scannable Code 128 barcode.
 */
export function openPatientCard(patient) {
  const center = getCenter() || {};
  const code = patient.display_code || `PAT-${String(patient.id).padStart(6, "0")}`;
  const barcode = renderBarcodeSVG(code, { height: 38, showText: false });

  const age = patient.date_of_birth ? ageFrom(patient.date_of_birth) : null;
  const gender = patient.gender ? t(`patients.gender.${patient.gender}`) : "";

  const cardNode = h("div", { class: "patient-id-card", id: "patient-card-printable" },
    h("div", { class: "id-card-header" },
      h("div", { class: "id-card-center" },
        h("div", { class: "id-card-logo" }, icon("activity")),
        h("div", null,
          h("strong", { class: "id-card-center-name" }, center.name || t("patients.health_center")),
          center.phone ? h("div", { class: "id-card-center-sub text-muted text-xs ltr" }, center.phone) : null)),
      h("div", { class: "id-card-badge" }, t("patients.id_card_title", { default: "PATIENT CARD" }))),
    
    h("div", { class: "id-card-body" },
      h("div", { class: "id-card-info" },
        h("h3", { class: "id-card-name" }, patient.full_name),
        h("div", { class: "id-card-meta-grid" },
          h("div", { class: "id-card-field" },
            h("span", { class: "id-card-lbl" }, t("patients.field.code")),
            h("span", { class: "id-card-val ltr" }, code)),
          h("div", { class: "id-card-field" },
            h("span", { class: "id-card-lbl" }, t("patients.field.gender")),
            h("span", { class: "id-card-val" }, gender || "—")),
          patient.date_of_birth ? h("div", { class: "id-card-field" },
            h("span", { class: "id-card-lbl" }, t("patients.field.date_of_birth")),
            h("span", { class: "id-card-val" }, `${formatDate(patient.date_of_birth, { year: "always" })} (${age ?? "-"})`)) : null,
          patient.blood_type ? h("div", { class: "id-card-field" },
            h("span", { class: "id-card-lbl" }, t("patients.field.blood_type")),
            h("span", { class: "id-card-val ltr highlight" }, patient.blood_type)) : null,
          patient.phone ? h("div", { class: "id-card-field span-2" },
            h("span", { class: "id-card-lbl" }, t("patients.field.phone")),
            h("span", { class: "id-card-val ltr" }, patient.phone)) : null))),
    
    h("div", { class: "id-card-barcode-wrap" },
      barcode,
      h("span", { class: "id-card-code-text ltr" }, code))
  );

  const printBtn = h("button", {
    class: "btn btn-primary",
    type: "button",
    onClick: () => {
      document.body.classList.add("printing-card");
      printElement(cardNode);
      const clean = () => {
        document.body.classList.remove("printing-card");
        window.removeEventListener("afterprint", clean);
      };
      window.addEventListener("afterprint", clean);
    }
  }, icon("printer"), t("core.print"));

  openModal({
    title: t("patients.id_card_modal_title", { default: "Patient ID Card" }),
    size: "md",
    body: [
      h("div", { class: "id-card-preview-wrap" }, cardNode),
      h("div", { class: "text-muted text-xs text-center mt-sm" }, t("patients.id_card_hint", { default: "Standard wallet size (85.6mm × 54mm) - Scannable by all barcode scanners." }))
    ],
    actions: [
      { label: t("core.close"), variant: "ghost" },
      { label: t("core.print"), variant: "primary", onClick: () => printBtn.click() }
    ]
  });
}
