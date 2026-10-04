// Interactive odontogram (permanent + primary) re-implemented from AeroDent's odontogram.js.
// Universal & FDI numbering viewed facing the patient: the patient's right is on the screen's start
// side (the chart is always laid out LTR, like a radiograph), upper 1 -> 16, lower 32 -> 17.
import {
  api, h, t, mount, icon, openDrawer, formatDateTime, loadingState, errorState, withBusy,
} from "../core/index.js";
import { conditionLabel, dentUrl, mutationError, savedNotice } from "./common.js";

const SHAPES = {
  incisor: "M9 4 Q20 -1 31 4 L30 22 Q30 30 20 30 Q10 30 10 22 Z M14 30 Q13 42 17 52 Q20 55 23 52 Q27 42 26 30 Z",
  canine: "M20 1 L30 20 Q31 30 20 32 Q9 30 10 20 Z M14 32 Q12 44 17 53 Q20 56 23 53 Q28 44 26 32 Z",
  premolar: "M9 8 Q9 1 20 1 Q31 1 31 8 L30 18 Q26 24 20 22 Q14 24 10 18 Z M13 30 Q10 40 14 50 Q17 55 20 52 Q23 55 26 50 Q30 40 27 30 Z",
  molar: "M6 8 Q6 0 20 0 Q34 0 34 8 L33 20 Q30 26 24 24 Q20 27 16 24 Q10 26 7 20 Z M10 30 Q7 40 10 50 Q13 55 17 50 Q18 40 18 30 Z M22 30 Q22 40 23 50 Q27 55 30 50 Q33 40 30 30 Z",
};

function shapeType(index, rowLength) {
  const distance = Math.abs(index - (rowLength / 2 - 0.5));
  if (rowLength >= 16) {
    if (distance < 2) return "incisor";
    if (distance < 3) return "canine";
    if (distance < 5) return "premolar";
    return "molar";
  }
  if (distance < 2) return "incisor";
  if (distance < 3) return "canine";
  return "molar";
}

function toothSvg(type, upper) {
  // Crowns face the occlusal plane: upper teeth are drawn with roots up.
  return h("svg:svg", { class: "dent-tooth-shape", viewBox: "0 0 40 56", "aria-hidden": "true" },
    h("svg:path", { d: SHAPES[type], transform: upper ? "matrix(1 0 0 -1 0 56)" : null }));
}

/**
 * renderOdontogram(panel, {patientId, clinicId, meta}) — chart + legend; click a tooth to edit.
 */
export function renderOdontogram(panel, { patientId, clinicId, meta }) {
  let mode = "permanent";
  let numbering = "universal"; // "universal" | "fdi"
  let teeth = new Map(); // "mode:number" -> tooth row
  let canEdit = false;
  const chartEl = h("div", { class: "dent-chart" });

  const modeBtns = meta.tooth_modes.map((m) => {
    const isAct = m === mode;
    return h("button", {
      type: "button", class: ["btn btn-sm", isAct && "is-active"], "aria-pressed": String(isAct),
      onClick: () => {
        mode = m;
        modeBtns.forEach((b, i) => {
          const act = meta.tooth_modes[i] === mode;
          b.setAttribute("aria-pressed", String(act));
          b.classList.toggle("is-active", act);
        });
        draw();
      },
    }, t(`dentistry.mode.${m}`));
  });

  const numBtns = [
    { key: "universal", label: t("dentistry.numbering.universal") },
    { key: "fdi", label: t("dentistry.numbering.fdi") },
  ].map((it) => {
    const isAct = it.key === numbering;
    return h("button", {
      type: "button", class: ["btn btn-sm", isAct && "is-active"], "aria-pressed": String(isAct),
      onClick: () => {
        numbering = it.key;
        numBtns.forEach((b, i) => {
          const act = (i === 0 ? "universal" : "fdi") === numbering;
          b.setAttribute("aria-pressed", String(act));
          b.classList.toggle("is-active", act);
        });
        draw();
      },
    }, it.label);
  });

  const legendConditions = ["healthy", "decay", "filling", "amalgam", "crown", "rct", "extract", "implant", "missing", "bridge", "fracture"];
  const legend = h("div", { class: "dent-legend" },
    legendConditions.map((c) =>
      h("span", { class: "dent-legend-item" }, h("i", { class: `dent-swatch dent-c-${c}` }), conditionLabel(c))));

  mount(panel,
    h("div", { class: "row row-between dent-chart-toolbar no-print" },
      h("div", { class: "row gap-2" },
        h("div", { class: "btn-group dent-segmented", role: "group", "aria-label": t("dentistry.chart.mode") }, modeBtns),
        h("div", { class: "btn-group dent-segmented", role: "group", "aria-label": t("dentistry.chart.numbering") }, numBtns)),
      h("span", { class: "text-sm text-muted" }, t("dentistry.chart.hint"))),
    chartEl, legend);

  async function load() {
    mount(chartEl, loadingState());
    try {
      const res = await api.get(dentUrl(`/patients/${patientId}/odontogram`), { query: { clinic_id: clinicId }, cache: true });
      teeth = new Map(res.teeth.map((x) => [`${x.tooth_mode}:${x.tooth_number}`, x]));
      canEdit = !!res.can_edit;
      draw();
    } catch (e) {
      mount(chartEl, errorState(e, load));
    }
  }

  function toothBtn(n, index, rowLength, upper) {
    const rec = teeth.get(`${mode}:${n}`);
    const cond = rec?.condition || "healthy";
    const univLabel = meta.numbering[mode].labels[n];
    const fdi = meta.numbering[mode].fdi[n];
    const primaryLabel = numbering === "fdi" ? fdi : univLabel;
    const secondaryLabel = numbering === "fdi" ? univLabel : fdi;
    const surfaces = rec?.surfaces?.length ? rec.surfaces.join("") : "";

    return h("button", {
      type: "button", class: ["dent-tooth", `dent-c-${cond}`, rec?.notes && "has-notes"],
      title: `${t("dentistry.tooth")} ${univLabel} (FDI ${fdi}) — ${conditionLabel(rec?.condition)}${rec?.notes ? ` — ${rec.notes}` : ""}`,
      "aria-label": `${t("dentistry.tooth")} ${primaryLabel}: ${conditionLabel(rec?.condition)}`,
      onClick: () => openTooth(n),
    },
    upper ? h("div", { class: "dent-tooth-label ltr" }, primaryLabel) : null,
    h("span", { class: "dent-tooth-visual" },
      toothSvg(shapeType(index, rowLength), upper),
      h("span", { class: "dent-tooth-mark" })),
    surfaces ? h("span", { class: "dent-tooth-surf ltr" }, surfaces) : null,
    upper ? null : h("div", { class: "dent-tooth-label ltr" }, primaryLabel));
  }

  function arch(numbers, upper) {
    const half = numbers.length / 2;
    const quad = (slice, offset) => h("div", { class: "dent-quadrant" },
      slice.map((n, i) => toothBtn(n, i + offset, numbers.length, upper)));
    return h("div", { class: "dent-arch-row" }, quad(numbers.slice(0, half), 0), quad(numbers.slice(half), half));
  }

  function draw() {
    const num = meta.numbering[mode];
    mount(chartEl,
      h("div", { class: ["dent-chart-inner", mode === "primary" && "is-primary"], dir: "ltr" },
        h("div", { class: "dent-sides" }, h("span", t("dentistry.chart.right")), h("span", t("dentistry.chart.left"))),
        h("div", { class: "dent-arch-title" }, t("dentistry.chart.maxillary")),
        arch(num.upper, true),
        h("div", { class: "dent-occlusal" }),
        arch(num.lower, false),
        h("div", { class: "dent-arch-title" }, t("dentistry.chart.mandibular"))));
  }

  function openTooth(n) {
    const key = `${mode}:${n}`;
    const toothMode = mode;
    const rec = teeth.get(key);
    const label = meta.numbering[toothMode].labels[n];
    const fdi = meta.numbering[toothMode].fdi[n];

    let currentCond = rec?.condition || "healthy";

    const procedure = h("input", {
      class: "input",
      maxlength: 150,
      value: rec?.procedure || "",
      placeholder: t("dentistry.field.procedure"),
      disabled: !canEdit,
    });
    procedure.dataset.auto = rec?.procedure ? "false" : "true";
    procedure.addEventListener("input", () => {
      procedure.dataset.auto = "false";
    });

    const notes = h("textarea", {
      class: "textarea",
      rows: 2,
      maxlength: 5000,
      placeholder: t("dentistry.field.notes"),
      disabled: !canEdit,
    });
    notes.value = rec?.notes || "";

    const condSel = h("select", { class: "select", disabled: !canEdit },
      meta.conditions.map((c) => h("option", { value: c }, conditionLabel(c))));
    condSel.value = currentCond;

    const surf = meta.surfaces.map((s) => {
      const inp = h("input", {
        type: "checkbox",
        value: s,
        checked: (rec?.surfaces || []).includes(s),
        disabled: !canEdit,
      });
      return h("label", { class: "check dent-surface" }, inp, h("span", { title: t(`dentistry.surface.${s}`) }, s));
    });

    const history = h("div", { class: "dent-history" }, loadingState());

    const selectedSurfaces = () => surf.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value);

    let drawer = null;

    async function save(body, btn) {
      const cur = teeth.get(key);
      const payload = { clinic_id: clinicId, ...body, version: cur ? cur.version : 0 };
      const run = async () => {
        try {
          const res = await api.put(dentUrl(`/patients/${patientId}/odontogram/${toothMode}/${n}`), payload,
            { offline: true, label: `${t("dentistry.tooth")} ${label}` });
          savedNotice(res);
          if (!res?.queued) {
            teeth.set(key, res);
            draw();
          }
          drawer?.close();
        } catch (e) {
          mutationError(e, () => { drawer?.close(); load(); });
        }
      };
      return btn ? withBusy(btn, run) : run();
    }

    const saveCurrent = (btn) => {
      const cond = condSel.value;
      const sfc = selectedSurfaces();
      const payload = cond === "clear"
        ? { condition: "clear" }
        : {
            condition: cond,
            procedure: procedure.value.trim() || conditionLabel(cond),
            surfaces: sfc.length ? sfc : (rec?.surfaces || []),
            notes: notes.value.trim() || null,
          };
      return save(payload, btn);
    };

    const actionBtns = new Map();
    const saveBtnLabel = h("span", ` ${t("dentistry.save_tooth")} (${conditionLabel(currentCond)})`);

    function syncCondition(cond, autoProcedure = true) {
      currentCond = cond;
      condSel.value = cond;
      actionBtns.forEach((btn, c) => {
        btn.classList.toggle("is-active", c === cond);
      });
      if (autoProcedure && (!procedure.value || procedure.dataset.auto === "true")) {
        procedure.value = (cond === "healthy" || cond === "clear") ? "" : conditionLabel(cond);
        procedure.dataset.auto = "true";
      }
      if (saveBtnLabel) {
        saveBtnLabel.textContent = ` ${t("dentistry.save_tooth")} (${conditionLabel(cond)})`;
      }
    }

    condSel.addEventListener("change", (e) => {
      syncCondition(e.target.value, true);
    });

    const applyBtn = canEdit ? h("button", {
      type: "button",
      class: "btn btn-primary dent-cond-apply",
      onClick: () => saveCurrent(applyBtn),
      title: t("dentistry.apply"),
    }, icon("check"), h("span", t("dentistry.apply"))) : null;

    const quickList = meta.conditions?.length ? meta.conditions : [
      "decay", "filling", "amalgam", "crown", "rct", "extract",
      "implant", "missing", "bridge", "veneer", "fracture", "sealant", "healthy"
    ];

    const quick = canEdit ? h("div", { class: "dent-actions" }, quickList.map((a) => {
      const b = h("button", {
        type: "button",
        class: ["btn btn-sm", `dent-action dent-c-${a}`, currentCond === a && "is-active"],
        onClick: () => {
          syncCondition(a, true);
          const sfc = selectedSurfaces();
          const payload = a === "clear"
            ? { condition: "clear" }
            : {
                condition: a,
                procedure: procedure.value.trim() || conditionLabel(a),
                surfaces: sfc.length ? sfc : (rec?.surfaces || []),
                notes: notes.value.trim() || null,
              };
          save(payload, b);
        },
      }, h("span", { class: `dent-swatch dent-c-${a}` }), conditionLabel(a));
      actionBtns.set(a, b);
      return b;
    })) : h("p", { class: "text-muted" }, t("dentistry.read_only"));

    const cancelBtn = h("button", {
      type: "button",
      class: "btn btn-outline",
      onClick: () => drawer?.close(),
    }, t("core.cancel"));

    const clearBtn = canEdit && rec && rec.condition !== "healthy" ? h("button", {
      type: "button",
      class: "btn btn-ghost text-danger",
      onClick: () => save({ condition: "clear" }, clearBtn),
    }, icon("trash"), t("dentistry.condition.clear")) : null;

    const saveBtn = canEdit ? h("button", {
      type: "button",
      class: "btn btn-primary",
      onClick: () => saveCurrent(saveBtn),
    }, icon("save"), saveBtnLabel) : null;

    drawer = openDrawer({
      title: `${t("dentistry.tooth")} ${label} · FDI ${fdi}`,
      body: h("div", { class: "stack" },
        h("div", { class: "text-sm text-muted" }, t(`dentistry.mode.${toothMode}`),
          rec ? ` · ${t("dentistry.updated_by", { name: rec.updated_by || "", date: formatDateTime(rec.updated_at) })}` : ""),
        h("div", { class: "field" },
          h("label", t("dentistry.field.condition")),
          h("div", { class: "dent-cond-row" }, condSel, applyBtn)),
        h("div", { class: "field" },
          h("label", t("dentistry.quick_conditions")),
          quick),
        h("div", { class: "form" },
          h("div", { class: "field" }, h("label", t("dentistry.field.surfaces")),
            h("div", { class: "row dent-surfaces" }, surf), h("div", { class: "field-help" }, t("dentistry.surfaces_help"))),
          h("div", { class: "field" }, h("label", t("dentistry.field.procedure")), procedure),
          h("div", { class: "field" }, h("label", t("dentistry.field.notes")), notes)),
        h("h3", { class: "dent-subtitle" }, t("dentistry.history")),
        history),
      footer: canEdit ? [clearBtn, cancelBtn, saveBtn].filter(Boolean) : [cancelBtn],
    });

    api.get(dentUrl(`/patients/${patientId}/odontogram/history`),
      { query: { clinic_id: clinicId, mode: toothMode, tooth_number: n } })
      .then((res) => mount(history, res.items.length ? h("ol", { class: "dent-history-list" }, res.items.map((e) =>
        h("li", h("div", { class: "row row-between" },
          h("strong", e.action === "clear" ? t("dentistry.condition.clear") : conditionLabel(e.condition)),
          h("span", { class: "text-xs text-muted" }, formatDateTime(e.created_at))),
        e.procedure ? h("div", { class: "text-sm" }, e.procedure) : null,
        e.surfaces?.length ? h("div", { class: "text-sm" }, t("dentistry.field.surfaces"), ": ", e.surfaces.join(" ")) : null,
        e.notes ? h("div", { class: "text-sm text-muted" }, e.notes) : null,
        h("div", { class: "text-xs text-muted" }, e.author_name)))) : h("p", { class: "text-muted" }, t("dentistry.history_empty"))))
      .catch((e) => mount(history, errorState(e)));
  }

  load();
  return { reload: load };
}
