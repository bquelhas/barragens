// =====================================================================
// Ponto de entrada: cria o mapa, carrega os dados e liga a interface.
// =====================================================================

import { MAP, DATA, LAYERS, USO_ORDER, PROJECT, STORAGE } from "./config.js";
import { fetchJson } from "./utils.js";
import * as layers from "./layers.js";
import * as panel from "./panel.js";
import * as search from "./search.js";
import * as discover from "./discover.js";

let map;
let manifest = null;
let notion = {};
let lastGenerated = null;
const REFRESH_MS = 60000;
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------------------------------------------------------------------
// Tema
// ---------------------------------------------------------------------

function currentTheme() {
  try {
    const saved = localStorage.getItem(STORAGE.theme);
    if (saved === "light" || saved === "dark") return saved;
  } catch (_) { /* ignora */ }
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
  for (const part of location.hash.replace(/^#/, "").split("&")) {
    const [k, v] = part.split("=");
    if (k === "map" && v) {
      const [z, lat, lon] = v.split("/").map(Number);
      if ([z, lat, lon].every(Number.isFinite)) out.view = { z, lat, lon };
    } else if (k === "dam" && v) out.dam = decodeURIComponent(v);
  }
  return out;
}

function writeHash() {
  const c = map.getCenter();
  const parts = [`map=${map.getZoom().toFixed(2)}/${c.lat.toFixed(4)}/${c.lng.toFixed(4)}`];
  if (layers.selectedDamId()) parts.push(`dam=${encodeURIComponent(layers.selectedDamId())}`);
  history.replaceState(null, "", `#${parts.join("&")}`);
}

// ---------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------

async function boot() {
  // Nome/subtítulo a partir da configuração.
  document.getElementById("brand-name").textContent = PROJECT.name;
  document.getElementById("brand-sub").textContent = "Portugal e Espanha";
  document.title = PROJECT.name;

  applyTheme(currentTheme(), { restyle: false });

  const [manifestData, notionData] = await Promise.all([
    fetchJson(DATA.manifest, null),
    fetchJson(DATA.notion, {}),
  ]);
  manifest = manifestData;
  notion = notionData || {};
  lastGenerated = manifest?.generated_at || null;
  showSampleBanner(manifest);

  const initial = parseHash();
  const start = initial.view || { z: MAP.zoom, lat: MAP.center[1], lon: MAP.center[0] };

  map = new maplibregl.Map({
    container: "map",
    style: MAP.styles[document.documentElement.dataset.theme || "light"],
    center: [start.lon, start.lat], zoom: start.z,
    minZoom: MAP.minZoom, maxZoom: MAP.maxZoom, attributionControl: false,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-left");
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: MAP.attribution }), "bottom-right");
  map.once("style.load", () => onMapReady(initial));
  map.on("error", (e) => console.warn("MapLibre:", e?.error?.message || e));
}

async function onMapReady(initial) {
  panel.initPanel({
    map, manifest,
    onFiltersChange: (f) => { layers.applyFilters(f); writeHash(); },
    onLayerToggle: (key, visible) => layers.setVisibility(key, visible),
    onListSort: (field) => discover.setSort(field),
    onListShow: () => discover.refreshList(),
    onOpenDamById: (damId) => openDamById(damId, null),
  });
  search.initSearch({
    onSelectDam: (damId, coords) => openDamById(damId, coords),
    onSelectReservoir: (item) => openReservoir(item),
  });
  layers.init({ map, manifest, notion });

  const defaults = LAYERS.filter((l) => l.default).map((l) => l.key);
  for (const key of defaults) await layers.ensureLayer(key);

  search.setData(layers.allDams(), layers.allReservoirs());
  layers.applyFilters({ country: "all", usos: [...USO_ORDER], onlyNotion: false });

  discover.initDiscover({
    map, manifest,
    allDams: layers.allDams,
    onSelectDam: (damId, coords) => openDamById(damId, coords),
    onHoverDam: (damId) => layers.setHover(damId),
  });

  wireMapEvents();
  wireChrome();
  if (new URLSearchParams(location.search).has("debug")) window.__map = map;

  if (initial.dam) openDamById(initial.dam, null);

  setInterval(checkForUpdates, REFRESH_MS);
  document.getElementById("loading").hidden = true;
  document.body.classList.add("ready");
}

async function checkForUpdates() {
  try {
    const fresh = await fetchJson(`${DATA.manifest}?t=${Date.now()}`, null);
    if (!fresh || !fresh.generated_at || fresh.generated_at === lastGenerated) return;
    lastGenerated = fresh.generated_at;
    manifest = fresh;
    notion = (await fetchJson(`${DATA.notion}?t=${Date.now()}`, {})) || {};
    layers.setNotion(notion);
    await layers.reloadData();
    search.setData(layers.allDams(), layers.allReservoirs());
    showSampleBanner(manifest);
    console.info("[dados] atualizados para", fresh.generated_at);
  } catch (err) {
    console.warn("Falha ao recarregar dados novos:", err);
  }
}

// ---------------------------------------------------------------------
// Eventos do mapa
// ---------------------------------------------------------------------

function wireMapEvents() {
  map.on("moveend", writeHash);
  map.on("zoomend", writeHash);

  if (map.getLayer("dams-clusters")) {
    map.on("click", "dams-clusters", (e) => {
      const f = e.features[0];
      map.getSource(layers.damsSourceId).getClusterExpansionZoom(f.properties.cluster_id)
        .then((zoom) => map.easeTo({ center: f.geometry.coordinates, zoom })).catch(() => {});
    });
  }
  if (map.getLayer("dams-points")) {
    map.on("mouseenter", "dams-points", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "dams-points", () => (map.getCanvas().style.cursor = ""));
  }
  if (map.getLayer("reservoirs-fill")) {
    map.on("mouseenter", "reservoirs-fill", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "reservoirs-fill", () => (map.getCanvas().style.cursor = ""));
  }
  if (map.getLayer("pois-fill")) {
    map.on("mouseenter", "pois-fill", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "pois-fill", () => (map.getCanvas().style.cursor = ""));
  }

  // Um único handler de clique. Prioridade: cluster > barragem > albufeira >
  // barragem mais próxima (garante que continua clicável com ícones sobrepostos).
  map.on("click", (e) => {
    const damLayers = ["dams-points", "dams-clusters"].filter((id) => map.getLayer(id));
    const damHits = damLayers.length ? map.queryRenderedFeatures(e.point, { layers: damLayers }) : [];
    if (damHits.length) {
      const f = damHits[0];
      if (f.layer.id === "dams-clusters") {
        map.getSource(layers.damsSourceId).getClusterExpansionZoom(f.properties.cluster_id)
          .then((zoom) => map.easeTo({ center: f.geometry.coordinates, zoom })).catch(() => {});
        return;
      }
      openDam(f);
      return;
    }
    const resLayers = ["reservoirs-fill", "reservoirs-outline"].filter((id) => map.getLayer(id));
    const resHits = resLayers.length ? map.queryRenderedFeatures(e.point, { layers: resLayers }) : [];
    if (resHits.length) { openReservoirProps(resHits[0].properties); return; }

    const poiLayers = ["pois-fill", "pois-line"].filter((id) => map.getLayer(id));
    const poiHits = poiLayers.length ? map.queryRenderedFeatures(e.point, { layers: poiLayers }) : [];
    if (poiHits.length) { openPoi(poiHits[0].properties); return; }

    const near = nearestDam(e.point, 22);
    if (near) openDam(near);
    else closeDetail();
  });
}

/** Barragem cujo ponto projetado está a ≤ `maxPx` do clique. */
function nearestDam(point, maxPx) {
  let best = null;
  let bestD = maxPx;
  for (const d of layers.allDams()) {
    const p = map.project(d.geometry.coordinates);
    const dx = p.x - point.x, dy = p.y - point.y;
    const dist = Math.hypot(dx, dy);
    if (dist <= bestD) { bestD = dist; best = d; }
  }
  return best;
}

// ---------------------------------------------------------------------
// Barra superior / atalhos
// ---------------------------------------------------------------------

function wireChrome() {
  document.getElementById("btn-dark").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem(STORAGE.theme, next); } catch (_) { /* ignora */ }
    applyTheme(next);
  });

  const help = document.getElementById("help-modal");
  document.getElementById("btn-help").addEventListener("click", () => {
    // O "?" abre o ecrã de boas-vindas (com atalho para "Como usar").
    discover.toggleWelcome();
  });
  document.getElementById("help-close").addEventListener("click", () => (help.hidden = true));
  help.addEventListener("click", (e) => { if (e.target === help) help.hidden = true; });

  // Atalho "Como usar" dentro das boas-vindas.
  const sub = document.getElementById("welcome-sub");
  if (sub && !document.getElementById("welcome-help")) {
    const a = document.createElement("button");
    a.id = "welcome-help"; a.className = "btn"; a.type = "button"; a.textContent = "Como usar";
    a.style.marginTop = "10px";
    a.addEventListener("click", () => (help.hidden = false));
    sub.insertAdjacentElement("afterend", a);
  }

  document.getElementById("btn-search")?.addEventListener("click", () => {
    document.getElementById("search-wrap").classList.toggle("open");
    document.getElementById("search-input").focus();
  });

  document.getElementById("detail-close").addEventListener("click", closeDetail);
  wireSheetDrag();

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!help.hidden) help.hidden = true;
    else if (!document.getElementById("welcome").hidden) discover.hideWelcome();
    else closeDetail();
  });

  addEventListener("resize", debounce(() => { map.resize(); }, 150));
}

// ---------------------------------------------------------------------
// Bottom sheet (telemóvel)
// ---------------------------------------------------------------------

function wireSheetDrag() {
  const grip = document.getElementById("detail-grip");
  if (!grip) return;
  let startY = null;
  grip.addEventListener("pointerdown", (e) => { startY = e.clientY; grip.setPointerCapture(e.pointerId); });
  grip.addEventListener("pointerup", (e) => {
    if (startY == null) return;
    const dy = e.clientY - startY;
    const cur = document.getElementById("detail").dataset.sheet || "half";
    let next = cur;
    if (dy < -30) next = cur === "collapsed" ? "half" : "full";
    else if (dy > 30) next = cur === "full" ? "half" : "collapsed";
    panel.setSheet(next);
    startY = null;
  });
}

// ---------------------------------------------------------------------
// Abrir/fechar ficha
// ---------------------------------------------------------------------

function openDam(feature) {
  const p = feature.properties;
  panel.showDetail({ type: "Feature", properties: p, geometry: feature.geometry || { coordinates: [0, 0] } });
  layers.selectDam(p.dam_id, p.reservoir_id);
  discover.markSelected(p.dam_id);
  layers.highlightRelated(feature).then((rel) => panel.setRelated(rel)).catch((err) => console.warn("Rede relacionada:", err));
  writeHash();
}

async function openDamById(damId, coords) {
  if (!damId) return;
  await layers.ensureLayer("dams");
  const dam = layers.getDam(damId);
  if (dam) {
    panel.showDetail(dam);
    layers.selectDam(damId, dam.properties.reservoir_id);
    discover.markSelected(damId);
    layers.highlightRelated(dam).then((rel) => panel.setRelated(rel)).catch((err) => console.warn("Rede relacionada:", err));
    flyTo(coords || dam.geometry.coordinates);
  } else if (coords) {
    flyTo(coords);
  }
  writeHash();
}

function closeDetail() {
  panel.hideDetail();
  layers.clearSelection();
  discover.markSelected(null);
  writeHash();
}

/** Abre a ficha de uma albufeira (ou da barragem associada, se existir). */
function openReservoir(item) {
  if (item.coords) flyTo(item.coords);
  if (item.damId) { openDamById(item.damId, null); return; }
  const feature = layers.allReservoirs().find((r) => r.properties.reservoir_id === item.reservoirId);
  openReservoirProps({ name: item.name, reservoir_id: item.reservoirId, ...(feature?.properties || {}) });
}

function openReservoirProps(props) {
  if (props.dam_id) { openDamById(props.dam_id, null); return; }
  layers.selectDam(null, props.reservoir_id);
  panel.showReservoir(props);
  discover.markSelected(null);
  writeHash();
}

/** Mostra o cartão de um ponto de interesse (património). */
function openPoi(props) {
  layers.clearSelection();
  panel.showPoi(props);
  discover.markSelected(null);
  writeHash();
}

function flyTo(coords) {
  if (!coords) return;
  const opts = { center: coords, zoom: Math.max(map.getZoom(), 11) };
  if (REDUCED) map.jumpTo(opts); else map.flyTo({ ...opts, essential: true });
}

// ---------------------------------------------------------------------
// Aviso de dados de amostra
// ---------------------------------------------------------------------

function showSampleBanner(manifest) {
  const banner = document.getElementById("sample-banner");
  const text = document.getElementById("sample-banner-text");
  const sc = manifest?.sample_countries || [];
  if (!manifest || !(manifest.sample || sc.length)) {
    banner.hidden = true;
    document.documentElement.style.setProperty("--banner-h", "0px");
    if (map) map.resize();
    return;
  }
  text.innerHTML = sc.length && sc.length < (manifest.countries || []).length
    ? `<strong>Dados de amostra</strong> para ${sc.join(" e ")}. As restantes são dados reais do OpenStreetMap.`
    : "Estás a ver <strong>dados de amostra</strong>. Corre o pipeline para carregar os dados reais do OpenStreetMap.";
  banner.hidden = false;
  requestAnimationFrame(() => {
    document.documentElement.style.setProperty("--banner-h", `${banner.offsetHeight}px`);
    if (map) map.resize();
  });
}

function debounce(fn, delay) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), delay); };
}

boot();
