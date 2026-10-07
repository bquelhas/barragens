// =====================================================================
// Configuração central do frontend.
// Espelha parte de `scripts/config.py`. Alterações aqui mudam cores,
// estilos de mapa, camadas e comportamentos sem mexer no resto do código.
// =====================================================================

// --- Mapa ------------------------------------------------------------
export const MAP = {
  center: [-4.2, 40.0],   // Península Ibérica
  zoom: 5.2,
  minZoom: 3,
  maxZoom: 18,
  // Estilos do OpenFreeMap (sem chave). `dark` para o modo escuro.
  styles: {
    light: "https://tiles.openfreemap.org/styles/positron",
    dark: "https://tiles.openfreemap.org/styles/dark",
  },
  attribution:
    '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
};

// --- Cores por uso ---------------------------------------------------
export const USO_COLORS = {
  "hidroelétrica": "#1f6feb",
  "regadio": "#d99b00",
  "abastecimento": "#12a150",
  "misto": "#8250df",
  "desconhecido": "#8b98a5",
};

export const USO_LABELS = {
  "hidroelétrica": "Hidroelétrica",
  "regadio": "Regadio",
  "abastecimento": "Abastecimento",
  "misto": "Misto",
  "desconhecido": "Desconhecido",
};

export const USO_ORDER = ["hidroelétrica", "regadio", "abastecimento", "misto", "desconhecido"];

// Cor de destaque (barragem selecionada / contornos).
export const HIGHLIGHT = "#ff7a1a";
export const NOTION_COLOR = "#ffb020";

// --- Camadas ---------------------------------------------------------
// `key` corresponde ao nome no manifest.json. `minzoom` esconde a camada
// abaixo desse zoom. `default` liga/desliga a camada ao carregar.
export const LAYERS = [
  {
    key: "dams", label: "Barragens", kind: "dams",
    minzoom: 0, default: true, legendSwatch: "circle", primary: true,
  },
  {
    key: "reservoirs", label: "Albufeiras", kind: "polygon",
    minzoom: 4, default: true, color: "#2b8fe0", legendSwatch: "polygon",
  },
  {
    key: "plants", label: "Centrais hidroelétricas", kind: "point",
    minzoom: 6, default: true, color: "#e0731a", legendSwatch: "circle",
  },
  {
    key: "weirs", label: "Açudes", kind: "point",
    minzoom: 11, default: false, color: "#7da7c9", legendSwatch: "circle",
  },
  {
    key: "substations", label: "Subestações", kind: "point",
    minzoom: 9, default: false, color: "#8a6df0", legendSwatch: "circle",
  },
  {
    key: "power_lines", label: "Linhas elétricas", kind: "line",
    minzoom: 8, default: false, color: "#f0803c", legendSwatch: "line",
  },
  {
    key: "conduits", label: "Condutas e canais", kind: "line",
    minzoom: 9, default: false, color: "#39b8c9", legendSwatch: "line",
  },
  // Fase 2 — bairros barragistas (desligada por defeito).
  {
    key: "bairros", label: "Bairros barragistas", kind: "polygon",
    minzoom: 7, default: false, color: "#c07ad0", legendSwatch: "polygon", future: true,
  },
];

// --- Ficheiros -------------------------------------------------------
export const DATA = {
  manifest: "data/manifest.json",
  notion: "data/notion.json",
};

// --- Clustering ------------------------------------------------------
export const CLUSTER = {
  radius: 46,
  maxZoom: 12,
};
