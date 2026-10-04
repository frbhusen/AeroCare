// Tabs: tabs([{key, label, render: (panelEl) => void}], {active, onChange}) -> {el, select(key)}
import { h, mount } from "../core/dom.js";

export function tabs(items, { active, onChange } = {}) {
  const list = h("div", { class: "tabs", role: "tablist" });
  const panel = h("div", { class: "tab-panel", role: "tabpanel" });
  const el = h("div", list, panel);
  let current = null;
  const buttons = items.map((it) => h("button", { class: "tab", type: "button", role: "tab", "aria-selected": "false",
    onClick: () => select(it.key) }, it.label));
  mount(list, buttons);
  function select(key) {
    const i = items.findIndex((x) => x.key === key);
    if (i < 0 || key === current) return;
    current = key;
    buttons.forEach((b, j) => b.setAttribute("aria-selected", String(j === i)));
    mount(panel);
    items[i].render(panel);
    if (onChange) onChange(key);
  }
  select(active ?? items[0]?.key);
  return { el, select, get active() { return current; } };
}
