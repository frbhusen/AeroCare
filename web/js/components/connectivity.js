// Connectivity / sync indicator (spec §75). Click opens the sync review panel.
import { h } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { onEvent } from "../core/events.js";
import { getSyncStatus } from "../offline/status.js";
import { openSyncPanel } from "../offline/sync-panel.js";

export function connectivityIndicator({ light = false } = {}) {
  const label = h("span", { class: "conn-label" });
  const el = h("button", { class: ["conn", light && "conn-light"], type: "button", onClick: () => openSyncPanel() }, label);
  const render = (st = getSyncStatus()) => {
    el.dataset.state = st.state;
    const text = t(`core.conn.${st.state}`) + (st.pending && st.state !== "issue" ? ` (${st.pending})` : "");
    label.textContent = text;
    el.title = text;
    el.setAttribute("aria-label", text);
  };
  render();
  const off = onEvent("sync:status", render);
  const offLang = onEvent("lang:changed", () => render());
  el.destroy = () => { off(); offLang(); };
  return el;
}
