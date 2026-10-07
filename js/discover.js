// =====================================================================
// Descoberta: ecrã de boas-vindas e lista "No mapa".
// =====================================================================

import { PROJECT, FEATURED, USO_COLORS, STORAGE } from "./config.js";
import { normalize, escapeHtml, fmtNumber, debounce } from "./utils.js";

let map = null;
let manifest = null;
let ctx = {};          // { onSelectDam, onHoverDam, allDams }
let sortField = "name";
let listDamId = null;

// ---------------------------------------------------------------------
// Boas-vindas
// ---------------------------------------------------------------------

export function initDiscover(opts) {
  Object.assign(ctx, opts);
  map = opts.map;
  manifest = opts.manifest;

  const welcome = document.getElementById("welcome");
  document.getElementById("welcome-close")?.addEventListener("click", hideWelcome);
  welcome?.addEventListener("click", (e) => { if (e.target === welcome) hideWelcome(); });

  fillWelcome();
  wireList();
  map.on("moveend", debounce(refreshList, 200));
  refreshList();   // preenche já a lista (o moveend inicial já passou)

  // Primeira visita (com try/catch, por causa do modo privado/navegação restrita).
  let seen = false;
  try { seen = localStorage.getItem(STORAGE.welcome) === "1"; } catch (_) { seen = false; }
  if (!seen) showWelcome();
}

export function showWelcome() {
  const w = document.getElementById("welcome");
  if (w) w.hidden = false;
}
export function hideWelcome() {
  const w = document.getElementById("welcome");
  if (w) w.hidden = true;
  try { localStorage.setItem(STORAGE.welcome, "1"); } catch (_) { /* ignora */ }
}
export function toggleWelcome() {
  const w = document.getElementById("welcome");
  if (w && !w.hidden) hideWelcome(); else showWelcome();
}

function fillWelcome() {
  document.getElementById("welcome-title").textContent = PROJECT.name;
  document.getElementById("welcome-sub").textContent = PROJECT.subtitle;

  const byC = manifest?.counts_by_country || {};
  const countries = manifest?.countries || Object.keys(byC);
  const sum = (k) => countries.reduce((a, c) => a + (byC[c]?.[k] || 0), 0);
  const stats = [
    [sum("dams"), "barragens"],
    [sum("reservoirs"), "albufeiras"],
    [sum("plants"), "centrais hidroelétricas"],
    [countries.join(" + ") || "—", "países"],
  ];
  document.getElementById("welcome-stats").innerHTML = stats
    .map(([n, l]) => `<div class="stat"><div class="n">${typeof n === "number" ? fmtNumber(n) : escapeHtml(String(n))}</div><div class="l">${escapeHtml(l)}</div></div>`)
    .join("");

  const box = document.getElementById("featured");
  box.innerHTML = "";
  const dams = ctx.allDams?.() || [];
  for (const wanted of FEATURED) {
    const dam = findDams(dams, wanted);
    if (!dam) continue;
    const btn = document.createElement("button");
    btn.textContent = dam.properties.name || dam.properties.dam_id;
    btn.addEventListener("click", () => {
      hideWelcome();
      ctx.onSelectDam?.(dam.properties.dam_id, dam.geometry.coordinates);
    });
    box.appendChild(btn);
  }
}

/** Encontra uma barragem por `dam_id` (ex.: "way/123") ou por nome. */
function findDams(dams, wanted) {
  if (wanted.id) return dams.find((d) => d.properties.dam_id === wanted.id);
  const w = normalize(wanted.name || "");
  if (!w) return null;
  return dams.find((d) => {
    const p = d.properties;
    return [p.name, p.name_pt, p.name_es].some((n) => normalize(n || "").includes(w));
  });
}

// ---------------------------------------------------------------------
// Lista "No mapa"
// ---------------------------------------------------------------------

function wireList() {
  // A ordenação é ligada pelo main.js (via painel), para evitar duplicação.
}

export function setSort(field) {
  sortField = field;
  refreshList();
}

export function refreshList() {
  const ul = document.getElementById("map-list");
  const note = document.getElementById("list-note");
  if (!ul || !map) return;

  const bounds = map.getBounds();
  const dams = (ctx.allDams?.() || []).filter((d) => {
    const [lon, lat] = d.geometry.coordinates;
    return bounds.contains([lon, lat]);
  });

  const key = (d) => {
    const p = d.properties;
    if (sortField === "name") return normalize(p.name || "zzz");
    if (sortField === "height") return -(Number(p.height) || 0);
    if (sortField === "plant_power_mw") return -(Number(p.plant_power_mw) || 0);
    if (sortField === "start_date") return -(Number(String(p.start_date || "").slice(0, 4)) || 0);
    return 0;
  };
  dams.sort((a, b) => (typeof key(a) === "number" ? key(a) - key(b) : String(key(a)).localeCompare(String(key(b)), "pt")));

  const LIMIT = 200;
  const shown = dams.slice(0, LIMIT);
  ul.innerHTML = shown.map((d) => {
    const p = d.properties;
    const color = USO_COLORS[p.uso] || USO_COLORS["desconhecido"];
    const meta = p.height != null ? `${fmtNumber(p.height)} m` : (p.plant_power_mw != null ? `${fmtNumber(p.plant_power_mw)} MW` : "");
    return `<li data-id="${escapeHtml(p.dam_id)}" class="${p.dam_id === listDamId ? "selected" : ""}">
      <span class="ml-dot" style="background:${color}"></span>
      <span class="ml-name">${escapeHtml(p.name || p.name_pt || p.name_es || "Barragem sem nome")}</span>
      <span class="ml-meta">${escapeHtml(meta)}</span>
    </li>`;
  }).join("");

  note.textContent = dams.length > LIMIT
    ? `Mostrando ${LIMIT} de ${fmtNumber(dams.length)}. Aproxima para ver mais.`
    : `${fmtNumber(dams.length)} barragens visíveis.`;

  ul.querySelectorAll("li").forEach((li) => {
    const id = li.dataset.id;
    li.addEventListener("click", () => {
      const d = (ctx.allDams?.() || []).find((x) => x.properties.dam_id === id);
      if (d) ctx.onSelectDam?.(id, d.geometry.coordinates);
    });
    li.addEventListener("mouseenter", () => { li.classList.add("hover"); ctx.onHoverDam?.(id); });
    li.addEventListener("mouseleave", () => { li.classList.remove("hover"); ctx.onHoverDam?.(null); });
  });
}

/** Marca a barragem selecionada na lista e faz scroll até ela. */
export function markSelected(damId) {
  listDamId = damId || null;
  document.querySelectorAll("#map-list li").forEach((li) => {
    const on = li.dataset.id === listDamId;
    li.classList.toggle("selected", on);
    if (on) li.scrollIntoView({ block: "nearest" });
  });
}
