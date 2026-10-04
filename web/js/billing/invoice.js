// Invoice detail: items, Total/Paid/Remaining, cash payments (partial), issue, void, delete+undo, print.
import { api, h, t, mount, navigate, toast, toastApiError, openModal, confirmDialog, createForm, deleteWithUndo,
  printPdf, formatDateTime, formatMoney, getLang, can, icon, getDepartment } from "../core/index.js";
import { link, invoiceStatus, totalsStrip, money, clinicName } from "./util.js";

export async function renderInvoice(ctx) {
  const id = Number(ctx.params.id);
  const root = h("div", { class: "page billing-page" });

  async function load() {
    const inv = await api.get(`/billing/invoices/${id}`);
    mount(root, ...view(inv));
  }

  function view(inv) {
    const live = inv.status !== "void";
    const actions = [];
    const btn = (label, ic, onClick, variant) => {
      const b = h("button", { class: `btn ${variant ? `btn-${variant}` : ""}`, type: "button" }, icon(ic), label);
      b.addEventListener("click", () => onClick(b));
      return b;
    };
    if (inv.status === "draft" && can("billing.edit")) actions.push(h("a", { class: "btn", href: link(ctx, `invoices/${inv.id}/edit`) }, icon("edit"), t("billing.detail.edit")));
    if (inv.status === "draft" && can("billing.create")) actions.push(btn(t("billing.detail.issue"), "check", issue, "primary"));
    if (live && Number(inv.balance) > 0 && can("billing.create")) actions.push(btn(t("billing.detail.add_payment"), "wallet", () => pay(inv), inv.status === "draft" ? null : "primary"));
    actions.push(btn(t("billing.detail.print_invoice"), "printer", () => printPdf(`/billing/invoices/${inv.id}/pdf`, { lang: getLang() })));
    if (inv.payments.some((p) => !p.is_void)) actions.push(btn(t("billing.detail.print_receipt"), "printer", () => printPdf(`/billing/invoices/${inv.id}/receipt`, { lang: getLang() })));
    if (live && Number(inv.paid_total) === 0 && can("billing.edit")) actions.push(btn(t("billing.detail.void"), "x", voidInvoice, "ghost"));
    if (can("billing.delete")) actions.push(btn(t("billing.detail.delete"), "trash", remove, "ghost"));

    async function issue(b) {
      b.disabled = true;
      try {
        await api.post(`/billing/invoices/${inv.id}/issue`, { version: inv.version });
        toast(t("billing.detail.issued"), { type: "success" });
        await load();
      } catch (e) { onError(e); } finally { b.disabled = false; }
    }
    async function voidInvoice() {
      let reason = "";
      const input = h("input", { class: "input", maxlength: 300 });
      input.addEventListener("input", () => { reason = input.value.trim(); });
      const ok = await new Promise((resolve) => {
        let res = false;
        openModal({ title: t("billing.detail.void"), size: "sm",
          body: [h("p", t("billing.detail.void_confirm")), h("div", { class: "field" }, h("label", t("billing.detail.void_reason")), input)],
          actions: [{ label: t("core.cancel") }, { label: t("billing.detail.void"), variant: "danger", onClick: () => { res = true; } }],
          onClose: () => resolve(res) });
      });
      if (!ok) return;
      try {
        await api.post(`/billing/invoices/${inv.id}/void`, { version: inv.version, reason: reason || null });
        toast(t("billing.detail.voided_ok"), { type: "success" });
        await load();
      } catch (e) { onError(e); }
    }
    async function remove() {
      if (!(await confirmDialog({ danger: true, confirmLabel: t("billing.detail.delete") }))) return;
      try {
        await deleteWithUndo(`/billing/invoices/${inv.id}`, { message: t("billing.detail.deleted"),
          onDone: () => navigate(link(ctx, "invoices")), onUndone: () => navigate(link(ctx, `invoices/${inv.id}`)) });
      } catch { /* toast shown */ }
    }

    const dept = getDepartment(inv.department_id);
    const kv = h("dl", { class: "kv" },
      h("dt", t("billing.patient")), h("dd", inv.patient_name || "", inv.patient_code ? h("span", { class: "text-muted ltr" }, ` ${inv.patient_code}`) : null),
      h("dt", t("billing.date")), h("dd", formatDateTime(inv.issued_at || inv.created_at)),
      h("dt", t("billing.department")), h("dd", inv.department_name || (dept ? dept.name : "")),
      h("dt", t("billing.clinic")), h("dd", inv.clinic_name || clinicName(inv.clinic_id)),
      inv.doctor_name ? [h("dt", t("billing.doctor")), h("dd", inv.doctor_name)] : null,
      h("dt", t("billing.created_by")), h("dd", inv.created_by || ""),
      inv.notes ? [h("dt", t("billing.notes")), h("dd", { style: "white-space:pre-wrap" }, inv.notes)] : null);

    const items = h("div", { class: "card" }, h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" },
      h("thead", h("tr", [t("billing.detail.item"), t("billing.editor.qty"), t("billing.editor.price"), t("billing.editor.discount"), t("billing.editor.line_total")].map((x, i) => h("th", { class: i ? "num" : null }, x)))),
      h("tbody", inv.items.map((it) => h("tr",
        h("td", { "data-label": t("billing.detail.item") }, it.description, h("div", { class: "text-sm text-muted" }, t(`billing.kind.${it.kind}`))),
        h("td", { class: "num", "data-label": t("billing.editor.qty") }, h("span", { class: "ltr" }, String(Number(it.qty)))),
        h("td", { class: "num", "data-label": t("billing.editor.price") }, money(it.unit_price)),
        h("td", { class: "num", "data-label": t("billing.editor.discount") }, Number(it.discount_amount)
          ? h("span", money(it.discount_amount), it.discount_percent != null ? h("span", { class: "text-muted ltr" }, ` (${Number(it.discount_percent)}%)`) : null) : "—"),
        h("td", { class: "num", "data-label": t("billing.editor.line_total") }, money(it.line_total)))))),
    h("div", { class: "card-footer billing-sumlines" },
      h("div", { class: "row-between" }, h("span", t("billing.subtotal")), money(inv.subtotal)),
      Number(inv.discount_total) ? h("div", { class: "row-between" }, h("span", t("billing.discounts")), money(inv.discount_total)) : null,
      h("div", { class: "row-between billing-grand" }, h("span", t("billing.total")), money(inv.total)))));

    const payments = h("section", { class: "card" },
      h("div", { class: "card-header" }, h("h2", t("billing.detail.payments"))),
      inv.payments.length ? h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" },
        h("thead", h("tr", [t("billing.detail.receipt_no"), t("billing.detail.paid_at"), t("billing.detail.received_by"), t("billing.detail.method"), t("billing.detail.amount"), ""].map((x) => h("th", x)))),
        h("tbody", inv.payments.map((p) => h("tr", { class: p.is_void ? "billing-voided" : null },
          h("td", { "data-label": t("billing.detail.receipt_no") }, h("span", { class: "ltr" }, p.receipt_number)),
          h("td", { "data-label": t("billing.detail.paid_at") }, formatDateTime(p.paid_at)),
          h("td", { "data-label": t("billing.detail.received_by") }, p.received_by),
          h("td", { "data-label": t("billing.detail.method") }, t("billing.detail.cash")),
          h("td", { class: "num", "data-label": t("billing.detail.amount") }, money(p.amount),
            p.is_void ? h("div", { class: "text-sm text-muted" }, t("billing.detail.voided"), p.void_reason ? ` — ${p.void_reason}` : "") : null),
          h("td", { class: "actions" }, p.is_void ? null : h("div", { class: "btn-group" },
            h("button", { class: "btn btn-sm btn-ghost", type: "button", title: t("billing.detail.print_receipt"), "aria-label": t("billing.detail.print_receipt"),
              onClick: () => printPdf(`/billing/invoices/${inv.id}/receipt`, { payment_id: p.id, lang: getLang() }) }, icon("printer")),
            can("billing.edit") ? h("button", { class: "btn btn-sm btn-ghost", type: "button", title: t("billing.detail.void_payment"), "aria-label": t("billing.detail.void_payment"),
              onClick: () => voidPayment(p) }, icon("x")) : null)))))))
        : h("div", { class: "card-body text-muted" }, t("billing.detail.no_payments")));

    async function voidPayment(p) {
      if (!(await confirmDialog({ danger: true, message: t("billing.detail.void_payment_confirm"), confirmLabel: t("billing.detail.void_payment") }))) return;
      try {
        await api.post(`/billing/invoices/${inv.id}/payments/${p.id}/void`, {});
        toast(t("billing.detail.payment_voided"), { type: "success" });
        await load();
      } catch (e) { onError(e); }
    }

    return [
      h("div", { class: "page-header" },
        h("div", h("a", { class: "btn btn-link", href: link(ctx, "invoices") }, icon("arrowLeft", "flip-rtl"), t("billing.tab.invoices")),
          h("h1", { class: "row" }, h("span", t("billing.invoice")), h("span", { class: "ltr" }, inv.number), invoiceStatus(inv.status)),
          inv.status === "void" && inv.voided_at ? h("p", { class: "text-muted" }, t("billing.detail.voided_on", { date: formatDateTime(inv.voided_at) }), inv.void_reason ? ` — ${inv.void_reason}` : "") : null),
        h("div", { class: "page-actions btn-group no-print" }, actions)),
      totalsStrip(inv),
      h("div", { class: "grid-2 billing-detail" }, h("section", { class: "card card-pad" }, kv), items),
      payments,
    ];
  }

  function pay(inv) {
    const form = createForm({
      columns: 1,
      fields: [
        { name: "amount", label: t("billing.detail.amount"), type: "money", required: true, min: "0.01", max: inv.balance,
          help: t("billing.remaining") + ": " + formatMoney(inv.balance) },
        { name: "notes", label: t("billing.notes"), maxLength: 500 },
      ],
      values: { amount: inv.balance },
      submitLabel: t("billing.detail.add_payment"),
      onSubmit: async (v) => {
        if (Number(v.amount) > Number(inv.balance)) return form.setErrors({ amount: t("billing.detail.overpay", { amount: formatMoney(inv.balance) }) });
        const res = await api.post(`/billing/invoices/${inv.id}/payments`, { amount: v.amount, method: "cash", notes: v.notes });
        modal.close();
        toast(t("billing.detail.payment_ok"), { type: "success", action: { label: t("billing.detail.print_receipt"),
          onClick: () => printPdf(`/billing/invoices/${inv.id}/receipt`, { payment_id: res.payment.id, lang: getLang() }) } });
        await load();
      },
    });
    const modal = openModal({ title: `${t("billing.detail.add_payment")} — ${inv.number}`, size: "sm",
      body: [inv.status === "draft" ? h("div", { class: "alert" }, icon("info"), h("div", t("billing.detail.issue_first"))) : null,
        h("p", { class: "row-between" }, h("span", t("billing.detail.method")), h("strong", t("billing.detail.cash"))), form.el] });
  }

  function onError(e) {
    if (e?.code === "version_conflict") {
      toast(t("billing.detail.conflict"), { type: "warning", action: { label: t("billing.detail.reload"), onClick: load } });
    } else toastApiError(e);
  }

  await load();
  return root;
}

