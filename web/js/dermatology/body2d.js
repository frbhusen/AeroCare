// 2D Interactive Anatomical Body Map for Dermatology & Laser Hair Removal
// Supports Anterior (Front) and Posterior (Back) views with clickable regions,
// hover tooltips, quick-select package presets, and removable selection tags.
import { t } from "../core/index.js";

const NS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v != null) n.setAttribute(k, String(v));
  }
  return n;
}

// Region label resolver: checks translation dictionary then falls back to formatted code
export function getRegionLabel(code) {
  const key = `dermatology.region.${code}`;
  const translated = t(key);
  if (translated && translated !== key) return translated;
  return String(code || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Anatomical region definitions for viewBox 0 0 200 460
// Front view: viewer left is patient's right; viewer right is patient's left.
const FRONT_REGIONS = [
  // Head & Neck
  { id: "scalp", tag: "path", attrs: { d: "M84 28 C84 12 116 12 116 28 C110 26 90 26 84 28 Z" } },
  { id: "forehead", tag: "path", attrs: { d: "M83 29 C90 27 110 27 117 29 C118 39 82 39 83 29 Z" } },
  { id: "cheeks", tag: "path", attrs: { d: "M81 39 C78 48 81 56 89 57 C94 57 95 48 93 39 Z" } },
  { id: "cheeks", tag: "path", attrs: { d: "M119 39 C122 48 119 56 111 57 C106 57 105 48 107 39 Z" } },
  { id: "upper_lip", tag: "path", attrs: { d: "M92 51 C96 50 104 50 108 51 C107 57 93 57 92 51 Z" } },
  { id: "chin", tag: "path", attrs: { d: "M91 58 C96 57 104 57 109 58 C107 68 93 68 91 58 Z" } },
  { id: "neck", tag: "path", attrs: { d: "M90 69 L110 69 L114 86 L86 86 Z" } },

  // Upper Limbs
  { id: "shoulders", tag: "path", attrs: { d: "M86 86 L68 90 C58 92 58 100 63 108 L76 102 L83 88 Z" } },
  { id: "shoulders", tag: "path", attrs: { d: "M114 86 L132 90 C142 92 142 100 137 108 L124 102 L117 88 Z" } },
  { id: "underarm_right", tag: "ellipse", attrs: { cx: 73, cy: 112, rx: 6, ry: 8 } },
  { id: "underarm_left", tag: "ellipse", attrs: { cx: 127, cy: 112, rx: 6, ry: 8 } },
  { id: "upper_arm_right", tag: "path", attrs: { d: "M63 108 C57 120 53 140 50 160 L64 160 C68 140 72 122 76 106 Z" } },
  { id: "upper_arm_left", tag: "path", attrs: { d: "M137 108 C143 120 147 140 150 160 L136 160 C132 140 128 122 124 106 Z" } },
  { id: "forearm_right", tag: "path", attrs: { d: "M50 162 C46 182 42 205 40 225 L53 225 C56 205 61 182 64 162 Z" } },
  { id: "forearm_left", tag: "path", attrs: { d: "M150 162 C154 182 158 205 160 225 L147 225 C144 205 139 182 136 162 Z" } },
  { id: "hands", tag: "path", attrs: { d: "M40 227 C36 238 35 250 39 260 C44 262 50 258 52 250 C55 242 54 233 53 227 Z" } },
  { id: "hands", tag: "path", attrs: { d: "M160 227 C164 238 165 250 161 260 C156 262 150 258 148 250 C145 242 146 233 147 227 Z" } },

  // Trunk
  { id: "chest", tag: "path", attrs: { d: "M84 87 L116 87 L124 102 C125 116 123 132 121 144 L79 144 C77 132 75 116 76 102 Z" } },
  { id: "abdomen", tag: "path", attrs: { d: "M79 146 L121 146 C123 160 124 175 122 186 L78 186 C76 175 77 160 79 146 Z" } },
  { id: "bikini", tag: "path", attrs: { d: "M77 188 L123 188 C121 204 112 218 102 226 L98 226 C88 218 79 204 77 188 Z" } },

  // Lower Limbs
  { id: "thigh_right", tag: "path", attrs: { d: "M76 195 C73 225 73 260 76 295 L96 295 C98 260 99 228 98 225 C92 220 84 210 76 195 Z" } },
  { id: "thigh_left", tag: "path", attrs: { d: "M124 195 C127 225 127 260 124 295 L104 295 C102 260 101 228 102 225 C108 220 116 210 124 195 Z" } },
  { id: "lower_leg_right", tag: "path", attrs: { d: "M76 298 L96 298 C96 330 95 365 92 400 L81 400 C78 365 75 330 76 298 Z" } },
  { id: "lower_leg_left", tag: "path", attrs: { d: "M104 298 L124 298 C125 330 122 365 119 400 L108 400 C105 365 104 330 104 298 Z" } },
  { id: "feet", tag: "path", attrs: { d: "M80 403 L93 403 C95 418 95 428 84 430 C76 430 76 418 80 403 Z" } },
  { id: "feet", tag: "path", attrs: { d: "M107 403 L120 403 C124 418 124 428 116 430 C105 430 105 418 107 403 Z" } },
];

// Back view: viewer left is patient's left; viewer right is patient's right.
const BACK_REGIONS = [
  // Head & Neck
  { id: "scalp", tag: "path", attrs: { d: "M83 24 C83 11 117 11 117 24 C120 46 80 46 83 24 Z" } },
  { id: "neck", tag: "path", attrs: { d: "M89 54 L111 54 L115 86 L85 86 Z" } },

  // Upper Limbs
  { id: "shoulders", tag: "path", attrs: { d: "M85 86 L68 90 C58 92 58 100 63 108 L76 102 L83 88 Z" } },
  { id: "shoulders", tag: "path", attrs: { d: "M115 86 L132 90 C142 92 142 100 137 108 L124 102 L117 88 Z" } },
  { id: "upper_arm_left", tag: "path", attrs: { d: "M63 108 C57 120 53 140 50 160 L64 160 C68 140 72 122 76 106 Z" } },
  { id: "upper_arm_right", tag: "path", attrs: { d: "M137 108 C143 120 147 140 150 160 L136 160 C132 140 128 122 124 106 Z" } },
  { id: "forearm_left", tag: "path", attrs: { d: "M50 162 C46 182 42 205 40 225 L53 225 C56 205 61 182 64 162 Z" } },
  { id: "forearm_right", tag: "path", attrs: { d: "M150 162 C154 182 158 205 160 225 L147 225 C144 205 139 182 136 162 Z" } },
  { id: "hands", tag: "path", attrs: { d: "M40 227 C36 238 35 250 39 260 C44 262 50 258 52 250 C55 242 54 233 53 227 Z" } },
  { id: "hands", tag: "path", attrs: { d: "M160 227 C164 238 165 250 161 260 C156 262 150 258 148 250 C145 242 146 233 147 227 Z" } },

  // Trunk
  { id: "upper_back", tag: "path", attrs: { d: "M84 87 L116 87 L124 102 C125 116 123 132 121 144 L79 144 C77 132 75 116 76 102 Z" } },
  { id: "lower_back", tag: "path", attrs: { d: "M79 146 L121 146 C123 160 124 174 122 184 L78 184 C76 174 77 160 79 146 Z" } },

  // Buttocks
  { id: "buttocks", tag: "path", attrs: { d: "M78 186 L99 186 L99 225 C88 225 78 214 75 198 Z" } },
  { id: "buttocks", tag: "path", attrs: { d: "M101 186 L122 186 L125 198 C122 214 112 225 101 225 Z" } },

  // Lower Limbs
  { id: "thigh_left", tag: "path", attrs: { d: "M75 198 C73 225 73 260 76 295 L96 295 C98 260 99 228 99 225 C90 225 80 215 75 198 Z" } },
  { id: "thigh_right", tag: "path", attrs: { d: "M125 198 C127 225 127 260 124 295 L104 295 C102 260 101 228 101 225 C110 225 120 215 125 198 Z" } },
  { id: "lower_leg_left", tag: "path", attrs: { d: "M76 298 L96 298 C96 330 95 365 92 400 L81 400 C78 365 75 330 76 298 Z" } },
  { id: "lower_leg_right", tag: "path", attrs: { d: "M104 298 L124 298 C125 330 122 365 119 400 L108 400 C105 365 104 330 104 298 Z" } },
  { id: "feet", tag: "path", attrs: { d: "M80 403 L93 403 C95 418 95 428 84 430 C76 430 76 418 80 403 Z" } },
  { id: "feet", tag: "path", attrs: { d: "M107 403 L120 403 C124 418 124 428 116 430 C105 430 105 418 107 403 Z" } },
];

// Continuous smooth silhouette path contour for the mannequin body outline
const SIL_FRONT_D = "M100 12 C116 12 118 25 117 38 C120 48 117 56 111 60 C109 66 110 70 114 86 "
  + "C126 89 138 91 142 96 C144 100 140 106 137 110 C143 122 147 142 150 162 C154 182 158 205 160 226 "
  + "C165 238 166 252 161 262 C154 264 148 258 146 248 C144 235 146 226 147 225 L136 160 C132 140 128 122 126 112 "
  + "C125 130 124 165 122 186 C127 220 127 260 124 295 L124 298 C125 330 122 365 119 400 L120 403 C124 418 124 428 116 430 "
  + "C105 430 105 418 107 403 L108 400 C105 365 104 330 104 298 L104 295 C102 260 101 228 100 226 "
  + "C99 228 98 260 96 295 L96 298 C96 330 95 365 92 400 L93 403 C95 418 95 428 84 430 "
  + "C76 430 76 418 80 403 L81 400 C78 365 75 330 76 298 L76 295 C73 260 73 220 78 186 C76 165 75 130 74 112 "
  + "C72 122 68 140 64 160 L53 225 C54 226 56 235 54 248 C52 258 46 264 39 262 C34 252 35 238 40 226 "
  + "C42 205 46 182 50 162 C53 142 57 122 63 110 C60 106 56 100 58 96 C62 91 74 89 86 86 "
  + "C90 70 91 66 89 60 C83 56 80 48 83 38 C82 25 84 12 100 12 Z";

const SIL_BACK_D = SIL_FRONT_D; // Identical outer anatomical boundary

/**
 * Creates a single 2D anatomical SVG view (Front or Back)
 */
export function body2dView({ view = "front", isSelected, onToggle, onHover }) {
  const isFront = view === "front";
  const regions = isFront ? FRONT_REGIONS : BACK_REGIONS;

  const svg = el("svg", {
    viewBox: "20 0 160 445",
    class: "derm-body2d",
    role: "group",
    "aria-label": isFront ? t("dermatology.bodymap.front") : t("dermatology.bodymap.back"),
  });

  // Base human mannequin silhouette (soft medical mannequin style)
  const sil = el("path", {
    class: "derm-sil",
    d: isFront ? SIL_FRONT_D : SIL_BACK_D,
  });
  svg.append(sil);

  const shapeMap = new Map();

  for (const reg of regions) {
    const shape = el(reg.tag, {
      ...reg.attrs,
      class: "derm-region",
      tabindex: 0,
      role: "checkbox",
      "data-region": reg.id,
      "aria-label": getRegionLabel(reg.id),
    });

    const titleEl = el("title");
    titleEl.textContent = getRegionLabel(reg.id);
    shape.append(titleEl);

    shape.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      onToggle(reg.id);
    });

    shape.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onToggle(reg.id);
      }
    });

    shape.addEventListener("mouseenter", () => {
      onHover(reg.id, true);
    });

    shape.addEventListener("mouseleave", () => {
      onHover(reg.id, false);
    });

    if (!shapeMap.has(reg.id)) {
      shapeMap.set(reg.id, []);
    }
    shapeMap.get(reg.id).push(shape);
    svg.append(shape);
  }

  function refresh() {
    shapeMap.forEach((shapes, regionId) => {
      const active = isSelected(regionId);
      for (const s of shapes) {
        s.classList.toggle("is-selected", active);
        s.setAttribute("aria-checked", String(active));
      }
    });
  }

  function highlight(regionId, on) {
    const shapes = shapeMap.get(regionId);
    if (shapes) {
      for (const s of shapes) {
        s.classList.toggle("is-hover", on);
      }
    }
  }

  refresh();
  return { el: svg, refresh, highlight };
}

/**
 * Renders the full interactive 2D body map component with Front/Back figures,
 * hover guide, quick-select package presets, and removable tags.
 */
export function renderBody2D({ selected = new Set(), onChange } = {}) {
  const container = document.createElement("div");
  container.className = "derm-bodymap-card";

  // Normalize selected storage
  const isSelected = (reg) => {
    if (selected instanceof Set) return selected.has(reg);
    if (Array.isArray(selected)) return selected.includes(reg);
    return false;
  };

  const toggleRegion = (reg) => {
    if (selected instanceof Set) {
      if (selected.has(reg)) selected.delete(reg);
      else selected.add(reg);
    } else if (Array.isArray(selected)) {
      const idx = selected.indexOf(reg);
      if (idx >= 0) selected.splice(idx, 1);
      else selected.push(reg);
    }
    refreshAll();
    if (onChange) onChange(selected, reg);
  };

  const setRegions = (regs, shouldAdd) => {
    for (const r of regs) {
      if (selected instanceof Set) {
        if (shouldAdd) selected.add(r);
        else selected.delete(r);
      } else if (Array.isArray(selected)) {
        const idx = selected.indexOf(r);
        if (shouldAdd && idx < 0) selected.push(r);
        else if (!shouldAdd && idx >= 0) selected.splice(idx, 1);
      }
    }
    refreshAll();
    if (onChange) onChange(selected, regs);
  };

  // Header and hover info
  const header = document.createElement("div");
  header.className = "derm-bodymap-header";

  const infoEl = document.createElement("div");
  infoEl.className = "derm-bodymap-info";
  infoEl.textContent = t("dermatology.bodymap.hover_hint");
  header.append(infoEl);

  const handleHover = (regionId, on) => {
    if (on) {
      const label = getRegionLabel(regionId);
      infoEl.textContent = `✨ ${label}`;
      infoEl.classList.add("has-hover");
      frontView?.highlight(regionId, true);
      backView?.highlight(regionId, true);
    } else {
      infoEl.textContent = t("dermatology.bodymap.hover_hint");
      infoEl.classList.remove("has-hover");
      frontView?.highlight(regionId, false);
      backView?.highlight(regionId, false);
    }
  };

  // Quick package presets
  const presetsWrap = document.createElement("div");
  presetsWrap.className = "derm-presets-wrap";

  const presetsLabel = document.createElement("span");
  presetsLabel.className = "derm-presets-label";
  presetsLabel.textContent = t("dermatology.bodymap.presets");
  presetsWrap.append(presetsLabel);

  const presetsRow = document.createElement("div");
  presetsRow.className = "derm-presets";

  const PACKAGES = [
    { key: "face", regions: ["forehead", "cheeks", "upper_lip", "chin"] },
    { key: "underarms", regions: ["underarm_left", "underarm_right"] },
    { key: "arms", regions: ["upper_arm_left", "upper_arm_right", "forearm_left", "forearm_right", "hands"] },
    { key: "bikini", regions: ["bikini"] },
    { key: "legs", regions: ["thigh_left", "thigh_right", "lower_leg_left", "lower_leg_right", "feet"] },
    { key: "trunk", regions: ["chest", "abdomen"] },
    { key: "back", regions: ["upper_back", "lower_back"] },
  ];

  for (const pkg of PACKAGES) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "derm-preset-btn";
    btn.textContent = t(`dermatology.bodymap.preset.${pkg.key}`);
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      const allSelected = pkg.regions.every((r) => isSelected(r));
      setRegions(pkg.regions, !allSelected);
    });
    presetsRow.append(btn);
  }

  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "derm-preset-btn derm-preset-clear";
  clearBtn.textContent = `✕ ${t("dermatology.bodymap.clear")}`;
  clearBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    if (selected instanceof Set) selected.clear();
    else if (Array.isArray(selected)) selected.length = 0;
    refreshAll();
    if (onChange) onChange(selected, null);
  });
  presetsRow.append(clearBtn);
  presetsWrap.append(presetsRow);

  // Body Figures Row
  const figuresRow = document.createElement("div");
  figuresRow.className = "derm-figures-row";

  // Front View Column
  const frontCol = document.createElement("div");
  frontCol.className = "derm-figure-col";
  const frontTitle = document.createElement("span");
  frontTitle.className = "derm-figure-title";
  frontTitle.textContent = t("dermatology.bodymap.front");
  const frontView = body2dView({
    view: "front",
    isSelected,
    onToggle: toggleRegion,
    onHover: handleHover,
  });
  frontCol.append(frontTitle, frontView.el);

  // Back View Column
  const backCol = document.createElement("div");
  backCol.className = "derm-figure-col";
  const backTitle = document.createElement("span");
  backTitle.className = "derm-figure-title";
  backTitle.textContent = t("dermatology.bodymap.back");
  const backView = body2dView({
    view: "back",
    isSelected,
    onToggle: toggleRegion,
    onHover: handleHover,
  });
  backCol.append(backTitle, backView.el);

  figuresRow.append(frontCol, backCol);

  // Selected Areas Tags Container
  const selectedBar = document.createElement("div");
  selectedBar.className = "derm-selected-bar";

  const selectedHeader = document.createElement("div");
  selectedHeader.className = "derm-selected-header";

  const selectedTitle = document.createElement("span");
  const countBadge = document.createElement("span");
  countBadge.className = "derm-selected-badge";
  selectedHeader.append(selectedTitle, countBadge);

  const tagsContainer = document.createElement("div");
  tagsContainer.className = "derm-selected-tags";
  selectedBar.append(selectedHeader, tagsContainer);

  function refreshAll() {
    frontView.refresh();
    backView.refresh();

    // Update preset button active states
    const presetButtons = presetsRow.querySelectorAll(".derm-preset-btn:not(.derm-preset-clear)");
    PACKAGES.forEach((pkg, idx) => {
      const allOn = pkg.regions.length > 0 && pkg.regions.every((r) => isSelected(r));
      presetButtons[idx]?.classList.toggle("is-active", allOn);
    });

    // Update selected areas tags
    const list = selected instanceof Set ? [...selected] : (Array.isArray(selected) ? selected : []);
    countBadge.textContent = String(list.length);
    selectedTitle.textContent = t("dermatology.bodymap.selected", { count: list.length });

    tagsContainer.innerHTML = "";
    if (list.length === 0) {
      const empty = document.createElement("span");
      empty.className = "derm-selected-empty";
      empty.textContent = t("dermatology.bodymap.hover_hint");
      tagsContainer.append(empty);
    } else {
      for (const reg of list) {
        const tag = document.createElement("span");
        tag.className = "derm-tag";
        tag.textContent = getRegionLabel(reg);

        const rm = document.createElement("button");
        rm.type = "button";
        rm.className = "derm-tag-remove";
        rm.setAttribute("aria-label", `Remove ${getRegionLabel(reg)}`);
        rm.innerHTML = "&times;";
        rm.addEventListener("click", (e) => {
          e.stopPropagation();
          e.preventDefault();
          toggleRegion(reg);
        });

        tag.append(rm);
        tagsContainer.append(tag);
      }
    }
  }

  container.append(header, presetsWrap, figuresRow, selectedBar);
  refreshAll();

  return container;
}
