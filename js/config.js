// =====================================================================
// Configuração central do frontend.
// Espelha parte de `scripts/config.py`. Alterações aqui (nome, cores,
// camadas, destaques, limiares) mudam o site sem mexer no resto do código.
// =====================================================================

// --- Identidade do projeto -------------------------------------------
export const PROJECT = {
  name: "Águas Represadas",
  subtitle: "Barragens, albufeiras e o seu património — Portugal e Espanha",
  // Nomes alternativos (para referência): "Pedra e Água", "Barragens Ibéricas"
};

// --- Mapa ------------------------------------------------------------
export const MAP = {
  center: [-4.2, 40.0],   // Península Ibérica
  zoom: 5.2,
  minZoom: 3,
  maxZoom: 18,
  styles: {
    light: "https://tiles.openfreemap.org/styles/positron",
    dark: "https://tiles.openfreemap.org/styles/dark",
  },
  attribution:
    '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
};

// --- Paleta (betão, água, xisto, granito) ----------------------------
export const PALETTE = {
  water: "#2f7fb5",        // albufeiras (distinto dos rios do mapa base)
  waterOutline: "#1c5a80",
  waterSelected: "#123f5c",
  related: "#c8892b",      // rede elétrica relacionada (âmbar dessaturado)
  notion: "#d9a441",       // ★ / anel dourado
  poi: "#8a5a44",          // pontos de interesse (património)
  submerged: "#2f8f6b",    // povoados submersos (cor-base = documentado)
  cluster: "#17516e",
};

// Povoados submersos: a cor do ponto indica o grau de confiança da fonte.
// (Sem inventário oficial — cada caso traz a sua ressalva na ficha.)
export const CONFIANCA_COLORS = {
  confirmado: "#2f8f6b",   // verde-água — documentado em fontes
  provavel: "#c8892b",     // âmbar — provável, por confirmar
  por_verificar: "#8b9096",// cinza — por verificar
};

export const CONFIANCA_LABELS = {
  confirmado: "Confirmado em fontes",
  provavel: "Provável — por confirmar",
  por_verificar: "Por verificar",
};

export const CONFIANCA_ORDER = ["confirmado", "provavel", "por_verificar"];

// Cores por uso — escolhidas para manter contraste AA e serem
// distinguíveis em deuteranopia (azul / âmbar / verde-água / violeta / cinza,
// com diferenças de luminosidade).
export const USO_COLORS = {
  "hidroelétrica": "#2f6fb0",
  "regadio": "#e0a12a",
  "abastecimento": "#4d9f93",
  "misto": "#8e5bd0",
  "desconhecido": "#8b9096",
};

export const USO_LABELS = {
  "hidroelétrica": "Hidroelétrica",
  "regadio": "Regadio",
  "abastecimento": "Abastecimento",
  "misto": "Misto",
  "desconhecido": "Desconhecido",
};

export const USO_ORDER = ["hidroelétrica", "regadio", "abastecimento", "misto", "desconhecido"];

export const HIGHLIGHT = PALETTE.related;
export const NOTION_COLOR = PALETTE.notion;

// --- Camadas ---------------------------------------------------------
export const LAYERS = [
  { key: "dams", label: "Barragens", kind: "dams", minzoom: 0, default: true, legendSwatch: "circle", primary: true },
  { key: "dam_geoms", label: "Contorno das barragens", kind: "outline", minzoom: 12, default: true, internal: true, color: "#16324a", legendSwatch: "line" },
  { key: "reservoirs", label: "Albufeiras", kind: "polygon", minzoom: 4, default: true, color: PALETTE.water, legendSwatch: "polygon" },
  { key: "plants", label: "Centrais hidroelétricas", kind: "point", minzoom: 6, default: true, color: "#c97a2b", legendSwatch: "circle" },
  { key: "weirs", label: "Açudes", kind: "point", minzoom: 11, default: false, color: "#7fa6bd", legendSwatch: "circle" },
  { key: "substations", label: "Subestações", kind: "point", minzoom: 9, default: false, color: "#8e7cc3", legendSwatch: "circle" },
  { key: "power_lines", label: "Linhas elétricas", kind: "line", minzoom: 8, default: false, color: "#c8892b", legendSwatch: "line" },
  { key: "conduits", label: "Condutas e canais", kind: "line", minzoom: 9, default: false, color: "#4f9aa8", legendSwatch: "line" },
  { key: "pois", label: "Pontos de interesse", kind: "poi", minzoom: 11, default: true, color: "#8a5a44", legendSwatch: "polygon" },
  { key: "submersos", label: "Povoados submersos", kind: "curated", minzoom: 6, default: true, color: CONFIANCA_COLORS.confirmado, legendSwatch: "circle" },
  { key: "bairros", label: "Bairros novos", kind: "curated", minzoom: 7, default: false, color: "#b07aa1", legendSwatch: "circle" },
];

// --- Ícone das barragens (Parte C) -----------------------------------
export const DAM_ICON = {
  size: 32,          // px do ícone base
  minSize: 0.55,     // multiplicador mínimo (dams sem dados)
  maxSize: 1.15,     // multiplicador máximo (dams grandes)
};

// --- Rede relacionada (C12) ------------------------------------------
export const RELATED = {
  line: 300,   // m — linhas que chegam às centrais
  sub: 400,    // m — subestações nessas ligações
  dim: 0.16,   // opacidade das camadas de rede quando há seleção
};

// --- Hillshade (B10) -------------------------------------------------
// Desligado por omissão: o relevo é dado pelas curvas de nível (`CONTOURS`).
// Continua disponível (e partilha as mesmas tiles de elevação).
export const HILLSHADE = {
  enabled: false,
  tiles: "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
  encoding: "terrarium",
  tileSize: 256,
  maxzoom: 13,
  exaggeration: 0.35,
  attribution: "Relevo: Terrain Tiles (AWS/Mapzen, CC-BY)",
};

// --- Curvas de nível (maplibre-contour) ------------------------------
// Geradas **no browser** a partir das mesmas tiles de relevo do hillshade
// (biblioteca `maplibre-contour`, carregada por CDN em `index.html`). Só
// funciona com ligação à rede; se a biblioteca falhar, o mapa segue sem curvas.
// `terrarium` é o formato nativo do plugin e o das tiles que já usamos.
export const CONTOURS = {
  enabled: true,
  encoding: "terrarium",   // "terrarium" (AWS/Mapzen) | "mapbox"
  maxzoom: 13,             // zoom máximo das tiles de relevo (igual ao DEM)
  sourceMaxzoom: 15,       // zoom máximo a que o MapLibre pede tiles ao plugin
  worker: true,            // calcular num web worker (não bloqueia o interface)
  cacheSize: 100,          // tiles de relevo guardadas em memória
  timeoutMs: 10000,
  // Intervalos por zoom, em metros: [menor, mestra]. A mestra tem de ser
  // múltipla da menor — é isso que a distingue nas linhas e nos rótulos.
  // Aos zooms mais afastados os intervalos são largos de propósito: linhas de
  // 10 m sobre a Península inteira seriam uma mancha.
  thresholds: {
    3: [500, 1000], 4: [500, 1000], 5: [500, 1000], 6: [200, 1000],
    7: [200, 1000], 8: [200, 500], 9: [100, 500], 10: [100, 500],
    11: [50, 250], 12: [25, 100], 13: [10, 50], 14: [10, 50], 15: [10, 50],
  },
  // Cores por tema (o mapa base é claro ou escuro).
  colors: {
    light: { minor: "#b6a692", major: "#8a755c", label: "#6b5c47" },
    dark: { minor: "#5f5748", major: "#8d8067", label: "#cbbfa5" },
  },
  opacity: 0.45,
  // As tiles de relevo incluem batimetria (cotas negativas no oceano). Só
  // interessam as cotas acima deste valor, para o mar ficar limpo.
  minElevation: 0,
  // Rótulos das cotas: só nas linhas mestras e a partir deste zoom.
  // "Noto Sans Regular" é a única fonte que os estilos claro e escuro servem.
  labelMinzoom: 12,
  labelFont: "Noto Sans Regular",
};

// --- Destaques (E16) -------------------------------------------------
// Localizados nos dados por nome normalizado (sem acentos, minúsculas).
// São omitidos os que não existirem.
export const FEATURED = [
  { name: "Alqueva" },
  { name: "Aldeadávila" },
  { name: "Miranda" },
  { name: "Castelo do Bode" },
  { name: "Alcántara" },
  { name: "Mequinenza" },
  { name: "Ribeiradio" },
];

// --- Ficheiros -------------------------------------------------------
export const DATA = {
  manifest: "data/manifest.json",
  notion: "data/notion.json",
};

// --- Clustering (despoluição em zoom baixo) --------------------------
// Nota: o clustering do MapLibre revelou-se pouco fiável neste ambiente
// (o worker não produzia tiles). Fica configurável e DESLIGADO por defeito;
// a despoluição é feita pela colocação anti-colisão dos símbolos.
// Ativa com `enabled: true` se confirmar que funciona no teu browser.
export const CLUSTER = { enabled: false, radius: 46, maxZoom: 12 };

// --- Chaves de armazenamento local -----------------------------------
export const STORAGE = { theme: "ar-theme", welcome: "ar-welcome-seen" };
