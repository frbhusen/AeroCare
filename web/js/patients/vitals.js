// Vital Signs Flowsheet & Trending (BP, Pulse, Temp, Weight, BMI)
import { api, h, t, mount, icon, can, toast, toastSuccess, toastApiError, createForm, openModal, formatDateTime, loadingState, errorState } from "../core/index.js";

export function calcBmi(weight, height) {
  if (!weight || !height || height <= 0) return null;
  const hM = height / 100;
  return Math.round((weight / (hM * hM)) * 10) / 10;
}

export function bmiCategory(bmi) {
  if (bmi == null) return null;
  if (bmi < 18.5) return { key: "underweight", label: t("patients.vitals.bmi_underweight", { default: "Underweight" }), cls: "badge-warning" };
  if (bmi < 25.0) return { key: "normal", label: t("patients.vitals.bmi_normal", { default: "Normal" }), cls: "badge-success" };
  if (bmi < 30.0) return { key: "overweight", label: t("patients.vitals.bmi_overweight", { default: "Overweight" }), cls: "badge-warning" };
  return { key: "obese", label: t("patients.vitals.bmi_obese", { default: "Obese" }), cls: "badge-danger" };
}

export function bpCategory(sys, dia) {
  if (!sys || !dia) return null;
  if (sys < 120 && dia < 80) return { label: t("patients.vitals.bp_normal", { default: "Normal" }), cls: "badge-success" };
  if (sys <= 129 && dia < 80) return { label: t("patients.vitals.bp_elevated", { default: "Elevated" }), cls: "badge-warning" };
  if (sys <= 139 || dia <= 89) return { label: t("patients.vitals.bp_stage1", { default: "Stage 1 HTN" }), cls: "badge-warning" };
  return { label: t("patients.vitals.bp_stage2", { default: "Stage 2 HTN" }), cls: "badge-danger" };
}

/**
 * Overview Vitals card
 */
export function vitalsCard({ ctx, patient, onUpdated }) {
  const root = h("section", { class: "card vitals-card" }, loadingState());

  async function load() {
    try {
      const data = await api.get(`/patients/${patient.id}/vitals`);
      render(data);
    } catch (err) {
      mount(root, errorState(err, load));
    }
  }

  function render(data) {
    const lat = data.latest;
    const canCreate = can("medical_records.create");

    const header = h("div", { class: "card-header row-between" },
      h("div", { class: "row gap-sm items-center" }, icon("activity"), h("h2", t("patients.vitals.title", { default: "Vital Signs & Biometrics" }))),
      h("div", { class: "row gap-xs" },
        data.items?.length ? h("button", { class: "btn btn-sm", type: "button", onClick: () => openVitalsHistoryModal({ ctx, patient, vitalsData: data, onUpdated: load }) },
          icon("chart"), t("patients.vitals.flowsheet", { default: "History & Trends" })) : null,
        canCreate ? h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: () => openRecordVitalsModal({ ctx, patient, onSaved: () => { load(); onUpdated?.(); } }) },
          icon("plus"), t("patients.vitals.record", { default: "Record Vitals" })) : null
      )
    );

    if (!lat) {
      mount(root, header, h("div", { class: "card-body text-center muted py-lg" },
        pNull("No vitals recorded yet for this patient.")
      ));
      return;
    }

    const bpCat = bpCategory(lat.bp_systolic, lat.bp_diastolic);
    const bmiCat = bmiCategory(lat.bmi);

    const grid = h("div", { class: "vitals-grid" },
      // BP
      vitalsTile(t("patients.vitals.bp", { default: "Blood Pressure" }),
        lat.bp_systolic && lat.bp_diastolic ? `${lat.bp_systolic} / ${lat.bp_diastolic}` : "—",
        "mmHg", bpCat ? h("span", { class: `badge ${bpCat.cls}` }, bpCat.label) : null),
      // Heart Rate
      vitalsTile(t("patients.vitals.hr", { default: "Heart Rate" }),
        lat.heart_rate ?? "—", "bpm"),
      // Temperature
      vitalsTile(t("patients.vitals.temp", { default: "Temperature" }),
        lat.temperature ? `${lat.temperature}` : "—", "°C"),
      // SpO2
      vitalsTile(t("patients.vitals.spo2", { default: "Oxygen (SpO2)" }),
        lat.spo2 ? `${lat.spo2}` : "—", "%"),
      // Resp Rate
      vitalsTile(t("patients.vitals.rr", { default: "Resp Rate" }),
        lat.resp_rate ?? "—", "/min"),
      // Weight
      vitalsTile(t("patients.vitals.weight", { default: "Weight" }),
        lat.weight ? `${lat.weight}` : "—", "kg"),
      // Height
      vitalsTile(t("patients.vitals.height", { default: "Height" }),
        lat.height ? `${lat.height}` : "—", "cm"),
      // BMI
      vitalsTile(t("patients.vitals.bmi", { default: "Body Mass Index" }),
        lat.bmi ? `${lat.bmi}` : "—", "kg/m²", bmiCat ? h("span", { class: `badge ${bmiCat.cls}` }, bmiCat.label) : null),
    );

    const footer = h("div", { class: "card-footer row-between text-xs muted" },
      h("span", `${t("patients.vitals.last_recorded", { default: "Last recorded" })}: ${formatDateTime(lat.recorded_at)}`),
      lat.author_name ? h("span", `${lat.author_name} (${lat.author_role || ""})`) : null
    );

    mount(root, header, h("div", { class: "card-body" }, grid), footer);
  }

  load();
  return root;
}

function vitalsTile(label, val, unit, badge = null) {
  return h("div", { class: "vitals-tile" },
    h("div", { class: "vitals-tile-header row-between" },
      h("span", { class: "vitals-tile-label" }, label),
      badge
    ),
    h("div", { class: "vitals-tile-val" },
      h("strong", { class: "ltr" }, val),
      unit ? h("span", { class: "vitals-tile-unit" }, unit) : null
    )
  );
}

function pNull(text) {
  return h("p", { class: "muted" }, t("patients.vitals.none", { default: text }));
}

/**
 * Record Vitals Modal
 */
export function openRecordVitalsModal({ ctx, patient, visit = null, onSaved }) {
  let form;
  form = createForm({
    fields: [
      { name: "bp_systolic", label: t("patients.vitals.bp_sys", { default: "Systolic BP (mmHg)" }), type: "number", min: 30, max: 300, placeholder: "120" },
      { name: "bp_diastolic", label: t("patients.vitals.bp_dia", { default: "Diastolic BP (mmHg)" }), type: "number", min: 10, max: 200, placeholder: "80" },
      { name: "heart_rate", label: t("patients.vitals.hr_label", { default: "Heart Rate (bpm)" }), type: "number", min: 10, max: 300, placeholder: "72" },
      { name: "temperature", label: t("patients.vitals.temp_label", { default: "Temperature (°C)" }), type: "number", min: 25, max: 45, step: 0.1, placeholder: "36.8" },
      { name: "spo2", label: t("patients.vitals.spo2_label", { default: "Oxygen Saturation (%)" }), type: "number", min: 0, max: 100, placeholder: "98" },
      { name: "resp_rate", label: t("patients.vitals.rr_label", { default: "Respiratory Rate (/min)" }), type: "number", min: 1, max: 100, placeholder: "16" },
      { name: "weight", label: t("patients.vitals.weight_label", { default: "Weight (kg)" }), type: "number", min: 0.2, max: 500, step: 0.1, placeholder: "70.0" },
      { name: "height", label: t("patients.vitals.height_label", { default: "Height (cm)" }), type: "number", min: 20, max: 260, step: 0.5, placeholder: "175.0" },
      { name: "notes", label: t("patients.vitals.notes", { default: "Clinical Notes & Observations" }), type: "textarea", span: 2, rows: 2 },
    ],
    submitLabel: t("core.save", { default: "Save Vitals" }),
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      try {
        const payload = { ...v, visit_id: visit?.id };
        await api.post(`/patients/${patient.id}/vitals`, payload);
        modal.close();
        toastSuccess(t("core.saved", { default: "Saved successfully" }));
        onSaved?.();
      } catch (err) {
        toastApiError(err);
      }
    }
  });

  const modal = openModal({
    title: t("patients.vitals.record_title", { default: "Record Vital Signs" }),
    body: form.el,
    size: "lg"
  });
}

/**
 * Historical Vitals Flowsheet & Trends Modal
 */
export function openVitalsHistoryModal({ ctx, patient, vitalsData, onUpdated }) {
  const body = h("div", { class: "stack gap-md" });
  const modal = openModal({
    title: t("patients.vitals.history_title", { default: "Vital Signs Flowsheet & History" }),
    body,
    size: "xl"
  });

  function render(data) {
    const items = data.items || [];
    const trends = data.trends || {};

    // Sparkline charts
    const charts = h("div", { class: "vitals-trends-row grid-3 gap-md" },
      trendCard(t("patients.vitals.bp_trend", { default: "Blood Pressure Trend" }), trends.bp_systolic, trends.bp_diastolic, "mmHg"),
      trendCard(t("patients.vitals.hr_trend", { default: "Heart Rate Trend" }), trends.heart_rate, null, "bpm"),
      trendCard(t("patients.vitals.weight_trend", { default: "Weight Trend" }), trends.weight, null, "kg")
    );

    // Table
    const table = h("div", { class: "table-wrap card" },
      h("table", { class: "table text-sm" },
        h("thead", h("tr",
          h("th", t("patients.vitals.col_date", { default: "Date / Time" })),
          h("th", t("patients.vitals.col_bp", { default: "BP (mmHg)" })),
          h("th", t("patients.vitals.col_hr", { default: "HR (bpm)" })),
          h("th", t("patients.vitals.col_temp", { default: "Temp (°C)" })),
          h("th", t("patients.vitals.col_spo2", { default: "SpO2 (%)" })),
          h("th", t("patients.vitals.col_weight", { default: "Weight" })),
          h("th", t("patients.vitals.col_bmi", { default: "BMI" })),
          h("th", t("patients.vitals.col_author", { default: "Author" })),
          can("medical_records.delete") ? h("th", "") : null
        )),
        h("tbody", items.map((v) => {
          const bpCat = bpCategory(v.bp_systolic, v.bp_diastolic);
          const bmiCat = bmiCategory(v.bmi);
          return h("tr",
            h("td", { class: "nowrap" }, formatDateTime(v.recorded_at)),
            h("td", { class: "ltr" }, v.bp_systolic && v.bp_diastolic ? `${v.bp_systolic}/${v.bp_diastolic}` : "—",
              bpCat ? h("span", { class: `badge ${bpCat.cls} ms-xs` }, bpCat.label) : null),
            h("td", { class: "ltr" }, v.heart_rate ?? "—"),
            h("td", { class: "ltr" }, v.temperature ?? "—"),
            h("td", { class: "ltr" }, v.spo2 ? `${v.spo2}%` : "—"),
            h("td", { class: "ltr" }, v.weight ? `${v.weight} kg` : "—"),
            h("td", { class: "ltr" }, v.bmi ?? "—",
              bmiCat ? h("span", { class: `badge ${bmiCat.cls} ms-xs` }, bmiCat.label) : null),
            h("td", v.author_name || "—"),
            can("medical_records.delete") ? h("td", h("button", {
              class: "btn btn-icon btn-ghost btn-sm",
              type: "button",
              onClick: async () => {
                if (!confirm(t("core.confirm_delete", { default: "Delete this record?" }))) return;
                try {
                  await api.delete(`/vitals/${v.id}`);
                  const refreshed = await api.get(`/patients/${patient.id}/vitals`);
                  render(refreshed);
                  onUpdated?.();
                } catch (e) { toastApiError(e); }
              }
            }, icon("trash"))) : null
          );
        }))
      )
    );

    mount(body, charts, table);
  }

  render(vitalsData);
}

function trendCard(title, seriesA, seriesB, unit) {
  const points = (seriesA || []).filter((p) => p.val != null);
  if (!points.length) {
    return h("div", { class: "card card-body text-center muted text-xs" }, h("strong", title), h("p", "No data"));
  }

  const svg = renderSparkline(points, seriesB, 220, 60);
  const latestVal = points[points.length - 1]?.val;

  return h("div", { class: "card card-body stack gap-xs" },
    h("div", { class: "row-between text-xs" },
      h("strong", title),
      h("span", { class: "ltr font-bold text-accent" }, `${latestVal} ${unit}`)
    ),
    svg
  );
}

function renderSparkline(seriesA, seriesB, width, height) {
  const valsA = seriesA.map((p) => Number(p.val));
  const valsB = (seriesB || []).map((p) => Number(p.val));
  const allVals = [...valsA, ...valsB];
  const min = Math.min(...allVals);
  const max = Math.max(...allVals);
  const range = max - min || 1;

  function toPath(series, stroke) {
    if (!series || !series.length) return "";
    const n = series.length;
    const pts = series.map((p, i) => {
      const x = n > 1 ? (i / (n - 1)) * (width - 16) + 8 : width / 2;
      const y = height - 8 - ((Number(p.val) - min) / range) * (height - 16);
      return `${Math.round(x)},${Math.round(y)}`;
    });
    return pts.length === 1
      ? `<circle cx="${pts[0].split(",")[0]}" cy="${pts[0].split(",")[1]}" r="4" fill="${stroke}"/>`
      : `<polyline fill="none" stroke="${stroke}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="${pts.join(" ")}"/>`;
  }

  const pathA = toPath(seriesA, "var(--accent, #0284c7)");
  const pathB = seriesB ? toPath(seriesB, "#9333ea") : "";

  const el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  el.setAttribute("viewBox", `0 0 ${width} ${height}`);
  el.setAttribute("class", "vitals-sparkline");
  el.style.width = "100%";
  el.style.height = `${height}px`;
  el.innerHTML = `${pathA}${pathB}`;
  return el;
}
