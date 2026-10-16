// =====================================================================
// Camadas do mapa: carregamento, estilo, ícones e filtros.
// =====================================================================

import {
  LAYERS, USO_COLORS, USO_ORDER, PALETTE, CLUSTER, DAM_ICON, RELATED, HILLSHADE,
  CONTOURS, CONFIANCA_COLORS, CONFIANCA_ORDER,
} from "./config.js";
import { fetchJson, distanceM, distanceToGeometryM, pointOf, normalize } from "./utils.js";

const state = {
  map: null,
  manifest: null,
  notion: {},
  loaded: new Set(),
  loading: {},
  data: {},
  visible: {},
  filters: { country: "all", usos: [...USO_ORDER], onlyNotion: false },
  selectedDam: null,
  selectedReservoir: null,
  selectedFid: null,
  hoverFid: null,
  fidByDam: {},
  damByFid: {},
};

export const damsSourceId = "src-dams";

// Camadas cujas feições pertencem a uma barragem (chave dos dados → ids no mapa).
// Seguem os filtros de país, uso e Notion — os atributos que faltam são
// copiados das barragens por `linkToDams`, **antes** de a fonte ser criada.
const DAM_LAYERS = [
  ["dam_geoms", ["dam_geoms-line", "dam_geoms-fill"]],
  ["reservoirs", ["reservoirs-fill", "reservoirs-outline"]],
  ["plants", ["plants-point"]],
  ["submersos", ["submersos-point", "submersos-label"]],
  ["bairros", ["bairros-point", "bairros-label"]],
];
const DAM_LAYER_KEYS = new Set(DAM_LAYERS.map(([k]) => k));

// Infraestrutura auxiliar: segue só o país (não tem uso nem barragem associada).
const COUNTRY_LAYERS = ["weirs-point", "substations-point", "power_lines-line", "conduits-line"];

// ---------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------

export function init(opts) {
  Object.assign(state, opts);
  addHillshade();
  addContours();
  attenuateBaseMap();
  buildReservoirHighlight();
  buildRelatedHighlight();
}

/** Relevo subtil por baixo das camadas temáticas (Parte B10). */
function addHillshade() {
  const map = state.map;
  if (!HILLSHADE.enabled) return;
  try {
    if (!map.getSource("dem")) {
      map.addSource("dem", {
        type: "raster-dem", tiles: [HILLSHADE.tiles], encoding: HILLSHADE.encoding,
        tileSize: HILLSHADE.tileSize, maxzoom: HILLSHADE.maxzoom,
        attribution: HILLSHADE.attribution,
      });
    }
    if (!map.getLayer("hillshade")) {
      map.addLayer({
        id: "hillshade", type: "hillshade", source: "dem",
        paint: {
          "hillshade-exaggeration": HILLSHADE.exaggeration,
          "hillshade-shadow-color": "#3d3627",
          "hillshade-highlight-color": "#ffffff",
          "hillshade-accent-color": "#6b6252",
        },
      });
    }
  } catch (err) {
    console.warn("Hillshade:", err);
  }
}

// ---------------------------------------------------------------------
// Curvas de nível (maplibre-contour, calculadas no browser)
// ---------------------------------------------------------------------

// Fonte de elevação partilhada: criada uma só vez, para a cache de tiles de
// relevo sobreviver às reconstruções (mudança de tema).
let demSource = null;

function ensureDemSource() {
  const lib = globalThis.mlcontour;
  if (!lib) {
    console.warn("Curvas de nível: a biblioteca maplibre-contour não carregou.");
    return null;
  }
  if (!demSource) {
    demSource = new lib.DemSource({
      url: HILLSHADE.tiles,          // as mesmas tiles do relevo
      encoding: CONTOURS.encoding,
      maxzoom: CONTOURS.maxzoom,
      worker: CONTOURS.worker,
      cacheSize: CONTOURS.cacheSize,
      timeoutMs: CONTOURS.timeoutMs,
    });
    demSource.setupMaplibre(maplibregl);
  }
  return demSource;
}

/**
 * Curvas de nível a partir das tiles de relevo, com intervalos por zoom.
 * Substitui o `hillshade` como leitura do terreno.
 */
function addContours() {
  if (!CONTOURS.enabled) return;
  const map = state.map;
  const dem = ensureDemSource();
  if (!dem) return;

  try {
    const t = document.documentElement.dataset.theme;
    const colors = CONTOURS.colors[t === "dark" ? "dark" : "light"];

    if (!map.getSource("contours")) {
      map.addSource("contours", {
        type: "vector",
        tiles: [dem.contourProtocolUrl({
          multiplier: 1,                     // metros (o DEM já está em metros)
          thresholds: CONTOURS.thresholds,
          contourLayer: "contours",
        })],
        maxzoom: CONTOURS.sourceMaxzoom,
        attribution: HILLSHADE.attribution,
      });
    }

    if (!map.getLayer("contours-lines")) {
      map.addLayer({
        id: "contours-lines", type: "line", source: "contours",
        "source-layer": "contours",
        // Sem as cotas negativas (batimetria): o mar fica sem linhas.
        filter: [">", ["get", "ele"], CONTOURS.minElevation],
        paint: {
          // `level` = índice mais alto dos intervalos de que a cota é múltipla:
          // 0 = linha menor, 1 = linha mestra.
          "line-color": ["match", ["get", "level"], 0, colors.minor, colors.major],
          "line-width": ["match", ["get", "level"], 0, 0.5, 1.1],
          "line-opacity": CONTOURS.opacity,
        },
      });
    }

    if (!map.getLayer("contours-labels")) {
      map.addLayer({
        id: "contours-labels", type: "symbol", source: "contours",
        "source-layer": "contours",
        minzoom: CONTOURS.labelMinzoom,
        filter: ["all", [">", ["get", "level"], 0],
                        [">", ["get", "ele"], CONTOURS.minElevation]],
        layout: {
          "symbol-placement": "line",
          "text-field": ["concat",
            ["number-format", ["get", "ele"], { "max-fraction-digits": 0 }], " m"],
          "text-size": 10,
          "text-font": [CONTOURS.labelFont],
        },
        paint: {
          "text-color": colors.label,
          "text-halo-color": t === "dark" ? "#111111" : "#ffffff",
          "text-halo-width": 1.2,
        },
      });
    }
  } catch (err) {
    console.warn("Curvas de nível:", err);
  }
}

/**
 * Atenua elementos do mapa base que competem com os dados (POIs, estradas
 * secundárias). Heurística por id/tipo, defensiva: se falhar, mantém-se.
 */
function attenuateBaseMap() {
  const map = state.map;
  try {
    for (const layer of map.getStyle().layers || []) {
      const id = (layer.id || "").toLowerCase();
      const sl = (layer["source-layer"] || "").toLowerCase();
      if (layer.type === "symbol" && (id.includes("poi") || sl.includes("poi") || id.includes("housenumber"))) {
        for (const prop of ["icon-opacity", "text-opacity"]) {
          try { map.setPaintProperty(layer.id, prop, 0.35); } catch (_) { /* ignora */ }
        }
      } else if (layer.type === "line" && /road|street/.test(id + sl) && !/motorway|trunk|primary|secondary/.test(id + sl)) {
        try { map.setPaintProperty(layer.id, "line-opacity", 0.45); } catch (_) { /* ignora */ }
      }
    }
  } catch (err) {
    console.warn("Atenuar mapa base:", err);
  }
}

function buildReservoirHighlight() {
  const map = state.map;
  if (!map.getSource("src-res-highlight")) map.addSource("src-res-highlight", emptySource());
  if (!map.getLayer("reservoirs-highlight-fill")) {
    map.addLayer({
      id: "reservoirs-highlight-fill", type: "fill", source: "src-res-highlight", minzoom: 0,
      filter: ["==", ["get", "reservoir_id"], "__none__"],
      paint: { "fill-color": PALETTE.waterSelected, "fill-opacity": 0.45 },
    });
  }
  if (!map.getLayer("reservoirs-highlight")) {
    map.addLayer({
      id: "reservoirs-highlight", type: "line", source: "src-res-highlight", minzoom: 0,
      filter: ["==", ["get", "reservoir_id"], "__none__"],
      paint: {
        "line-color": PALETTE.waterSelected,
        "line-width": ["interpolate", ["linear"], ["zoom"], 6, 2, 12, 4.5],
        "line-opacity": 0.95,
      },
    });
  }
}

/** Destaque da rede elétrica relacionada (discreto: traço fino + halo). */
function buildRelatedHighlight() {
  const map = state.map;
  if (!map.getSource("src-related")) map.addSource("src-related", emptySource());
  if (!map.getLayer("related-halo")) {
    map.addLayer({
      id: "related-halo", type: "line", source: "src-related", minzoom: 0,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": PALETTE.related, "line-width": 7, "line-opacity": 0.18 },
    });
  }
  if (!map.getLayer("related-line")) {
    map.addLayer({
      id: "related-line", type: "line", source: "src-related", minzoom: 0,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": PALETTE.related,
        "line-width": ["interpolate", ["linear"], ["zoom"], 6, 1.5, 12, 2.6],
        "line-opacity": 0.85,
      },
    });
  }
  if (!map.getLayer("related-point")) {
    map.addLayer({
      id: "related-point", type: "circle", source: "src-related", minzoom: 0,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 5, 14, 8],
        "circle-color": PALETTE.related,
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5,
      },
    });
  }
}

function emptySource() {
  return { type: "geojson", data: { type: "FeatureCollection", features: [] } };
}

// ---------------------------------------------------------------------
// Ícones das barragens (Parte C13) — um por uso, desenhados em canvas.
// ---------------------------------------------------------------------

function damSvg(color) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
    <g stroke="#ffffff" stroke-width="1.8" stroke-linejoin="round">
      <path d="M9 6 h6 l3.2 19 H6.2 z" fill="${color}"/>
      <path d="M19 21.5 h9 v4.5 h-9 z" fill="${color}" stroke-width="1.4"/>
    </g>
  </svg>`;
}

function svgToImageData(svg, size, ratio) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = size * ratio; c.height = size * ratio;
      const ctx = c.getContext("2d");
      ctx.drawImage(img, 0, 0, c.width, c.height);
      resolve(ctx.getImageData(0, 0, c.width, c.height));
    };
    img.onerror = reject;
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  });
}

async function ensureDamIcons() {
  const map = state.map;
  const ratio = 2;
  for (const uso of USO_ORDER) {
    const id = `damicon-${uso}`;
    if (map.hasImage(id)) continue;
    try {
      const data = await svgToImageData(damSvg(USO_COLORS[uso]), DAM_ICON.size, ratio);
      if (!map.hasImage(id)) map.addImage(id, data, { pixelRatio: ratio });
    } catch (err) {
      console.warn("Ícone", uso, err);
    }
  }
}

// ---------------------------------------------------------------------
// Carregamento de dados
// ---------------------------------------------------------------------

async function loadLayerData(key) {
  const files = state.manifest?.layers?.[key];
  if (!files || files.length === 0) return null;
  if (state.data[key]) return { type: "FeatureCollection", features: state.data[key] };

  const features = [];
  const v = encodeURIComponent(state.manifest?.generated_at || Date.now());
  for (const file of files) {
    const fc = await fetchJson(`data/${file}?v=${v}`, null);
    if (fc?.features) features.push(...fc.features);
  }

  if (key === "dams") { attachNotion(features); computeDamSizes(features); buildFidIndex(features); }
  state.data[key] = features;
  return { type: "FeatureCollection", features };
}

/**
 * Índice dam_id -> fid (inteiro). O clustering do MapLibre exige ids
 * numéricos, por isso promovemos `fid` (e não o dam_id, que é texto) e
 * guardamos o mapa para a seleção/hover.
 */
function buildFidIndex(features) {
  state.fidByDam = {};
  state.damByFid = {};
  for (const f of features) {
    const p = f.properties;
    state.fidByDam[p.dam_id] = p.fid;
    state.damByFid[p.fid] = p.dam_id;
  }
}

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

/**
 * Índice das barragens para os filtros: por `dam_id`, por central (`plant_ids`
 * da barragem — as centrais não trazem `dam_id`) e por nome. Reconstruído só
 * quando os dados das barragens mudam.
 */
let damIdx = { data: null, byId: null, byPlant: null, byName: null };

function damIndex() {
  const dams = state.data.dams || [];
  if (damIdx.data === dams) return damIdx;
  const byId = new Map(), byPlant = new Map(), byName = new Map();
  for (const f of dams) {
    const p = f.properties;
    if (!p) continue;
    byId.set(p.dam_id, p);
    let pids = p.plant_ids;
    if (typeof pids === "string") { try { pids = JSON.parse(pids); } catch { pids = []; } }
    for (const pid of pids || []) byPlant.set(pid, p);
  }
  // Nomes próprios primeiro; só depois os nomes das albufeiras (numa cascata de
  // barragens a albufeira pode ter o nome da barragem seguinte — ver
  // `docs/06-notion.md`).
  for (const campo of ["name", "name_pt", "name_es"]) {
    for (const f of dams) {
      const key = damKey(f.properties?.[campo]);
      if (key && !byName.has(key)) byName.set(key, f.properties);
    }
  }
  for (const f of dams) {
    const key = damKey(f.properties?.reservoir_name);
    if (key && !byName.has(key)) byName.set(key, f.properties);
  }
  damIdx = { data: dams, byId, byPlant, byName };
  return damIdx;
}

/**
 * Liga às feições que pertencem a uma barragem (contorno, albufeira, central,
 * povoado) os atributos que os filtros usam — `uso` e, se ainda não tiverem,
 * `notion_url` — para os filtros valerem também para elas.
 *
 * A ligação é por `dam_id` (contornos, albufeiras, povoados do Notion), pelos
 * `plant_ids` da barragem (centrais) ou pelo nome da barragem (povoados curados,
 * que só trazem `barragem`). O país das camadas curadas vem em `pais`.
 *
 * Sem isto, as albufeiras e as centrais ignoravam por completo país/uso/Notion,
 * e o contorno das barragens desaparecia com o filtro «Só com página Notion».
 */
function linkToDams(features, layerKey) {
  const { byId, byPlant, byName } = damIndex();
  for (const f of features) {
    const p = f.properties;
    if (!p) continue;
    let dam = p.dam_id ? byId.get(p.dam_id) : null;
    if (!dam && layerKey === "plants") dam = byPlant.get(`${p.osm_type}/${p.osm_id}`);
    if (!dam && p.barragem) dam = byName.get(damKey(p.barragem));
    if (!p.country && p.pais) p.country = p.pais;
    // Albufeira/central sem barragem associada fica sem uso conhecido, tal como
    // as barragens sem tags de uso.
    p.uso = dam?.uso || p.uso || "desconhecido";
    if (dam?.notion_url && !p.notion_url) p.notion_url = dam.notion_url;
  }
}

/** Tamanho do ícone em função da altura ou da potência (valor por defeito). */
function computeDamSizes(features) {
  const clamp = (v) => Math.max(0, Math.min(1, v));
  features.forEach((f, i) => {
    const p = f.properties || {};
    const h = Number(p.height), pw = Number(p.plant_power_mw);
    let score = 0.35;
    if (Number.isFinite(h) && h > 0) score = Math.max(score, clamp(h / 150));
    if (Number.isFinite(pw) && pw > 0) score = Math.max(score, clamp(pw / 800));
    p.dsize = +(DAM_ICON.minSize + score * (DAM_ICON.maxSize - DAM_ICON.minSize)).toFixed(2);
    p.fid = i;   // id numérico para clustering + feature-state
  });
}

// ---------------------------------------------------------------------
// Construção de sources e layers
// ---------------------------------------------------------------------

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

  // As barragens definem `uso`/`notion_url` das restantes camadas (ver
  // `linkToDams`): se ainda não estiverem carregadas, carregar primeiro.
  if (DAM_LAYER_KEYS.has(key) && !state.loaded.has("dams")) await ensureLayer("dams");

  const fc = await loadLayerData(key);
  if (!fc) return;

  // Antes de criar a fonte: o MapLibre gera as *tiles* do GeoJSON uma só vez, no
  // momento em que o `data` é definido, e não volta a ver propriedades
  // acrescentadas depois — os filtros deixariam de as encontrar.
  if (DAM_LAYER_KEYS.has(key)) linkToDams(fc.features, key);

  state.loaded.add(key);
  if (key === "dams") { await ensureDamIcons(); addDams(fc); }
  else addGeneric(def, fc);

  // O MapLibre recusa camadas com estilo inválido **sem** lançar exceção (só
  // emite um aviso), o que deixaria a camada em falta de forma silenciosa.
  const faltam = expectedLayerIds(key).filter((id) => !map.getLayer(id));
  if (faltam.length) {
    console.error(`Camada "${key}" incompleta: faltam ${faltam.join(", ")}. Ver os avisos do MapLibre.`);
  }

  if (key === "reservoirs") {
    const hl = map.getSource("src-res-highlight");
    if (hl) hl.setData(fc);
    for (const id of ["reservoirs-highlight-fill", "reservoirs-highlight"]) {
      if (map.getLayer(id)) map.moveLayer(id);
    }
  }
  setVisibility(key, state.visible[key] ?? def.default, true);
}

function addGeneric(def, fc) {
  const map = state.map;
  const srcId = `src-${def.key}`;
  if (!map.getSource(srcId)) {
    const src = { type: "geojson", data: fc };
    if (def.kind === "polygon") src.promoteId = "reservoir_id";
    map.addSource(srcId, src);
  }

  const color = def.color || "#888";
  if (def.kind === "line") {
    map.addLayer({
      id: `${def.key}-line`, type: "line", source: srcId, minzoom: def.minzoom,
      paint: { "line-color": color, "line-width": 1.3, "line-opacity": 0.8 },
    });
  } else if (def.kind === "outline") {
    const colorExpr = def.key === "dam_geoms" ? usoColorExpression() : color;
    map.addLayer({ id: `${def.key}-fill`, type: "fill", source: srcId, minzoom: def.minzoom, paint: { "fill-color": colorExpr, "fill-opacity": 0.22 } });
    map.addLayer({
      id: `${def.key}-line`, type: "line", source: srcId, minzoom: def.minzoom,
      paint: { "line-color": colorExpr, "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1.6, 16, 3.2], "line-opacity": 0.9 },
    });
  } else if (def.kind === "curated") {
    // Camadas curadas (povoados submersos, bairros novos): pontos cujo rótulo
    // aparece a partir de um certo zoom. Se a feature tiver `confianca`, a cor
    // codifica-a; caso contrário usa a cor da camada.
    map.addLayer({
      id: `${def.key}-point`, type: "circle", source: srcId, minzoom: def.minzoom,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 4, 12, 7],
        "circle-color": confiancaColorExpression(color),
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1.2,
        "circle-opacity": 0.92,
      },
    });
    map.addLayer({
      id: `${def.key}-label`, type: "symbol", source: srcId, minzoom: Math.max(def.minzoom, 9),
      layout: { "text-field": ["get", "name"], "text-size": 11, "text-offset": [0, 1.1], "text-anchor": "top" },
      paint: { "text-color": "#3a3a3a", "text-halo-color": "#ffffff", "text-halo-width": 1.4 },
    });
  } else if (def.kind === "poi") {
    // Pontos de interesse (património): polígono/linha + rótulo do nome.
    map.addLayer({ id: `${def.key}-fill`, type: "fill", source: srcId, minzoom: def.minzoom, paint: { "fill-color": color, "fill-opacity": 0.28 } });
    map.addLayer({ id: `${def.key}-line`, type: "line", source: srcId, minzoom: def.minzoom, paint: { "line-color": color, "line-width": 1.8, "line-opacity": 0.95 } });
    map.addLayer({
      id: `${def.key}-label`, type: "symbol", source: srcId, minzoom: Math.max(def.minzoom, 12),
      layout: { "text-field": ["get", "name"], "text-size": 12, "text-offset": [0, 1.1], "text-anchor": "top" },
      paint: { "text-color": color, "text-halo-color": "#ffffff", "text-halo-width": 1.4 },
    });
  } else if (def.kind === "polygon") {
    const outline = def.key === "reservoirs" ? PALETTE.waterOutline : color;
    map.addLayer({ id: `${def.key}-fill`, type: "fill", source: srcId, minzoom: def.minzoom, paint: { "fill-color": color, "fill-opacity": 0.35 } });
    map.addLayer({ id: `${def.key}-outline`, type: "line", source: srcId, minzoom: def.minzoom, paint: { "line-color": outline, "line-width": 0.8, "line-opacity": 0.7 } });
  } else {
    map.addLayer({
      id: `${def.key}-point`, type: "circle", source: srcId, minzoom: def.minzoom,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 3, 12, 5.5],
        "circle-color": color, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1,
      },
    });
  }
}

function usoColorExpression() {
  const expr = ["match", ["get", "uso"]];
  for (const uso of USO_ORDER) expr.push(uso, USO_COLORS[uso]);
  expr.push(USO_COLORS["desconhecido"]);
  return expr;
}

function usoIconExpression() {
  const expr = ["match", ["get", "uso"]];
  for (const uso of USO_ORDER) expr.push(uso, `damicon-${uso}`);
  expr.push("damicon-desconhecido");
  return expr;
}

function confiancaColorExpression(fallback) {
  const expr = ["match", ["get", "confianca"]];
  for (const c of CONFIANCA_ORDER) expr.push(c, CONFIANCA_COLORS[c]);
  expr.push(fallback || CONFIANCA_COLORS.por_verificar);
  return expr;
}

/** Camadas das barragens: ícone (tamanho por altura/potência) e, se ligado,
 *  clustering.
 */
function addDams(fc) {
  const map = state.map;
  const clustered = CLUSTER.enabled;
  const source = { type: "geojson", data: fc, promoteId: "fid" };
  if (clustered) {
    source.cluster = true;
    source.clusterRadius = CLUSTER.radius;
    source.clusterMaxZoom = CLUSTER.maxZoom;
  }
  map.addSource(damsSourceId, source);

  const pointOnly = clustered ? ["!", ["has", "point_count"]] : ["all"];

  if (clustered) {
    map.addLayer({
      id: "dams-clusters", type: "circle", source: damsSourceId, minzoom: 0,
      filter: ["has", "point_count"],
      paint: {
        "circle-color": PALETTE.cluster, "circle-opacity": 0.88,
        "circle-radius": ["step", ["get", "point_count"], 14, 20, 18, 100, 24],
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5,
      },
    });
    map.addLayer({
      id: "dams-cluster-count", type: "symbol", source: damsSourceId, minzoom: 0,
      filter: ["has", "point_count"],
      layout: { "text-field": ["to-string", ["get", "point_count"]], "text-size": 12 },
      paint: { "text-color": "#ffffff" },
    });
  }

  // Anel da barragem selecionada (por baixo do ícone).
  map.addLayer({
    id: "dams-selected", type: "circle", source: damsSourceId, minzoom: 0,
    filter: pointOnly,
    paint: {
      "circle-radius": ["case", sel(), 15, 0],
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-color": PALETTE.related, "circle-stroke-width": ["case", sel(), 2.5, 0],
    },
  });

  // Anel ao passar o rato (a partir da lista).
  map.addLayer({
    id: "dams-hover", type: "circle", source: damsSourceId, minzoom: 0,
    filter: pointOnly,
    paint: {
      "circle-radius": ["case", hov(), 12, 0],
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-color": "#ffffff", "circle-stroke-width": ["case", hov(), 2, 0],
      "circle-opacity": ["case", hov(), 0.9, 0],
    },
  });

  // Ícone da barragem, colorido por uso e dimensionado. Sem clustering, a
  // colocação anti-colisão evita a sobreposição em zoom baixo.
  map.addLayer({
    id: "dams-points", type: "symbol", source: damsSourceId, minzoom: 0,
    filter: pointOnly,
    layout: {
      "icon-image": usoIconExpression(),
      // O `zoom` só pode aparecer no topo de um `interpolate`/`step`; por isso
      // o tamanho por barragem (`dsize`) entra nos valores de saída.
      "icon-size": ["interpolate", ["linear"], ["zoom"],
                    5, ["*", ["coalesce", ["get", "dsize"], 0.7], 0.6],
                    12, ["*", ["coalesce", ["get", "dsize"], 0.7], 1],
                    16, ["*", ["coalesce", ["get", "dsize"], 0.7], 1.08]],
      "icon-allow-overlap": false,
      "icon-ignore-placement": false,
    },
  });

  // Anel dourado para barragens com página Notion.
  map.addLayer({
    id: "dams-notion", type: "circle", source: damsSourceId, minzoom: 0,
    filter: ["all", ...(clustered ? [["!", ["has", "point_count"]]] : []), ["has", "notion_url"]],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 8, 14, 13],
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-color": PALETTE.notion, "circle-stroke-width": 2,
    },
  });
}

function sel() {
  return ["boolean", ["feature-state", "selected"], false];
}

function hov() {
  return ["boolean", ["feature-state", "hover"], false];
}

/** Destaca (ou não) uma barragem ao passar o rato na lista. */
export function setHover(damId) {
  const map = state.map;
  if (!map || !state.loaded.has("dams")) return;
  const fid = damId != null ? state.fidByDam?.[damId] : null;
  if (state.hoverFid != null && state.hoverFid !== fid) {
    map.setFeatureState({ source: damsSourceId, id: state.hoverFid }, { hover: false });
  }
  state.hoverFid = fid ?? null;
  if (fid != null) map.setFeatureState({ source: damsSourceId, id: fid }, { hover: true });
}

// ---------------------------------------------------------------------
// Visibilidade
// ---------------------------------------------------------------------

const layerIdsByKey = (key) => {
  if (key === "dams") return ["dams-clusters", "dams-cluster-count", "dams-selected", "dams-hover", "dams-points", "dams-notion"];
  const def = LAYERS.find((l) => l.key === key);
  if (!def) return [];
  if (def.kind === "line") return [`${key}-line`];
  if (def.kind === "polygon") return [`${key}-fill`, `${key}-outline`];
  if (def.kind === "outline") return [`${key}-fill`, `${key}-line`];
  if (def.kind === "poi") return [`${key}-fill`, `${key}-line`, `${key}-label`];
  if (def.kind === "curated") return [`${key}-point`, `${key}-label`];
  return [`${key}-point`];
};

/** Ids de camada que a chave deve criar (para validar que foi mesmo criada). */
function expectedLayerIds(key) {
  if (key !== "dams") return layerIdsByKey(key);
  const ids = ["dams-selected", "dams-hover", "dams-points", "dams-notion"];
  if (CLUSTER.enabled) ids.push("dams-clusters", "dams-cluster-count");
  return ids;
}

export function setVisibility(key, visible, force = false) {
  state.visible[key] = visible;
  if (key === "dams") setVisibility("dam_geoms", visible, force);
  if (!state.loaded.has(key) && visible) {
    ensureLayer(key).then(() => state.map && applyFilters(state.filters));
    return;
  }
  if (!state.loaded.has(key)) return;
  const map = state.map;
  for (const id of layerIdsByKey(key)) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
  if (key === "reservoirs") {
    for (const id of ["reservoirs-highlight-fill", "reservoirs-highlight"]) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
    }
  }
}

// ---------------------------------------------------------------------
// Filtros
// ---------------------------------------------------------------------

export function applyFilters(filters) {
  state.filters = filters;
  const map = state.map;
  if (!map || !state.loaded.has("dams")) return;

  const pointConds = [["!", ["has", "point_count"]], ...countryUsoNotionConds(filters)];
  const pointFilter = ["all", ...pointConds];

  if (map.getLayer("dams-points")) map.setFilter("dams-points", pointFilter);
  if (map.getLayer("dams-selected")) map.setFilter("dams-selected", pointFilter);
  if (map.getLayer("dams-notion")) map.setFilter("dams-notion", ["all", ...pointConds, ["has", "notion_url"]]);

  if (map.getLayer("dams-clusters")) map.setFilter("dams-clusters", ["has", "point_count"]);
  if (map.getLayer("dams-cluster-count")) {
    map.setLayoutProperty("dams-cluster-count", "text-field", ["to-string", ["get", "point_count"]]);
  }

  // Camadas que pertencem a uma barragem: país, uso e Notion (os atributos
  // foram copiados em `linkToDams`, antes de a fonte ser criada).
  const ctxConds = countryUsoNotionConds(filters);
  const ctxFilter = ctxConds.length ? ["all", ...ctxConds] : null;
  for (const [, ids] of DAM_LAYERS) {
    for (const id of ids) if (map.getLayer(id)) map.setFilter(id, ctxFilter);
  }

  const cc = countryConds(filters);
  const countryFilter = cc.length ? ["all", ...cc] : null;
  for (const id of COUNTRY_LAYERS) if (map.getLayer(id)) map.setFilter(id, countryFilter);
}

function countryConds(filters) {
  return (filters.country && filters.country !== "all")
    ? [["==", ["get", "country"], filters.country]] : [];
}

function countryUsoNotionConds(filters) {
  const conds = countryConds(filters);
  if (filters.usos && filters.usos.length > 0 && filters.usos.length < USO_ORDER.length) {
    conds.push(["in", ["get", "uso"], ["literal", filters.usos]]);
  }
  if (filters.onlyNotion) conds.push(["has", "notion_url"]);
  return conds;
}

// ---------------------------------------------------------------------
// Seleção e destaques
// ---------------------------------------------------------------------

export function selectDam(damId, reservoirId) {
  const map = state.map;
  if (!map || !state.loaded.has("dams")) return;

  const fid = damId != null ? state.fidByDam?.[damId] : null;
  if (state.selectedFid != null && state.selectedFid !== fid) {
    map.setFeatureState({ source: damsSourceId, id: state.selectedFid }, { selected: false });
  }
  state.selectedDam = damId || null;
  state.selectedFid = fid ?? null;
  if (fid != null) map.setFeatureState({ source: damsSourceId, id: fid }, { selected: true });

  state.selectedReservoir = reservoirId || null;
  const rid = reservoirId || "__none__";
  for (const id of ["reservoirs-highlight", "reservoirs-highlight-fill"]) {
    if (map.getLayer(id)) map.setFilter(id, ["==", ["get", "reservoir_id"], rid]);
  }

  dimNetwork(!!damId);
}

/** Esbate as camadas de rede base quando há uma barragem selecionada (C12). */
function dimNetwork(dim) {
  const map = state.map;
  const targets = {
    plants: ["plants-point"],
    substations: ["substations-point"],
    power_lines: ["power_lines-line"],
    conduits: ["conduits-line"],
    weirs: ["weirs-point"],
  };
  for (const ids of Object.values(targets)) {
    for (const id of ids) {
      if (!map.getLayer(id)) continue;
      const prop = id.endsWith("-point") ? "circle-opacity" : "line-opacity";
      const normal = id.endsWith("-point") ? 1 : (id.includes("power_lines") ? 0.8 : (id.includes("conduits") ? 0.8 : 1));
      try { map.setPaintProperty(id, prop, dim ? RELATED.dim : normal); } catch (_) { /* ignora */ }
    }
  }
}

const RELATED_RADIUS = { line: RELATED.line, sub: RELATED.sub };

export async function highlightRelated(dam) {
  const map = state.map;
  const src = map.getSource("src-related");
  if (!src) return null;
  if (!dam) { src.setData(emptySource().data); return null; }

  const p = dam.properties || {};
  for (const k of ["plants", "substations", "power_lines"]) await ensureLayer(k);

  const idOf = (f) => `${f.properties.osm_type}/${f.properties.osm_id}`;
  const plants = state.data.plants || [];
  const subs = state.data.substations || [];
  const lines = state.data.power_lines || [];

  let plantIds = p.plant_ids;
  if (typeof plantIds === "string") { try { plantIds = JSON.parse(plantIds); } catch { plantIds = []; } }
  const ids = new Set(plantIds || []);

  const relPlants = plants.filter((f) => ids.has(idOf(f)));
  const plantPts = relPlants.map((f) => pointOf(f.geometry)).filter(Boolean);
  const relLines = lines.filter((f) => plantPts.some((pt) => distanceToGeometryM(pt, f.geometry) <= RELATED_RADIUS.line));
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
    nSubs: relSubs.length, nLines: relLines.length,
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
// Reconstrução (tema) e recarga de dados
// ---------------------------------------------------------------------

export function rebuildAfterStyleChange() {
  const map = state.map;
  state.loaded.clear();
  addHillshade();
  addContours();
  attenuateBaseMap();
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
    }
    setVisibility(key, state.visible[key] ?? def.default, true);
  }
  applyFilters(state.filters);
  if (state.selectedDam) selectDam(state.selectedDam, state.selectedReservoir);
}

export async function reloadData() {
  const map = state.map;
  for (const def of LAYERS) {
    for (const id of layerIdsByKey(def.key)) if (map.getLayer(id)) map.removeLayer(id);
  }
  for (const id of ["reservoirs-highlight", "reservoirs-highlight-fill", "related-halo", "related-line", "related-point"]) {
    if (map.getLayer(id)) map.removeLayer(id);
  }
  const srcIds = [damsSourceId, "src-res-highlight", "src-related", ...LAYERS.map((d) => `src-${d.key}`)];
  for (const id of srcIds) if (map.getSource(id)) map.removeSource(id);

  state.loaded.clear();
  state.loading = {};
  state.data = {};
  buildReservoirHighlight();
  buildRelatedHighlight();
  for (const def of LAYERS) if (state.visible[def.key]) await ensureLayer(def.key);
  applyFilters(state.filters);
  if (state.selectedDam) selectDam(state.selectedDam, state.selectedReservoir);
}

// ---------------------------------------------------------------------
// Acesso aos dados
// ---------------------------------------------------------------------

export function setNotion(notion) { state.notion = notion || {}; }
export function getDam(damId) { return (state.data.dams || []).find((f) => f.properties.dam_id === damId) || null; }
export function allDams() { return state.data.dams || []; }
export function allReservoirs() { return state.data.reservoirs || []; }
export function isLoaded(key) { return state.loaded.has(key); }
export function selectedDamId() { return state.selectedDam; }

/** Carrega só os dados de uma camada (sem a desenhar no mapa). */
export function preloadLayerData(key) { return loadLayerData(key).catch(() => null); }

/** Chave de comparação de nomes de barragem/albufeira (sem acentos/prefixos). */
function damKey(name) {
  let t = normalize(name || "").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  for (const p of ["barragem de ", "barragem da ", "barragem do ", "barragem ",
    "presa de ", "presa da ", "presa del ", "presa ",
    "embalse de ", "embalse del ", "embalse ",
    "albufeira de ", "albufeira da ", "albufeira do ", "albufeira ",
    "encoro de ", "encoro da ", "encoro do ", "encoro "]) {
    if (t.startsWith(p)) { t = t.slice(p.length); break; }
  }
  return t.trim();
}

/**
 * Aldeias submersas e bairros ligados a uma barragem.
 * Liga por `dam_id` (exato); se faltar, tenta pelo nome da barragem-mãe.
 */
export function curatedForDam(damId, damName) {
  const out = [];
  const key = damKey(damName);
  for (const layerKey of ["submersos", "bairros"]) {
    for (const f of state.data[layerKey] || []) {
      const p = f.properties || {};
      const byId = damId && p.dam_id && p.dam_id === damId;
      const byName = key && damKey(p.barragem) === key;
      if (byId || byName) out.push({ layer: layerKey, ...p });
    }
  }
  return out;
}
