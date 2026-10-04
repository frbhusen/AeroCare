// Review UI for queued changes and sync issues: view details, retry, discard.
import { h, mount } from "../core/dom.js";
import { t, formatDateTime } from "../core/i18n.js";
import { onEvent } from "../core/events.js";
import { listOps, retryOp, discardOp, replay } from "./queue.js";
import { getSyncStatus } from "./status.js";
import { openDrawer, confirmDialog } from "../components/modal.js";
import { emptyState } from "../components/states.js";
import { icon } from "../components/icons.js";

export function openSyncPanel() {
  const body = h("div", { class: "stack" });
  const m = openDrawer({ title: t("core.sync.title"), body });
  const off = onEvent("sync:status", () => render());
  const origClose = m.close;
  m.close = () => { off(); origClose(); };

  async function render() {
    if (!body.isConnected) return off();
    const ops = await listOps();
    const st = getSyncStatus();
    const issues = ops.filter((o) => o.status === "issue");
    const pending = ops.filter((o) => o.status === "pending");
    mount(body,
      h("div", { class: `alert ${st.state === "issue" ? "alert-danger" : st.state === "offline" ? "alert-warning" : ""}` }, icon(st.online ? "wifi" : "wifiOff"), h("div", t(`core.conn.${st.state}`))),
      issues.length ? h("h3", t("core.sync.issues", { count: issues.length })) : null,
      issues.map((op) => opCard(op, true)),
      h("div", { class: "row-between" }, h("h3", t("core.sync.pending", { count: pending.length })),
        pending.length && st.online ? h("button", { class: "btn btn-sm", type: "button", onClick: () => replay() }, icon("refresh"), t("core.sync.sync_now")) : null),
      pending.length ? pending.map((op) => opCard(op, false)) : emptyState({ icon: "cloud", title: t("core.sync.nothing") }));
  }

  function opCard(op, isIssue) {
    const details = h("pre", { hidden: true }, JSON.stringify({ request: { method: op.method, url: op.url, body: op.body }, error: op.error }, null, 2));
    return h("div", { class: "sync-op" },
      h("div", { class: "row-between" },
        h("div", h("strong", op.label || `${op.method} ${op.url.replace(/^\/api\/v1/, "")}`),
          h("div", { class: "text-xs text-muted" }, formatDateTime(op.created_at))),
        isIssue ? h("span", { class: "pill pill--danger" }, t("core.sync.issue")) : h("span", { class: "pill pill--warning" }, t("core.sync.waiting"))),
      isIssue && op.error ? h("div", { class: "text-sm text-danger" }, op.error.message) : null,
      h("div", { class: "row", style: "margin-top:8px" },
        h("button", { class: "btn btn-sm", type: "button", onClick: () => { details.hidden = !details.hidden; } }, icon("eye"), t("core.sync.details")),
        isIssue ? h("button", { class: "btn btn-sm", type: "button", onClick: () => retryOp(op.op_id).then(render) }, icon("refresh"), t("core.retry")) : null,
        h("button", { class: "btn btn-sm btn-ghost text-danger", type: "button", onClick: async () => {
          if (await confirmDialog({ title: t("core.sync.discard"), message: t("core.sync.discard_confirm"), danger: true, confirmLabel: t("core.sync.discard") })) {
            await discardOp(op.op_id);
            render();
          }
        } }, icon("trash"), t("core.sync.discard"))),
      details);
  }

  render();
  return m;
}
