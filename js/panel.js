// =====================================================================
// Interface: gaveta (camadas/filtros/lista), legenda e ficha da barragem.
// =====================================================================

import { LAYERS, USO_COLORS, USO_LABELS, USO_ORDER, PALETTE } from "./config.js";
import { escapeHtml, fmtNumber } from "./utils.js";

let dom = {};
let hooks = {};
let currentFilters = { country: "all", usos: [...USO_ORDER], onlyNotion: false };

export function initPanel({ map, manifest, onFiltersChange, onLayerToggle, onListSort, onListShow, onOpenDamById }) {
  dom = {
    drawer: document.getElementById("drawer"),
    layerList: document.getElementById("layer-list"),
    legend: document.getElementById("legend"),
    filterCountry: document.getElementById("filter-country"),
    filterUso: document.getElementById("filter-uso"),
    filterNotion: document.getElementById("filter-notion"),
    detail: document.getElementById("detail"),
    detailBody: document.getElementById("detail-body"),
    btnLayers: document.getElementById("btn-layers"),
    drawerClose: document.getElementById("drawer-close"),
    listSort: document.getElementById("list-sort"),
  };
  hooks = { onFiltersChange, onLayerToggle, onListSort, onListShow, onOpenDamById };

  buildLayerList(manifest);
  buildUsoFilters();
  renderLegend(currentFilters.usos);
  wireFilters();
  wireDrawer();
}

// ---------------------------------------------------------------------
// Gaveta (camadas / lista)
// ---------------------------------------------------------------------

function wireDrawer() {
  dom.btnLayers?.addEventListener("click", () => toggleDrawer());
  dom.drawerClose?.addEventListener("click", () => closeDrawer());
  document.querySelectorAll(".drawer-tabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
  });
  dom.listSort?.addEventListener("change", () => hooks.onListSort?.(dom.listSort.value));
}

export function openDrawer() {
  if (!dom.drawer) return;
  dom.drawer.hidden = false;
  dom.btnLayers?.setAttribute("aria-expanded", "true");
}
export function closeDrawer() {
  if (!dom.drawer) return;
  dom.drawer.hidden = true;
  dom.btnLayers?.setAttribute("aria-expanded", "false");
}
export function toggleDrawer() {
  if (!dom.drawer) return;
  if (dom.drawer.hidden) openDrawer(); else closeDrawer();
}
export function openListTab() { openDrawer(); selectTab("lista"); }

function selectTab(name) {
  document.querySelectorAll(".drawer-tabs .tab").forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", String(on));
  });
  for (const n of ["camadas", "lista"]) {
    const el = document.getElementById(`tab-${n}`);
    if (el) el.hidden = n !== name;
  }
  if (name === "lista") hooks.onListShow?.();
}

// ---------------------------------------------------------------------
// Camadas
// ---------------------------------------------------------------------

function buildLayerList(manifest) {
  const available = manifest?.layers || {};
  dom.layerList.innerHTML = "";
  for (const def of LAYERS) {
    if (def.internal) continue;
    const hasData = Array.isArray(available[def.key]) && available[def.key].length > 0;
    if (!hasData) continue;

    const li = document.createElement("li");
    const id = `layer-${def.key}`;
    const swClass = def.legendSwatch === "line" ? "line" : (def.legendSwatch === "polygon" ? "polygon" : "");
    li.innerHTML = `
      <label for="${id}">
        <input type="checkbox" id="${id}" ${def.default ? "checked" : ""} />
        <span class="swatch ${swClass}" style="background:${swatchColor(def)}"></span>
        <span>${escapeHtml(def.label)}${def.future ? " <em>(futuro)</em>" : ""}</span>
      </label>
      ${def.minzoom > 0 ? `<span class="minzoom" title="Só aparece a partir deste zoom">z${def.minzoom}+</span>` : ""}
    `;
    const checkbox = li.querySelector("input");
    checkbox.addEventListener("change", () => hooks.onLayerToggle(def.key, checkbox.checked));
    dom.layerList.appendChild(li);
  }
}

function swatchColor(def) {
  if (def.kind === "dams") return USO_COLORS["hidroelétrica"];
  return def.color || "#888";
}

// ---------------------------------------------------------------------
// Filtros + legenda
// ---------------------------------------------------------------------

function buildUsoFilters() {
  dom.filterUso.innerHTML = "";
  for (const uso of USO_ORDER) {
    const label = document.createElement("label");
    const id = `uso-${USO_ORDER.indexOf(uso)}`;
    label.innerHTML = `
      <input type="checkbox" id="${id}" checked />
      <span class="dot" style="background:${USO_COLORS[uso]}"></span>
      <span>${escapeHtml(USO_LABELS[uso])}</span>
    `;
    label.querySelector("input").addEventListener("change", readFilters);
    dom.filterUso.appendChild(label);
  }
}

function wireFilters() {
  dom.filterCountry?.addEventListener("change", readFilters);
  dom.filterNotion?.addEventListener("change", readFilters);
}

function readFilters() {
  const usos = USO_ORDER.filter((u) => document.getElementById(`uso-${USO_ORDER.indexOf(u)}`)?.checked);
  currentFilters = { country: dom.filterCountry.value, usos, onlyNotion: dom.filterNotion.checked };
  renderLegend(usos);
  hooks.onFiltersChange(currentFilters);
}

/** Legenda compacta: só as categorias de uso ativas + rede relacionada/Notion. */
export function renderLegend(activeUsos = [...USO_ORDER]) {
  const items = USO_ORDER.filter((u) => activeUsos.includes(u))
    .map((u) => `<span class="lg"><span class="swatch" style="background:${USO_COLORS[u]}"></span>${escapeHtml(USO_LABELS[u])}</span>`);
  items.push(`<span class="lg"><span class="swatch line" style="background:${PALETTE.related}"></span>Rede relacionada</span>`);
  dom.legend.innerHTML = items.join("");
}

// ---------------------------------------------------------------------
// Ficha da barragem
// ---------------------------------------------------------------------

export function showDetail(dam) {
  const p = dam.properties || {};
  const title = p.name || p.name_pt || p.name_es || "Barragem sem nome";
  const uso = p.uso || "desconhecido";
  const usoColor = USO_COLORS[uso] || USO_COLORS["desconhecido"];

  // Capa (foto do Notion) com fallback gráfico na cor do uso.
  const hero = `
    <div class="ficha-hero">
      <div class="hero-fallback">${heroSvg(usoColor)}</div>
      ${p.notion_foto ? `<img src="${escapeHtml(p.notion_foto)}" alt="" loading="lazy"
            onerror="this.remove()" />` : ""}
    </div>`;

  const chips = [`<span class="chip">${escapeHtml(p.country || "")}</span>`];
  if (p.river) chips.push(`<span class="chip">${escapeHtml(p.river)}</span>`);
  chips.push(`<span class="chip uso" style="background:${usoColor}">${escapeHtml(USO_LABELS[uso] || uso)}</span>`);

  const facts = [];
  const addFact = (k, v) => { if (v != null && v !== "") facts.push(`<div class="fact"><div class="k">${escapeHtml(k)}</div><div class="v">${v}</div></div>`); };
  addFact("Altura", p.height != null ? `${fmtNumber(p.height)} m` : null);
  addFact("Ano", p.start_date);
  addFact("Albufeira", p.reservoir_area_ha != null ? `${fmtNumber(p.reservoir_area_ha)} ha` : null);
  addFact("Potência", p.plant_power_mw != null ? `${fmtNumber(p.plant_power_mw)} MW` : null);

  const notionBtn = p.notion_url
    ? `<a class="btn notion block" href="${escapeHtml(p.notion_url)}" target="_blank" rel="noopener">Ver no Notion</a>` : "";
  const resumo = p.notion_resumo ? `<p class="muted">${escapeHtml(p.notion_resumo)}</p>` : "";

  const links = [];
  links.push(`<a class="icon-link" href="https://www.openstreetmap.org/${p.osm_type}/${p.osm_id}" target="_blank" rel="noopener">OSM</a>`);
  if (p.wikidata) links.push(`<a class="icon-link" href="https://www.wikidata.org/wiki/${encodeURIComponent(p.wikidata)}" target="_blank" rel="noopener">Wikidata</a>`);
  if (p.wikipedia) {
    const [lang, ...rest] = String(p.wikipedia).split(":");
    const article = rest.join(":") || lang;
    links.push(`<a class="icon-link" href="https://${lang}.wikipedia.org/wiki/${encodeURIComponent(article)}" target="_blank" rel="noopener">Wikipédia</a>`);
  }

  dom.detailBody.innerHTML = `
    ${hero}
    <div class="ficha-body">
      <h2 class="ficha-title">${escapeHtml(title)}</h2>
      <div class="chips">${chips.join("")}</div>
      ${resumo}
      ${facts.length ? `<div class="facts">${facts.join("")}</div>` : ""}
      ${p.reservoir_name ? `<p class="small muted">Albufeira: ${escapeHtml(p.reservoir_name)}</p>` : ""}
      ${notionBtn}
      <div id="detail-related" class="related-box"><span class="muted small">A procurar rede elétrica relacionada…</span></div>

      <div class="contrib">
        <h3>Contribuir · ligar ao Notion</h3>
        <p class="small muted">Cola este ID no campo <strong>ID Mapa</strong> da página no Notion.</p>
        <code id="dam-id">${escapeHtml(p.dam_id || "")}</code>
        <button class="btn block" id="copy-id" type="button">Copiar ID</button>
      </div>

      <details class="tech">
        <summary>Detalhes técnicos</summary>
        <pre>${escapeHtml(techText(p))}</pre>
      </details>

      <div class="ficha-footer">${links.join("")}</div>
    </div>
  `;

  dom.detail.hidden = false;
  // No telemóvel, abre a meio (bottom sheet).
  if (matchMedia("(max-width: 780px)").matches) setSheet("half");
  document.getElementById("copy-id")?.addEventListener("click", (e) => copyId(p.dam_id, e.currentTarget));
}

function heroSvg(color) {
  return `<svg viewBox="0 0 400 150" preserveAspectRatio="xMidYMax slice" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="${color}" stop-opacity="0.10"/>
        <stop offset="1" stop-color="${color}" stop-opacity="0.30"/>
      </linearGradient>
    </defs>
    <rect width="400" height="150" fill="url(#g)"/>
    <path d="M0 120 h400 v30 H0 z" fill="${color}" opacity="0.18"/>
    <path d="M60 55 h70 l30 65 H30 z" fill="${color}" opacity="0.55"/>
    <path d="M150 96 q30 -14 60 0 t60 0 t60 0" fill="none" stroke="${color}" stroke-width="4" opacity="0.5"/>
  </svg>`;
}

function techText(p) {
  const lines = [
    `ID Mapa: ${p.dam_id || "—"}`,
    `OSM: ${p.osm_type}/${p.osm_id}`,
    `Operador: ${p.operator || "—"}`,
    `Altitude: ${p.ele != null ? p.ele + " m" : "—"}`,
    `Classificação (uso): ${p.uso || "—"}`,
    `Fonte do uso: ${p.uso_fonte || "—"}`,
  ];
  if (p.reservoir_name) lines.push(`Albufeira associada: ${p.reservoir_name}${p.reservoir_area_ha != null ? ` (${p.reservoir_area_ha} ha)` : ""}`);
  return lines.join("\n");
}

export function setRelated(rel) {
  const box = document.getElementById("detail-related");
  if (!box) return;
  if (!rel || (!rel.plantNames.length && !rel.nSubs && !rel.nLines)) {
    box.innerHTML = '<span class="muted small">Sem infraestrutura elétrica associada no OSM.</span>';
    return;
  }
  const plantNames = [...new Set(rel.plantNames)].filter(Boolean);
  const parts = [];
  if (plantNames.length) parts.push(`<div class="small"><strong>Centrais:</strong> ${plantNames.map(escapeHtml).join(", ")}</div>`);
  if (rel.nSubs) parts.push(`<div class="small"><strong>Subestações:</strong> ${rel.nSubs}</div>`);
  if (rel.nLines) parts.push(`<div class="small"><strong>Linhas elétricas:</strong> ${rel.nLines}</div>`);
  box.innerHTML = `<div class="related-title">⚡ Rede relacionada (a âmbar no mapa)</div>${parts.join("")}`;
}

function copyId(text, btn) {
  const done = () => { const o = btn.textContent; btn.textContent = "Copiado ✓"; setTimeout(() => { btn.textContent = o; }, 1500); };
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  else fallbackCopy(text, done);
}
function fallbackCopy(text, done) {
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (_) { /* ignora */ }
  document.body.removeChild(ta);
}

export function hideDetail() {
  dom.detail.hidden = true;
  dom.detail.removeAttribute("data-sheet");
}

/** Define a posição da ficha no telemóvel (collapsed/half/full). */
export function setSheet(state) {
  if (dom.detail) dom.detail.dataset.sheet = state;
}

export function showReservoir(p) {
  const name = p.name || p.name_pt || p.name_es || "Albufeira sem nome";
  const usage = p.usage || p.reservoir_type || null;
  const facts = [];
  if (p.area_ha != null) facts.push(`<div class="fact"><div class="k">Área</div><div class="v">${fmtNumber(p.area_ha)} ha</div></div>`);
  if (p.dam_id) facts.push(`<div class="fact"><div class="k">Barragem</div><div class="v">associada</div></div>`);

  dom.detailBody.innerHTML = `
    <div class="ficha-hero"><div class="hero-fallback">${heroSvg(PALETTE.water)}</div></div>
    <div class="ficha-body">
      <h2 class="ficha-title">${escapeHtml(name)}</h2>
      <div class="chips">
        <span class="chip">${escapeHtml(p.country || "")}</span>
        <span class="chip uso" style="background:${PALETTE.water}">Albufeira</span>
        ${usage ? `<span class="chip">${escapeHtml(usage)}</span>` : ""}
      </div>
      ${facts.length ? `<div class="facts">${facts.join("")}</div>` : ""}
      ${p.dam_id
        ? `<button class="btn primary block" id="res-dam" type="button">Ver a barragem</button>`
        : `<p class="muted small">Sem barragem associada no OpenStreetMap.</p>`}
    </div>`;
  dom.detail.hidden = false;
  if (matchMedia("(max-width: 780px)").matches) setSheet("half");
  document.getElementById("res-dam")?.addEventListener("click", () => hooks.onOpenDamById?.(p.dam_id));
}

/** Mostra a data dos dados + contagens (usado no ecrã de boas-vindas). */
export function dataInfoHtml(manifest) {
  if (!manifest) return "Informação dos dados indisponível.";
  const when = manifest.generated_at ? new Date(manifest.generated_at).toLocaleDateString("pt-PT") : "—";
  return `Dados atualizados a <strong>${escapeHtml(when)}</strong>.`;
}
