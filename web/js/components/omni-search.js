// Global Omni-Search / Command Palette (Ctrl+K or /)
// Instant search for patients, departments, and fast clinical actions.
import { api, h, t, mount, formatDate, navigate, href, getPrincipal, getCenter, getDepartments } from "../core/index.js";
import { icon } from "./icons.js";
import { openModal } from "./modal.js";

let activeModal = null;

export function initOmniSearchHotkeys() {
  window.addEventListener("keydown", (e) => {
    // Ctrl+K or Cmd+K
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openOmniSearch();
      return;
    }
    // Slash / when not typing in an input
    if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
      e.preventDefault();
      openOmniSearch();
    }
  });
}

export function openOmniSearch() {
  if (activeModal) return;

  const p = getPrincipal() || {};
  const depts = getDepartments() || [];

  const input = h("input", {
    class: "omni-input",
    type: "search",
    placeholder: t("core.search.omni_placeholder", { default: "Search patients, departments, actions... (Ctrl+K)" }),
    autocomplete: "off",
    autofocus: true,
  });

  const resultsBox = h("div", { class: "omni-results", role: "listbox" });

  let items = [];
  let activeIndex = 0;
  let searchSeq = 0;

  function renderList() {
    resultsBox.innerHTML = "";
    if (!items.length) {
      const empty = h("div", { class: "omni-empty" }, icon("search"), h("span", t("core.search.no_results", { default: "No matches found" })));
      resultsBox.append(empty);
      return;
    }

    let lastGroup = null;
    items.forEach((item, idx) => {
      if (item.group && item.group !== lastGroup) {
        lastGroup = item.group;
        const groupEl = h("div", { class: "omni-group-title" }, item.group);
        resultsBox.append(groupEl);
      }

      const el = h("button", {
        class: ["omni-item", idx === activeIndex && "is-active"],
        type: "button",
        role: "option",
        "aria-selected": String(idx === activeIndex),
        onClick: () => {
          activeModal?.close();
          item.action();
        },
        onMouseEnter: () => {
          activeIndex = idx;
          updateHighlight();
        }
      },
      h("span", { class: "omni-item-icon" }, icon(item.icon || "arrowRight")),
      h("div", { class: "omni-item-content" },
        h("div", { class: "omni-item-title" }, item.title),
        item.subtitle ? h("div", { class: "omni-item-sub" }, item.subtitle) : null
      ),
      item.badge ? h("span", { class: "omni-item-badge" }, item.badge) : null
      );

      resultsBox.append(el);
    });

    const activeEl = resultsBox.querySelector(".omni-item.is-active");
    activeEl?.scrollIntoView({ block: "nearest" });
  }

  function updateHighlight() {
    const all = resultsBox.querySelectorAll(".omni-item");
    all.forEach((el, i) => {
      const on = i === activeIndex;
      el.classList.toggle("is-active", on);
      el.setAttribute("aria-selected", String(on));
    });
    all[activeIndex]?.scrollIntoView({ block: "nearest" });
  }

  function getDefaultItems() {
    const list = [];
    const deptsGroup = t("core.nav.departments", { default: "Departments" });
    const actionsGroup = t("core.nav.quick_actions", { default: "Quick Navigation & Actions" });

    // Departments
    for (const d of depts) {
      list.push({
        group: deptsGroup,
        title: d.name,
        subtitle: t(`core.env.${d.environment}`, { default: d.environment }),
        icon: d.icon || "hospital",
        badge: t("core.nav.jump", { default: "Jump" }),
        action: () => navigate(`/d/${d.id}`)
      });
    }

    // Quick Actions
    list.push({
      group: actionsGroup,
      title: t("patients.title", { default: "Patients" }),
      subtitle: t("patients.subtitle", { default: "Search, register and manage patient records" }),
      icon: "users",
      action: () => navigate(p.center_wide ? "/center/patients" : "/patients")
    });

    list.push({
      group: actionsGroup,
      title: t("appointments.title", { default: "Appointments" }),
      subtitle: t("appointments.menu", { default: "Daily schedules and calendar bookings" }),
      icon: "calendar",
      action: () => navigate(p.center_wide ? "/center/appointments" : "/appointments")
    });

    if (p.can?.("billing.view") || p.center_wide) {
      list.push({
        group: actionsGroup,
        title: t("billing.title", { default: "Invoices & Billing" }),
        subtitle: t("billing.subtitle", { default: "Patient billing, payments, and receipts" }),
        icon: "creditCard",
        action: () => navigate(p.center_wide ? "/center/billing" : "/billing")
      });
    }

    return list;
  }

  let debounceTimer = null;
  async function performSearch() {
    const q = input.value.trim();
    if (q.length < 2) {
      items = getDefaultItems();
      activeIndex = 0;
      renderList();
      return;
    }

    const currentSeq = ++searchSeq;
    const patGroup = t("patients.title", { default: "Patients" });

    try {
      const res = await api.get("/patients", { query: { q, per_page: 6 } });
      if (currentSeq !== searchSeq) return;

      const patients = res.items || (Array.isArray(res) ? res : []);
      const matches = patients.map((pat) => ({
        group: patGroup,
        title: pat.full_name || `${pat.first_name || ""} ${pat.last_name || ""}`.trim(),
        subtitle: [
          pat.display_code || pat.code,
          pat.phone,
          pat.date_of_birth ? formatDate(pat.date_of_birth, { year: "always" }) : null
        ].filter(Boolean).join(" · "),
        icon: "user",
        badge: t("patients.profile.view", { default: "Open Profile" }),
        action: () => navigate(p.center_wide ? `/center/patients/${pat.id}` : `/patients/${pat.id}`)
      }));

      // Also filter departments by name
      const matchedDepts = depts.filter((d) => d.name.toLowerCase().includes(q.toLowerCase())).map((d) => ({
        group: t("core.nav.departments", { default: "Departments" }),
        title: d.name,
        subtitle: d.environment,
        icon: d.icon || "hospital",
        badge: t("core.nav.jump", { default: "Jump" }),
        action: () => navigate(`/d/${d.id}`)
      }));

      items = [...matches, ...matchedDepts];
      activeIndex = 0;
      renderList();
    } catch {
      // offline or error fallback
      items = getDefaultItems().filter((item) => item.title.toLowerCase().includes(q.toLowerCase()));
      activeIndex = 0;
      renderList();
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(performSearch, 200);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (items.length > 0) {
        activeIndex = (activeIndex + 1) % items.length;
        updateHighlight();
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (items.length > 0) {
        activeIndex = (activeIndex - 1 + items.length) % items.length;
        updateHighlight();
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (items[activeIndex]) {
        activeModal?.close();
        items[activeIndex].action();
      }
    } else if (e.key === "Escape") {
      activeModal?.close();
    }
  });

  const footer = h("div", { class: "omni-footer" },
    h("span", { class: "omni-key-hint" }, h("kbd", "↑↓"), " " + t("core.search.navigate", { default: "navigate" })),
    h("span", { class: "omni-key-hint" }, h("kbd", "↵"), " " + t("core.search.select", { default: "select" })),
    h("span", { class: "omni-key-hint" }, h("kbd", "ESC"), " " + t("core.search.close", { default: "close" }))
  );

  const container = h("div", { class: "omni-modal" },
    h("div", { class: "omni-search-bar" },
      icon("search"),
      input
    ),
    resultsBox,
    footer
  );

  items = getDefaultItems();
  renderList();

  activeModal = openModal({
    body: container,
    size: "md",
    onClose: () => { activeModal = null; }
  });

  setTimeout(() => input.focus(), 50);
}
