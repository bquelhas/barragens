// =====================================================================
// Ponto de entrada: cria o mapa, carrega os dados e liga a interface.
// =====================================================================

import { MAP, DATA, LAYERS, USO_ORDER } from "./config.js";
import { fetchJson } from "./utils.js";
import * as layers from "./layers.js";
import * as panel from "./panel.js";
import * as search from "./search.js";

const THEME_KEY = "barragens-theme";

let map;
let manifest = null;
let notion = {};

// ---------------------------------------------------------------------
// Tema
// ---------------------------------------------------------------------

function currentTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme, { restyle = true } = {}) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById("btn-dark");
  if (btn) {
    btn.textContent = theme === "dark" ? "☀" : "🌙";
    btn.setAttribute("aria-label", theme === "dark" ? "Modo claro" : "Modo escuro");
  }
  if (restyle && map) {
    map.setStyle(MAP.styles[theme], { diff: false });
    map.once("style.load", () => layers.rebuildAfterStyleChange());
  }
}

// ---------------------------------------------------------------------
// Estado no URL (#map=z/lat/lon&dam=way/123)
// ---------------------------------------------------------------------

function parseHash() {
  const out = { view: null, dam: null };
  const hash = location.hash.replace(/^#/, "");
  for (const part of hash.split("&")) {
    const [k, v] = part.split("=");
    if (k === "map" && v) {
      const [z, lat, lon] = v.split("/").map(Number);
      if ([z, lat, lon].every((n) => Number.isFinite(n))) out.view = { z, lat, lon };
    } else if (k === "dam" && v) {
      out.dam = decodeURIComponent(v);
    }
  }
  return out;
}

function writeHash() {
  const c = map.getCenter();
  const parts = [
    `map=${map.getZoom().toFixed(2)}/${c.lat.toFixed(4)}/${c.lng.toFixed(4)}`,
  ];
  if (layers.selectedDamId()) parts.push(`dam=${encodeURIComponent(layers.selectedDamId())}`);
  history.replaceState(null, "", `#${parts.join("&")}`);
}

// ---------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------

async function boot() {
  applyTheme(currentTheme(), { restyle: false });

  // Dados (em paralelo com a criação do mapa).
  const [manifestData, notionData] = await Promise.all([
    fetchJson(DATA.manifest, null),
    fetchJson(DATA.notion, {}),
  ]);
  manifest = manifestData;
  notion = notionData || {};

  showSampleBanner(manifest);

  const initial = parseHash();
  const startView = initial.view || { z: MAP.zoom, lat: MAP.center[1], lon: MAP.center[0] };

  map = new maplibregl.Map({
    container: "map",
    style: MAP.styles[document.documentElement.dataset.theme || "light"],
    center: [startView.lon, startView.lat],
    zoom: startView.z,
    minZoom: MAP.minZoom,
    maxZoom: MAP.maxZoom,
    attributionControl: false,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: MAP.attribution }), "bottom-right");

  // Inicializamos em `style.load` (estilo pronto), em vez de `load`, para
  // não depender do carregamento completo dos tiles do mapa base.
  map.once("style.load", () => onMapReady(initial));
  map.on("error", (e) => console.warn("MapLibre:", e?.error?.message || e));
}

async function onMapReady(initial) {
  // Inicializa módulos.
  panel.initPanel({
    map, manifest,
    onFiltersChange: (f) => { layers.applyFilters(f); writeHash(); },
    onLayerToggle: (key, visible) => layers.setVisibility(key, visible),
  });
  search.initSearch({
    onSelectDam: (damId, coords) => openDamById(damId, coords),
    onSelectReservoir: (coords) => flyTo(coords),
  });
  layers.init({ map, manifest, notion });

  // Carrega as camadas que arrancam ligadas.
  const defaults = LAYERS.filter((l) => l.default).map((l) => l.key);
  for (const key of defaults) await layers.ensureLayer(key);

  // Índice de pesquisa.
  search.setData(layers.allDams(), layers.allReservoirs());

  // Filtros iniciais (todos).
  layers.applyFilters({ country: "all", usos: [...USO_ORDER], onlyNotion: false });

  wireMapEvents();
  wireChrome();

  // Estado inicial vindo do URL.
  if (initial.dam) openDamById(initial.dam, null);

  document.getElementById("loading").hidden = true;
  document.body.classList.add("ready");
}

// ---------------------------------------------------------------------
// Eventos do mapa
// ---------------------------------------------------------------------

function wireMapEvents() {
  map.on("moveend", writeHash);
  map.on("zoomend", writeHash);

  map.on("click", "dams-points", (e) => {
    const f = e.features[0];
    openDam(f);
  });
  map.on("click", "dams-clusters", (e) => {
    const f = e.features[0];
    map.getSource(layers.damsSourceId)
      .getClusterExpansionZoom(f.properties.cluster_id)
      .then((zoom) => map.easeTo({ center: f.geometry.coordinates, zoom }))
      .catch(() => {});
  });

  for (const id of ["dams-points", "dams-clusters"]) {
    map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
  }

  // Clique no "vazio" fecha o detalhe.
  map.on("click", (e) => {
    const hits = map.queryRenderedFeatures(e.point, {
      layers: ["dams-points", "dams-clusters"],
    });
    if (hits.length === 0) closeDetail();
  });
}

// ---------------------------------------------------------------------
// Barra superior / ajuda
// ---------------------------------------------------------------------

function wireChrome() {
  document.getElementById("btn-dark").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });

  const help = document.getElementById("help-modal");
  document.getElementById("btn-help").addEventListener("click", () => (help.hidden = false));
  document.getElementById("help-close").addEventListener("click", () => (help.hidden = true));
  help.addEventListener("click", (e) => { if (e.target === help) help.hidden = true; });

  document.getElementById("detail-close").addEventListener("click", closeDetail);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!help.hidden) help.hidden = true;
      else closeDetail();
    }
  });
}

// ---------------------------------------------------------------------
// Abrir/fechar detalhe
// ---------------------------------------------------------------------

function openDam(feature) {
  const p = feature.properties;
  panel.showDetail({
    type: "Feature",
    properties: p,
    geometry: feature.geometry || { coordinates: [0, 0] },
  });
  layers.selectDam(p.dam_id, p.reservoir_id);
  panel.closeSidebar();
  writeHash();
}

async function openDamById(damId, coords) {
  if (!damId) return;
  await layers.ensureLayer("dams");
  const dam = layers.getDam(damId);
  if (dam) {
    panel.showDetail(dam);
    layers.selectDam(damId, dam.properties.reservoir_id);
    const c = coords || dam.geometry.coordinates;
    flyTo(c);
  } else if (coords) {
    flyTo(coords);
  }
  panel.closeSidebar();
  writeHash();
}

function closeDetail() {
  panel.hideDetail();
  layers.clearSelection();
  writeHash();
}

function flyTo(coords) {
  if (!coords) return;
  map.flyTo({ center: coords, zoom: Math.max(map.getZoom(), 11), essential: true });
}

// ---------------------------------------------------------------------
// Aviso de dados de amostra
// ---------------------------------------------------------------------

function showSampleBanner(manifest) {
  const banner = document.getElementById("sample-banner");
  if (manifest && manifest.sample) {
    banner.hidden = false;
    // As alturas do mapa, do menu e do painel dependem de --banner-h.
    requestAnimationFrame(() => {
      document.documentElement.style.setProperty("--banner-h", `${banner.offsetHeight}px`);
      if (map) map.resize();
    });
  }
}

boot();
