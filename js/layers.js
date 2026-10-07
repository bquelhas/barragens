// =====================================================================
// Camadas do mapa: carregamento de dados, estilo e filtros.
// =====================================================================

import { LAYERS, USO_COLORS, USO_ORDER, HIGHLIGHT, NOTION_COLOR, CLUSTER } from "./config.js";
import { fetchJson, distanceM, distanceToGeometryM, pointOf } from "./utils.js";

const state = {
  map: null,
  manifest: null,
  notion: {},
  loaded: new Set(),      // camadas cujo source já foi adicionado
  loading: {},            // promessas de camadas em carregamento (evita duplicados)
  data: {},               // dados em memória por camada
  visible: {},            // visibilidade pretendida por camada
  filters: { country: "all", usos: [...USO_ORDER], onlyNotion: false },
  selectedDam: null,
  selectedReservoir: null,
};

export const damsSourceId = "src-dams";

// ---------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------

export function init(opts) {
  Object.assign(state, opts);
  buildReservoirHighlight();
  buildRelatedHighlight();
}

/** Camada de destaque da infraestrutura relacionada (rede elétrica). */
function buildRelatedHighlight() {
  const map = state.map;
  if (!map.getSource("src-related")) map.addSource("src-related", emptySource());
  if (!map.getLayer("related-line")) {
    map.addLayer({
      id: "related-line", type: "line", source: "src-related", minzoom: 0,
      paint: {
        "line-color": HIGHLIGHT,
        "line-width": ["interpolate", ["linear"], ["zoom"], 6, 2, 12, 4],
        "line-opacity": 0.95,
      },
    });
  }
  if (!map.getLayer("related-point")) {
    map.addLayer({
      id: "related-point", type: "circle", source: "src-related", minzoom: 0,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 6, 14, 9],
        "circle-color": HIGHLIGHT,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    });
  }
}

/** Prepara a camada de destaque da albufeira selecionada (sempre presente). */
function buildReservoirHighlight() {
  const map = state.map;
  if (!map.getSource("src-res-highlight")) {
    map.addSource("src-res-highlight", emptySource());
  }
  if (!map.getLayer("reservoirs-highlight")) {
    map.addLayer({
      id: "reservoirs-highlight",
      type: "line",
      source: "src-res-highlight",
      minzoom: 0,
      filter: ["==", ["get", "reservoir_id"], "__none__"],
      paint: {
        "line-color": HIGHLIGHT,
        "line-width": ["interpolate", ["linear"], ["zoom"], 6, 2, 12, 4],
        "line-opacity": 0.95,
      },
    });
  }
}

function emptySource() {
  return { type: "geojson", data: { type: "FeatureCollection", features: [] } };
}

// ---------------------------------------------------------------------
// Carregamento de dados
// ---------------------------------------------------------------------

/** Junta as features de todos os ficheiros de uma camada do manifest. */
async function loadLayerData(key) {
  const files = state.manifest?.layers?.[key];
  if (!files || files.length === 0) return null;

  const features = [];
  // Versão dos dados para evitar cache obsoleta (muda com o manifest).
  const v = encodeURIComponent(state.manifest?.generated_at || Date.now());
  for (const file of files) {
    const fc = await fetchJson(`data/${file}?v=${v}`, null);
    if (fc?.features) features.push(...fc.features);
  }

  if (key === "dams") attachNotion(features);
  state.data[key] = features;
  return { type: "FeatureCollection", features };
}

/** Acrescenta os campos do Notion às barragens que têm página. */
function attachNotion(features) {
  const notion = state.notion || {};
  for (const f of features) {
    const meta = notion[f.properties?.dam_id];
    if (meta) {
      f.properties.notion_url = meta.url || null;
      f.properties.notion_titulo = meta.titulo || null;
      f.properties.notion_foto = meta.foto_capa || null;
      f.properties.notion_resumo = meta.resumo || null;
    }
  }
}

// ---------------------------------------------------------------------
// Construção de sources e layers
// ---------------------------------------------------------------------

/** Garante que a camada está carregada e adicionada ao mapa. */
export function ensureLayer(key) {
  if (state.loaded.has(key)) return Promise.resolve();
  if (state.loading[key]) return state.loading[key];
  state.loading[key] = doEnsureLayer(key).finally(() => { delete state.loading[key]; });
  return state.loading[key];
}

async function doEnsureLayer(key) {
  if (state.loaded.has(key)) return;
  const map = state.map;
  const def = LAYERS.find((l) => l.key === key);
  if (!def) return;
  const fc = await loadLayerData(key);
  if (!fc) return; // sem ficheiro no manifest (ex.: bairros vazio)

  state.loaded.add(key);
  if (key === "dams") addDams(fc);
  else addGeneric(def, fc);

  // Alimenta o destaque da albufeira e garante que fica por cima das albufeiras.
  if (key === "reservoirs") {
    const hl = map.getSource("src-res-highlight");
    if (hl) hl.setData(fc);
    if (map.getLayer("reservoirs-highlight")) map.moveLayer("reservoirs-highlight");
  }

  // Aplica a visibilidade pretendida à camada acabada de criar.
  setVisibility(key, state.visible[key] ?? def.default, true);
}

/**
 * Volta a criar sources/layers a partir dos dados em memória.
 * Necessário depois de `map.setStyle` (mudança de tema), que limpa tudo.
 */
export function rebuildAfterStyleChange() {
  const map = state.map;
  state.loaded.clear();
  buildReservoirHighlight();
  buildRelatedHighlight();
  for (const def of LAYERS) {
    const key = def.key;
    if (!state.data[key]) continue;
    const fc = { type: "FeatureCollection", features: state.data[key] };
    state.loaded.add(key);
    if (key === "dams") addDams(fc);
    else addGeneric(def, fc);
    if (key === "reservoirs") {
      const hl = map.getSource("src-res-highlight");
      if (hl) hl.setData(fc);
      if (map.getLayer("reservoirs-highlight")) map.moveLayer("reservoirs-highlight");
    }
    setVisibility(key, state.visible[key] ?? def.default, true);
  }
  applyFilters(state.filters);
  if (state.selectedDam) selectDam(state.selectedDam, state.selectedReservoir);
}

function addGeneric(def, fc) {
  const map = state.map;
  const srcId = `src-${def.key}`;
  if (!map.getSource(srcId)) map.addSource(srcId, { type: "geojson", data: fc });

  const color = def.color || "#888";
  if (def.kind === "line") {
    map.addLayer({
      id: `${def.key}-line`, type: "line", source: srcId, minzoom: def.minzoom,
      paint: { "line-color": color, "line-width": 1.4, "line-opacity": 0.85 },
    });
  } else if (def.kind === "outline") {
    // Contorno de estruturas (linhas e polígonos): preenchimento suave
    // (só afeta polígonos) + traço. Aparece apenas a partir de `minzoom`.
    // O contorno das barragens é colorido pelo uso (tal como as bolinhas).
    const colorExpr = def.key === "dam_geoms" ? usoColorExpression() : color;
    map.addLayer({
      id: `${def.key}-fill`, type: "fill", source: srcId, minzoom: def.minzoom,
      paint: { "fill-color": colorExpr, "fill-opacity": 0.25 },
    });
    map.addLayer({
      id: `${def.key}-line`, type: "line", source: srcId, minzoom: def.minzoom,
      paint: {
        "line-color": colorExpr,
        "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2, 16, 4],
        "line-opacity": 0.95,
      },
    });
  } else if (def.kind === "polygon") {
    map.addLayer({
      id: `${def.key}-fill`, type: "fill", source: srcId, minzoom: def.minzoom,
      paint: { "fill-color": color, "fill-opacity": 0.32 },
    });
    map.addLayer({
      id: `${def.key}-outline`, type: "line", source: srcId, minzoom: def.minzoom,
      paint: { "line-color": color, "line-width": 1, "line-opacity": 0.8 },
    });
  } else {
    map.addLayer({
      id: `${def.key}-point`, type: "circle", source: srcId, minzoom: def.minzoom,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 3, 12, 6],
        "circle-color": color,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1,
      },
    });
  }
}

/** Camadas específicas das barragens (clustering, cor por uso, ★ Notion). */
function addDams(fc) {
  const map = state.map;
  map.addSource(damsSourceId, {
    type: "geojson",
    data: fc,
    promoteId: "dam_id",
    cluster: true,
    clusterRadius: CLUSTER.radius,
    clusterMaxZoom: CLUSTER.maxZoom,
  });

  // Grupos (clusters)
  map.addLayer({
    id: "dams-clusters", type: "circle", source: damsSourceId, minzoom: 0,
    filter: ["has", "point_count"],
    paint: {
      "circle-color": "#1f6feb",
      "circle-opacity": 0.85,
      "circle-radius": ["step", ["get", "point_count"], 14, 20, 18, 100, 24],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.5,
    },
  });
  map.addLayer({
    id: "dams-cluster-count", type: "symbol", source: damsSourceId, minzoom: 0,
    filter: ["has", "point_count"],
    layout: { "text-field": ["to-string", ["get", "point_count"]], "text-size": 12 },
    paint: { "text-color": "#ffffff" },
  });

  // Barragens individuais
  map.addLayer({
    id: "dams-points", type: "circle", source: damsSourceId, minzoom: 0,
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 4, 10, 5.5, 14, 6],
      "circle-color": usoColorExpression(),
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": ["case", ["boolean", ["feature-state", "selected"], false], 3, 1],
    },
  });

  // ★ nas barragens com página Notion
  map.addLayer({
    id: "dams-notion", type: "symbol", source: damsSourceId, minzoom: 5,
    filter: ["all", ["!", ["has", "point_count"]], ["has", "notion_url"]],
    layout: {
      "text-field": "★",
      "text-size": 13,
      "text-offset": [0.9, -0.9],
      "text-allow-overlap": true,
    },
    paint: { "text-color": NOTION_COLOR, "text-halo-color": "#000000", "text-halo-width": 0.6 },
  });

  // Realce da barragem selecionada (o estado vai no paint, não no filter:
  // o MapLibre não permite feature-state em filtros).
  map.addLayer({
    id: "dams-selected", type: "circle", source: damsSourceId, minzoom: 0,
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-radius": ["case", sel(), 16, 0],
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-color": HIGHLIGHT,
      "circle-stroke-width": ["case", sel(), 3, 0],
    },
  });
}

function sel() {
  return ["boolean", ["feature-state", "selected"], false];
}

function usoColorExpression() {
  const expr = ["match", ["get", "uso"]];
  for (const uso of USO_ORDER) expr.push(uso, USO_COLORS[uso]);
  expr.push(USO_COLORS["desconhecido"]); // fallback
  return expr;
}

// ---------------------------------------------------------------------
// Visibilidade
// ---------------------------------------------------------------------

const layerIdsByKey = (key) => {
  if (key === "dams") return ["dams-clusters", "dams-cluster-count", "dams-points", "dams-notion", "dams-selected"];
  const def = LAYERS.find((l) => l.key === key);
  if (!def) return [];
  if (def.kind === "line") return [`${key}-line`];
  if (def.kind === "polygon") return [`${key}-fill`, `${key}-outline`];
  if (def.kind === "outline") return [`${key}-fill`, `${key}-line`];
  return [`${key}-point`];
};

export function setVisibility(key, visible, force = false) {
  state.visible[key] = visible;
  // O contorno segue sempre a camada "Barragens".
  if (key === "dams") setVisibility("dam_geoms", visible, force);
  if (!state.loaded.has(key) && visible) {
    ensureLayer(key).then(() => state.map && applyFilters(state.filters));
    return;
  }
  if (!state.loaded.has(key)) return;
  const map = state.map;
  for (const id of layerIdsByKey(key)) {
    if (map.getLayer(id)) {
      map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
    }
  }
  // A albufeira de destaque acompanha a camada de albufeiras.
  if (key === "reservoirs" && map.getLayer("reservoirs-highlight")) {
    map.setLayoutProperty("reservoirs-highlight", "visibility", visible ? "visible" : "none");
  }
}

// ---------------------------------------------------------------------
// Filtros
// ---------------------------------------------------------------------

export function applyFilters(filters) {
  state.filters = filters;
  const map = state.map;
  if (!map || !state.loaded.has("dams")) return;

  const pointConds = [["!", ["has", "point_count"]], ...countryUsoNotionConds(filters, false)];
  const pointFilter = ["all", ...pointConds];

  if (map.getLayer("dams-points")) map.setFilter("dams-points", pointFilter);
  if (map.getLayer("dams-notion")) {
    map.setFilter("dams-notion", ["all", ...pointConds, ["has", "notion_url"]]);
  }
  if (map.getLayer("dams-selected")) {
    map.setFilter("dams-selected", pointFilter);
  }

  // Clusters: o guarda `has point_count` separa-os dos pontos individuais.
  // (Os filtros aplicam-se aos pontos; os grupos mostram sempre o total.)
  if (map.getLayer("dams-clusters")) {
    map.setFilter("dams-clusters", ["has", "point_count"]);
  }
  if (map.getLayer("dams-cluster-count")) {
    map.setLayoutProperty("dams-cluster-count", "text-field",
      ["to-string", ["get", "point_count"]]);
  }

  // O contorno das barragens (dam_geoms) respeita os mesmos filtros.
  const outlineConds = countryUsoNotionConds(filters, false);
  const outlineFilter = outlineConds.length ? ["all", ...outlineConds] : null;
  for (const id of ["dam_geoms-line", "dam_geoms-fill"]) {
    if (map.getLayer(id)) map.setFilter(id, outlineFilter);
  }
}

function countryUsoNotionConds(filters, isCluster) {
  const conds = [];
  if (filters.country && filters.country !== "all") {
    conds.push(["==", ["get", "country"], filters.country]);
  }
  if (filters.usos && filters.usos.length > 0 && filters.usos.length < USO_ORDER.length) {
    conds.push(["in", ["get", "uso"], ["literal", filters.usos]]);
  }
  if (filters.onlyNotion) conds.push(["has", "notion_url"]);
  return conds;
}

// ---------------------------------------------------------------------
// Seleção e destaque
// ---------------------------------------------------------------------

export function selectDam(damId, reservoirId) {
  const map = state.map;
  if (!map || !state.loaded.has("dams")) return;

  if (state.selectedDam && state.selectedDam !== damId) {
    map.setFeatureState({ source: damsSourceId, id: state.selectedDam }, { selected: false });
  }
  state.selectedDam = damId;
  if (damId) {
    map.setFeatureState({ source: damsSourceId, id: damId }, { selected: true });
  }

  state.selectedReservoir = reservoirId || null;
  if (map.getLayer("reservoirs-highlight")) {
    map.setFilter("reservoirs-highlight", [
      "==", ["get", "reservoir_id"], reservoirId || "__none__",
    ]);
  }
}

const RELATED_RADIUS = { line: 300, sub: 400 }; // metros

/**
 * Calcula e destaca a infraestrutura elétrica relacionada com a barragem:
 * centrais associadas, linhas elétricas que lhes chegam e subestações
 * nessas ligações — para se perceber o caminho da eletricidade.
 */
export async function highlightRelated(dam) {
  const map = state.map;
  const src = map.getSource("src-related");
  if (!src) return null;
  if (!dam) { src.setData(emptySource().data); return null; }

  const p = dam.properties || {};
  // Carrega os dados necessários (podem estar desligados no painel).
  for (const k of ["plants", "substations", "power_lines"]) {
    await ensureLayer(k);
  }

  const idOf = (f) => `${f.properties.osm_type}/${f.properties.osm_id}`;
  const plants = state.data.plants || [];
  const subs = state.data.substations || [];
  const lines = state.data.power_lines || [];

  // `plant_ids` chega como string JSON por via do MapLibre.
  let plantIds = p.plant_ids;
  if (typeof plantIds === "string") {
    try { plantIds = JSON.parse(plantIds); } catch { plantIds = []; }
  }
  const ids = new Set(plantIds || []);

  const relPlants = plants.filter((f) => ids.has(idOf(f)));
  const plantPts = relPlants.map((f) => pointOf(f.geometry)).filter(Boolean);
  const relLines = lines.filter((f) =>
    plantPts.some((pt) => distanceToGeometryM(pt, f.geometry) <= RELATED_RADIUS.line));
  const relSubs = subs.filter((f) => {
    const c = pointOf(f.geometry);
    if (!c) return false;
    if (plantPts.some((pt) => distanceM(pt, c) <= RELATED_RADIUS.sub)) return true;
    return relLines.some((l) => distanceToGeometryM(c, l.geometry) <= RELATED_RADIUS.sub);
  });

  const features = [...relPlants, ...relSubs, ...relLines].map((f) => ({
    type: "Feature", geometry: f.geometry, properties: { osm: idOf(f) },
  }));
  src.setData({ type: "FeatureCollection", features });

  return {
    plantNames: relPlants.map((f) => f.properties.name).filter(Boolean),
    nSubs: relSubs.length,
    nLines: relLines.length,
  };
}

export function clearRelated() {
  const src = state.map?.getSource("src-related");
  if (src) src.setData(emptySource().data);
}

export function clearSelection() {
  selectDam(null, null);
  clearRelated();
}

// ---------------------------------------------------------------------
// Acesso aos dados (para pesquisa e painel)
// ---------------------------------------------------------------------

export function getDam(damId) {
  return (state.data.dams || []).find((f) => f.properties.dam_id === damId) || null;
}

export function allDams() {
  return state.data.dams || [];
}

export function allReservoirs() {
  return state.data.reservoirs || [];
}

export function isLoaded(key) {
  return state.loaded.has(key);
}

export function selectedDamId() {
  return state.selectedDam;
}

/** Atualiza a tabela do Notion (usada ao reanexar dados). */
export function setNotion(notion) {
  state.notion = notion || {};
}

/**
 * Remove as nossas camadas/sources e recarrega os dados do disco.
 * Usado quando o `manifest.json` muda (novos dados publicados).
 */
export async function reloadData() {
  const map = state.map;
  for (const def of LAYERS) {
    for (const id of layerIdsByKey(def.key)) {
      if (map.getLayer(id)) map.removeLayer(id);
    }
  }
  if (map.getLayer("reservoirs-highlight")) map.removeLayer("reservoirs-highlight");
  for (const id of ["related-line", "related-point"]) {
    if (map.getLayer(id)) map.removeLayer(id);
  }

  const srcIds = [damsSourceId, "src-res-highlight", "src-related",
                  ...LAYERS.map((d) => `src-${d.key}`)];
  for (const id of srcIds) {
    if (map.getSource(id)) map.removeSource(id);
  }

  state.loaded.clear();
  state.loading = {};
  state.data = {};
  buildReservoirHighlight();
  buildRelatedHighlight();

  for (const def of LAYERS) {
    if (state.visible[def.key]) await ensureLayer(def.key);
  }
  applyFilters(state.filters);
  if (state.selectedDam) selectDam(state.selectedDam, state.selectedReservoir);
}
