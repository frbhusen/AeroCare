// 80mm Thermal Receipt Printing (POS / Cashier)
import { h } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { formatDateTime, formatMoney } from "../core/i18n.js";
import { getCenter } from "../core/state.js";
import { printElement } from "../components/print.js";
import { renderBarcodeSVG } from "../components/barcode.js";

/**
 * Print an 80mm POS thermal receipt for an invoice or a specific payment.
 * @param {object} inv Invoice object from API
 * @param {object|null} payment Optional payment object (if printing a specific receipt)
 */
export function printThermalReceipt(inv, payment = null) {
  const center = getCenter() || {};
  const receiptNo = payment?.receipt_number || inv.invoice_number || `INV-${inv.id}`;
  const invNo = inv.invoice_number || `INV-${inv.id}`;
  const dateStr = formatDateTime(payment?.paid_at || inv.issued_at || inv.created_at);
  const cashier = payment?.received_by || inv.created_by || "—";
  const paidNow = payment ? payment.amount : inv.paid_total;

  const node = h("div", { class: "receipt-thermal", id: "thermal-receipt-printable" },
    // Header
    h("div", { class: "th-header" },
      h("div", { class: "th-center-name" }, center.name || t("billing.receipt.center", { default: "Health Center" })),
      center.phone ? h("div", { class: "th-center-contact ltr" }, center.phone) : null,
      center.address ? h("div", { class: "th-center-address" }, center.address) : null,
      h("div", { class: "th-title" }, payment ? t("billing.receipt.payment_title", { default: "PAYMENT RECEIPT / إيصال قبض" }) : t("billing.receipt.invoice_title", { default: "TAX INVOICE / فاتورة ضريبية" }))
    ),

    h("div", { class: "th-divider" }),

    // Metadata
    h("div", { class: "th-meta" },
      h("div", { class: "th-row" },
        h("span", { class: "th-lbl" }, t("billing.detail.receipt_no", { default: "Receipt No:" })),
        h("span", { class: "th-val ltr" }, receiptNo)),
      h("div", { class: "th-row" },
        h("span", { class: "th-lbl" }, t("billing.invoice", { default: "Invoice:" })),
        h("span", { class: "th-val ltr" }, invNo)),
      h("div", { class: "th-row" },
        h("span", { class: "th-lbl" }, t("billing.date", { default: "Date:" })),
        h("span", { class: "th-val" }, dateStr)),
      h("div", { class: "th-row" },
        h("span", { class: "th-lbl" }, t("billing.detail.received_by", { default: "Cashier:" })),
        h("span", { class: "th-val" }, cashier)),
      h("div", { class: "th-row" },
        h("span", { class: "th-lbl" }, t("billing.patient", { default: "Patient:" })),
        h("span", { class: "th-val" }, inv.patient_name || "—")),
      inv.patient_code ? h("div", { class: "th-row" },
        h("span", { class: "th-lbl" }, t("patients.field.code", { default: "File No:" })),
        h("span", { class: "th-val ltr" }, inv.patient_code)) : null,
      inv.department_name ? h("div", { class: "th-row" },
        h("span", { class: "th-lbl" }, t("billing.department", { default: "Dept:" })),
        h("span", { class: "th-val" }, `${inv.department_name}${inv.clinic_name ? ` - ${inv.clinic_name}` : ""}`)) : null,
      inv.doctor_name ? h("div", { class: "th-row" },
        h("span", { class: "th-lbl" }, t("billing.doctor", { default: "Doctor:" })),
        h("span", { class: "th-val" }, inv.doctor_name)) : null
    ),

    h("div", { class: "th-divider" }),

    // Items list
    h("div", { class: "th-items" },
      h("div", { class: "th-items-head" },
        h("span", { class: "th-col-desc" }, t("billing.detail.item", { default: "Item" })),
        h("span", { class: "th-col-total" }, t("billing.editor.line_total", { default: "Total" }))),
      (inv.items || []).map((it) =>
        h("div", { class: "th-item-line" },
          h("div", { class: "th-item-name" }, it.description),
          h("div", { class: "th-item-calc" },
            h("span", { class: "text-muted ltr" }, `${Number(it.qty)} × ${formatMoney(it.unit_price)}`),
            h("span", { class: "th-item-total ltr" }, formatMoney(it.line_total))))
      )
    ),

    h("div", { class: "th-divider" }),

    // Totals
    h("div", { class: "th-totals" },
      h("div", { class: "th-row" },
        h("span", t("billing.subtotal", { default: "Subtotal:" })),
        h("span", { class: "ltr" }, formatMoney(inv.subtotal))),
      Number(inv.discount_total) > 0 ? h("div", { class: "th-row" },
        h("span", t("billing.discounts", { default: "Discount:" })),
        h("span", { class: "ltr" }, `-${formatMoney(inv.discount_total)}`)) : null,
      h("div", { class: "th-row th-grand-total" },
        h("span", t("billing.total", { default: "TOTAL:" })),
        h("span", { class: "ltr" }, formatMoney(inv.total))),
      h("div", { class: "th-divider th-divider-dashed" }),
      h("div", { class: "th-row th-paid-now" },
        h("span", payment ? t("billing.receipt.paid_amount", { default: "Amount Paid:" }) : t("billing.paid", { default: "Paid:" })),
        h("span", { class: "ltr" }, formatMoney(paidNow))),
      payment ? h("div", { class: "th-row" },
        h("span", t("billing.detail.total_paid", { default: "Total Paid:" })),
        h("span", { class: "ltr" }, formatMoney(inv.paid_total))) : null,
      h("div", { class: "th-row th-balance" },
        h("span", t("billing.balance", { default: "Balance Due:" })),
        h("span", { class: "ltr" }, formatMoney(inv.balance)))
    ),

    h("div", { class: "th-divider" }),

    // Barcode & Footer
    h("div", { class: "th-barcode-wrap" },
      renderBarcodeSVG(receiptNo, { height: 35, showText: true, className: "th-barcode-svg" })
    ),

    h("div", { class: "th-footer" },
      h("div", { class: "th-thanks" }, t("billing.receipt.thank_you", { default: "Thank you for visiting us / شكراً لزيارتكم" })),
      h("div", { class: "th-power text-muted text-xs" }, center.name || "AeroCare")
    )
  );

  document.body.classList.add("printing-thermal");
  printElement(node);
  const cleanup = () => {
    document.body.classList.remove("printing-thermal");
    window.removeEventListener("afterprint", cleanup);
  };
  window.addEventListener("afterprint", cleanup);
}
