// Pharmacy module entry point
import {
  api, h, mount, t, can, icon, dataTable, tabs, formatDateTime, formatMoney,
  openModal, openDrawer, createForm, toastSuccess, toastApiError, emptyState, loadingState, errorState,
} from "../core/index.js";
import { dict } from "./i18n.js";

export function register(registry) {
  registry.i18n(dict);

  // Department routes
  registry.route({
    area: "department",
    env: ["pharmacy"],
    path: "queue",
    title: "pharmacy.tab.queue",
    perm: "pharmacy.dispense",
    render: renderQueue,
  });

  registry.menu({
    area: "department",
    env: ["pharmacy"],
    key: "pharmacy-queue",
    path: "queue",
    label: "pharmacy.tab.queue",
    icon: "shoppingBag",
    perm: "pharmacy.dispense",
    order: 20,
  });

  registry.route({
    area: "department",
    env: ["pharmacy"],
    path: "sales",
    title: "pharmacy.tab.sales",
    perm: "pharmacy.sell",
    render: renderSales,
  });

  registry.menu({
    area: "department",
    env: ["pharmacy"],
    key: "pharmacy-sales",
    path: "sales",
    label: "pharmacy.tab.sales",
    icon: "tag",
    perm: "pharmacy.sell",
    order: 30,
  });
}

function renderQueue(ctx) {
  ctx.setTitle(t("pharmacy.tab.queue"));
  const table = dataTable({
    columns: [
      { key: "created_at", label: t("pharmacy.col.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.created_at)) },
      { key: "patient", label: t("pharmacy.col.patient"), render: (r) => h("strong", r.patient?.full_name || r.patient?.name || `Patient #${r.patient_id}`) },
      { key: "doctor", label: t("pharmacy.col.doctor"), render: (r) => r.doctor_name || "—" },
      { key: "clinic", label: t("pharmacy.col.clinic"), render: (r) => r.clinic_name || "" },
      { key: "status", label: t("pharmacy.col.status"), render: (r) => h("span", { class: `pill pill--${r.status === "dispensed" ? "success" : "warning"}` }, t(`pharmacy.status.${r.status}`, r.status)) },
    ],
    fetch: (q) => api.get("/pharmacy/queue", { query: { ...q, status: "open" } }),
    onRowClick: (r) => openDispenseModal(r.id, () => table.reload()),
    empty: { icon: "shoppingBag", title: t("pharmacy.queue.empty") },
  });

  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("h1", t("pharmacy.tab.queue")),
      h("p", { class: "subtitle" }, ctx.dept?.name)
    ),
    table.el
  );
}

function renderSales(ctx) {
  ctx.setTitle(t("pharmacy.tab.sales"));
  const table = dataTable({
    columns: [
      { key: "created_at", label: t("pharmacy.col.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.created_at)) },
      { key: "patient", label: t("pharmacy.col.patient"), render: (r) => r.patient?.full_name || r.customer_name || "OTC Customer" },
      { key: "total", label: t("pharmacy.col.total"), render: (r) => formatMoney(r.total) },
      { key: "paid", label: t("pharmacy.sales.paid"), render: (r) => formatMoney(r.paid_amount) },
    ],
    fetch: (q) => api.get("/pharmacy/sales", { query: q }),
    empty: { icon: "tag", title: t("pharmacy.sales.empty") },
  });

  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("h1", t("pharmacy.tab.sales")),
      h("p", { class: "subtitle" }, ctx.dept?.name)
    ),
    table.el
  );
}

async function openDispenseModal(rxId, onDone) {
  const body = h("div", loadingState());
  const modal = openModal({ title: t("pharmacy.dispense.title", { id: rxId }), body, size: "lg" });

  try {
    const rx = await api.get(`/pharmacy/prescriptions/${rxId}`);
    const items = rx.items || [];

    const itemsList = h("div", { class: "stack gap-sm" },
      items.map((item) => h("div", { class: "card card-body row-between" },
        h("div",
          h("strong", item.medication_name),
          h("div", { class: "text-sm text-muted" }, `${item.dose || ""} · ${item.instructions || ""}`),
          h("div", { class: "text-xs" }, `Qty: ${item.quantity} (Dispensed: ${item.dispensed_quantity || 0})`)
        ),
        h("input", {
          class: "input input-sm",
          type: "number",
          min: 0,
          max: (item.quantity - (item.dispensed_quantity || 0)),
          value: (item.quantity - (item.dispensed_quantity || 0)),
          dataset: { itemId: item.id },
          style: "width: 80px;",
        })
      ))
    );

    const submitBtn = h("button", { class: "btn btn-primary", type: "button" }, icon("check"), t("pharmacy.dispense.action"));
    submitBtn.addEventListener("click", async () => {
      submitBtn.disabled = true;
      try {
        const dispenseItems = [...itemsList.querySelectorAll("input")].map((inp) => ({
          prescription_item_id: Number(inp.dataset.itemId),
          quantity: Number(inp.value) || 0,
        })).filter((x) => x.quantity > 0);

        await api.post(`/pharmacy/prescriptions/${rxId}/dispense`, {
          version: rx.version,
          items: dispenseItems,
          complete: true,
        });
        modal.close();
        toastSuccess(t("pharmacy.dispense.success"));
        if (onDone) onDone();
      } catch (err) {
        toastApiError(err);
      } finally {
        submitBtn.disabled = false;
      }
    });

    mount(body,
      h("div", { class: "stack gap-md" },
        itemsList,
        h("div", { class: "row-end gap-sm" },
          h("button", { class: "btn", type: "button", onClick: () => modal.close() }, t("core.cancel")),
          submitBtn
        )
      )
    );
  } catch (e) {
    mount(body, errorState(e));
  }
}
