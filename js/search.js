// =====================================================================
// Pesquisa por nome de barragem, albufeira ou rio (ignora acentos).
// =====================================================================

import { normalize, escapeHtml, debounce } from "./utils.js";

let index = [];
let dom = {};
let hooks = {};
let activeIndex = -1;
let results = [];

export function initSearch({ onSelectDam, onSelectReservoir }) {
  dom = {
    input: document.getElementById("search-input"),
    list: document.getElementById("search-results"),
  };
  hooks = { onSelectDam, onSelectReservoir };

  dom.input.addEventListener("input", debounce(onInput, 150));
  dom.input.addEventListener("keydown", onKeyDown);
  document.addEventListener("click", (e) => {
    if (!dom.list.contains(e.target) && e.target !== dom.input) hideResults();
  });
}

/** Constrói o índice de pesquisa a partir das features carregadas. */
export function setData(dams, reservoirs) {
  index = [];
  const push = (type, name, coords, extra = {}) => {
    if (!name) return;
    index.push({
      type, name,
      search: normalize(name),
      coords,
      ...extra,
    });
  };

  for (const d of dams || []) {
    const p = d.properties || {};
    const names = new Set([p.name, p.name_pt, p.name_es].filter(Boolean));
    const river = p.river || "";
    for (const n of names) {
      push("dam", n, d.geometry.coordinates, { damId: p.dam_id, river });
    }
    if (river) push("rio", river, d.geometry.coordinates, { damId: p.dam_id });
  }

  for (const r of reservoirs || []) {
    const p = r.properties || {};
    for (const n of new Set([p.name, p.name_pt, p.name_es].filter(Boolean))) {
      const c = centroid(r.geometry);
      if (c) push("reservoir", n, c, { reservoirId: p.reservoir_id, damId: p.dam_id || null });
    }
  }
}

function centroid(geometry) {
  const coords = geometry?.coordinates;
  if (!coords) return null;
  const flat = [];
  const walk = (arr) => {
    if (typeof arr[0] === "number") flat.push(arr);
    else arr.forEach(walk);
  };
  walk(coords);
  if (!flat.length) return null;
  const sum = flat.reduce((a, c) => [a[0] + c[0], a[1] + c[1]], [0, 0]);
  return [sum[0] / flat.length, sum[1] / flat.length];
}

function onInput() {
  const q = normalize(dom.input.value);
  if (q.length < 2) return hideResults();

  const scored = [];
  for (const item of index) {
    let score = -1;
    if (item.search === q) score = 0;
    else if (item.search.startsWith(q)) score = 1;
    else if (item.search.includes(q)) score = 2;
    if (score >= 0) scored.push([score, item]);
  }
  scored.sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name, "pt"));

  const seen = new Set();
  results = [];
  for (const [, item] of scored) {
    const key = `${item.type}:${item.name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    results.push(item);
    if (results.length >= 12) break;
  }
  renderResults();
}

const KIND_LABEL = { dam: "Barragem", reservoir: "Albufeira", rio: "Rio" };

function renderResults() {
  if (!results.length) return hideResults();
  activeIndex = -1;
  dom.list.innerHTML = results.map((r, i) => `
    <li role="option" data-i="${i}" aria-selected="false">
      <span>${escapeHtml(r.name)}</span>
      <span class="sr-kind">${KIND_LABEL[r.type] || ""}</span>
    </li>
  `).join("");
  dom.list.hidden = false;
  dom.list.querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", () => choose(Number(li.dataset.i)));
  });
}

function hideResults() {
  dom.list.hidden = true;
  dom.list.innerHTML = "";
  results = [];
}

function onKeyDown(e) {
  if (dom.list.hidden) return;
  if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
  else if (e.key === "Enter") { e.preventDefault(); if (activeIndex >= 0) choose(activeIndex); }
  else if (e.key === "Escape") { hideResults(); }
}

function move(delta) {
  const items = [...dom.list.querySelectorAll("li")];
  if (!items.length) return;
  activeIndex = (activeIndex + delta + items.length) % items.length;
  items.forEach((li, i) => li.setAttribute("aria-selected", String(i === activeIndex)));
  items[activeIndex].scrollIntoView({ block: "nearest" });
}

function choose(i) {
  const item = results[i];
  if (!item) return;
  hideResults();
  dom.input.value = item.name;
  if (item.type === "dam" || item.type === "rio") {
    hooks.onSelectDam(item.damId, item.coords);
  } else {
    hooks.onSelectReservoir(item);
  }
}
