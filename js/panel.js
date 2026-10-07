// =====================================================================
// Interface: painel de camadas, filtros, legenda e detalhe da barragem.
// =====================================================================

import { LAYERS, USO_COLORS, USO_LABELS, USO_ORDER, NOTION_COLOR } from "./config.js";
import { escapeHtml, fmtNumber } from "./utils.js";

let dom = {};
let hooks = {};
let currentFilters = { country: "all", usos: [...USO_ORDER], onlyNotion: false };

export function initPanel({ map, manifest, onFiltersChange, onLayerToggle }) {
  dom = {
    sidebar: document.getElementById("sidebar"),
    layerList: document.getElementById("layer-list"),
    legend: document.getElementById("legend"),
    filterCountry: document.getElementById("filter-country"),
    filterUso: document.getElementById("filter-uso"),
    filterNotion: document.getElementById("filter-notion"),
    dataInfo: document.getElementById("data-info"),
    detail: document.getElementById("detail"),
    detailBody: document.getElementById("detail-body"),
    btnSidebar: document.getElementById("btn-sidebar"),
  };
  hooks = { onFiltersChange, onLayerToggle };

  buildLayerList(manifest);
  buildUsoFilters();
  buildLegend();
  wireFilters();
  wireSidebar();
  renderDataInfo(manifest);
}

// ---------------------------------------------------------------------
// Camadas
// ---------------------------------------------------------------------

function buildLayerList(manifest) {
  const available = manifest?.layers || {};
  dom.layerList.innerHTML = "";

  for (const def of LAYERS) {
    if (def.internal) continue; // camadas ligadas a outra (ex.: contorno das barragens)
    const hasData = Array.isArray(available[def.key]) && available[def.key].length > 0;
    if (!hasData) continue;

    const li = document.createElement("li");
    const id = `layer-${def.key}`;
    li.innerHTML = `
      <label for="${id}">
        <input type="checkbox" id="${id}" ${def.default ? "checked" : ""} />
        <span class="swatch ${def.legendSwatch === "line" ? "line" : ""}"
              style="background:${swatchColor(def)}"></span>
        <span>${escapeHtml(def.label)}${def.future ? " <em>(futuro)</em>" : ""}</span>
      </label>
      ${def.minzoom > 0 ? `<span class="minzoom" title="Só aparece a partir deste zoom">z${def.minzoom}+</span>` : ""}
    `;
    const checkbox = li.querySelector("input");
    checkbox.addEventListener("change", () => {
      hooks.onLayerToggle(def.key, checkbox.checked);
    });
    dom.layerList.appendChild(li);
  }
}

function swatchColor(def) {
  if (def.kind === "dams") return USO_COLORS["hidroelétrica"];
  return def.color || "#888";
}

// ---------------------------------------------------------------------
// Filtros
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
  dom.filterCountry.addEventListener("change", readFilters);
  dom.filterNotion.addEventListener("change", readFilters);
}

function readFilters() {
  const usos = USO_ORDER.filter((u) => {
    const el = document.getElementById(`uso-${USO_ORDER.indexOf(u)}`);
    return el && el.checked;
  });
  currentFilters = {
    country: dom.filterCountry.value,
    usos,
    onlyNotion: dom.filterNotion.checked,
  };
  hooks.onFiltersChange(currentFilters);
}

// ---------------------------------------------------------------------
// Legenda
// ---------------------------------------------------------------------

function buildLegend() {
  dom.legend.innerHTML = "";
  for (const uso of USO_ORDER) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="swatch" style="background:${USO_COLORS[uso]}"></span>
                    <span>${escapeHtml(USO_LABELS[uso])}</span>`;
    dom.legend.appendChild(li);
  }
  const star = document.createElement("li");
  star.innerHTML = `<span class="swatch" style="background:transparent;color:${NOTION_COLOR};font-size:15px;line-height:1;border:none">★</span>
                    <span>Com página Notion</span>`;
  dom.legend.appendChild(star);
}

// ---------------------------------------------------------------------
// Informação dos dados (rodapé)
// ---------------------------------------------------------------------

export function renderDataInfo(manifest) {
  if (!manifest) {
    dom.dataInfo.textContent = "Não foi possível ler data/manifest.json.";
    return;
  }
  const when = manifest.generated_at
    ? new Date(manifest.generated_at).toLocaleString("pt-PT")
    : "data desconhecida";
  const total = fmtNumber(manifest.total_features || 0);
  dom.dataInfo.innerHTML =
    `Dados atualizados a <strong>${escapeHtml(when)}</strong>.<br>` +
    `<span class="small">${total} elementos · ${escapeHtml(manifest.source || "OpenStreetMap")}</span>`;
}

// ---------------------------------------------------------------------
// Painel de detalhe
// ---------------------------------------------------------------------

export function showDetail(dam) {
  const p = dam.properties || {};
  const [lon, lat] = dam.geometry.coordinates;
  const title = p.name || p.name_pt || p.name_es || "Barragem sem nome";
  const usoColor = USO_COLORS[p.uso] || USO_COLORS["desconhecido"];

  const rows = [];
  const addRow = (label, value) => {
    if (value != null && value !== "") rows.push([label, value]);
  };
  addRow("Rio", p.river);
  addRow("Operador", p.operator);
  addRow("Altura", p.height != null ? `${fmtNumber(p.height)} m` : null);
  addRow("Altitude", p.ele != null ? `${fmtNumber(p.ele)} m` : null);
  addRow("Ano", p.start_date);
  if (p.reservoir_name) {
    const area = p.reservoir_area_ha != null ? ` (${fmtNumber(p.reservoir_area_ha)} ha)` : "";
    addRow("Albufeira", `${escapeHtml(p.reservoir_name)}${area}`);
  }
  // Centrais associadas. Nota: o MapLibre devolve propriedades do tipo
  // array como strings JSON (ex.: '["Grupo 4"]'), por isso interpretamos.
  let plantNames = p.plant_names;
  if (typeof plantNames === "string") {
    try { plantNames = JSON.parse(plantNames); }
    catch { plantNames = plantNames ? [plantNames] : []; }
  }
  if (!Array.isArray(plantNames)) plantNames = plantNames ? [String(plantNames)] : [];
  if (plantNames.length) {
    const pw = p.plant_power_mw != null ? ` — ${fmtNumber(p.plant_power_mw)} MW` : "";
    addRow("Centrais", `${plantNames.map(escapeHtml).join(", ")}${pw}`);
  }
  addRow("Volume", p.volume != null ? `${fmtNumber(p.volume)}` : null);
  addRow("Ref.", p.ref);

  const links = [];
  const osmUrl = `https://www.openstreetmap.org/${p.osm_type}/${p.osm_id}`;
  links.push(`<a href="${osmUrl}" target="_blank" rel="noopener">OpenStreetMap</a>`);
  if (p.wikidata) {
    links.push(`<a href="https://www.wikidata.org/wiki/${encodeURIComponent(p.wikidata)}" target="_blank" rel="noopener">Wikidata</a>`);
  }
  if (p.wikipedia) {
    const [lang, ...rest] = String(p.wikipedia).split(":");
    const article = rest.join(":") || lang;
    links.push(`<a href="https://${lang}.wikipedia.org/wiki/${encodeURIComponent(article)}" target="_blank" rel="noopener">Wikipédia</a>`);
  }

  const cover = p.notion_foto
    ? `<img class="detail-cover" src="${escapeHtml(p.notion_foto)}" alt="" loading="lazy"
            onerror="this.style.display='none'" />`
    : "";
  const notionBtn = p.notion_url
    ? `<a class="btn notion block" href="${escapeHtml(p.notion_url)}" target="_blank" rel="noopener">Ver no Notion</a>`
    : "";
  const resumo = p.notion_resumo
    ? `<p class="muted">${escapeHtml(p.notion_resumo)}</p>` : "";

  dom.detailBody.innerHTML = `
    ${cover}
    <h2>${escapeHtml(title)}</h2>
    <span class="detail-country">${escapeHtml(p.country || "")}</span>
    <div>
      <span class="detail-badge" style="background:${usoColor}">
        ${escapeHtml(USO_LABELS[p.uso] || p.uso || "—")}
      </span>
    </div>
    ${resumo}
    <dl class="kv">
      ${rows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${v}</dd>`).join("")}
    </dl>

    <div class="id-box">
      <code id="dam-id">${escapeHtml(p.dam_id || "")}</code>
      <p>Para ligar esta barragem ao Notion, cola este ID no campo <strong>ID Mapa</strong>.</p>
      <button class="btn block" id="copy-id" type="button">Copiar ID</button>
    </div>

    ${notionBtn}
    <div class="detail-links">${links.join("")}</div>
    <p class="muted small" style="margin-top:10px">
      Uso: ${escapeHtml(p.uso_fonte || "—")}
    </p>
  `;

  dom.detail.hidden = false;
  requestAnimationFrame(() => dom.detail.classList.add("open"));

  const copyBtn = document.getElementById("copy-id");
  copyBtn.addEventListener("click", () => copyId(p.dam_id, copyBtn));
}

function copyId(text, btn) {
  const done = () => {
    const original = btn.textContent;
    btn.textContent = "Copiado ✓";
    setTimeout(() => { btn.textContent = original; }, 1500);
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}

function fallbackCopy(text, done) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); done(); } catch (_) { /* ignorar */ }
  document.body.removeChild(ta);
}

export function hideDetail() {
  dom.detail.classList.remove("open");
  dom.detail.hidden = true;
}

// ---------------------------------------------------------------------
// Menu lateral (telemóvel)
// ---------------------------------------------------------------------

function wireSidebar() {
  dom.btnSidebar?.addEventListener("click", () => {
    const open = dom.sidebar.classList.toggle("open");
    dom.btnSidebar.setAttribute("aria-expanded", String(open));
  });
}

export function closeSidebar() {
  dom.sidebar?.classList.remove("open");
  dom.btnSidebar?.setAttribute("aria-expanded", "false");
}
