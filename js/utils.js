// Utilitários pequenos e reutilizáveis.

/** Remove acentos e passa a minúsculas (para pesquisa tolerante). */
export function normalize(text) {
  if (!text) return "";
  return text
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();
}

/** Escapa HTML para inserir texto do utilizador/OSM em segurança. */
export function escapeHtml(text) {
  if (text == null) return "";
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Formata um número com separadores locais de Portugal. */
export function fmtNumber(value, decimals = 0) {
  if (value == null || value === "" || Number.isNaN(value)) return "—";
  return Number(value).toLocaleString("pt-PT", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Debounce simples baseado em temporizador. */
export function debounce(fn, delay = 180) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), delay);
  };
}

/** Lê um ficheiro JSON, devolvendo um valor por omissão em caso de falha. */
export async function fetchJson(url, fallback = null) {
  try {
    const resp = await fetch(url, { cache: "no-cache" });
    if (!resp.ok) throw new Error(`${resp.status} em ${url}`);
    return await resp.json();
  } catch (err) {
    console.warn(`Não foi possível carregar ${url}:`, err.message);
    return fallback;
  }
}

// --- Geometria aproximada (para destacar infraestrutura próxima) --------

const R_EARTH = 6371000;
const RAD = Math.PI / 180;

/** Distância aproximada (m) entre dois pontos [lon, lat]. */
export function distanceM([lon1, lat1], [lon2, lat2]) {
  const dLat = (lat2 - lat1) * RAD;
  const dLon = (lon2 - lon1) * RAD;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * R_EARTH * Math.asin(Math.sqrt(a));
}

/** Distância (m) de um ponto a um segmento [a, b] (projeção local plana). */
function segmentDistanceM(p, a, b) {
  const cosLat = Math.cos(p[1] * RAD);
  const ax = (a[0] - p[0]) * RAD * cosLat * R_EARTH;
  const ay = (a[1] - p[1]) * RAD * R_EARTH;
  const bx = (b[0] - p[0]) * RAD * cosLat * R_EARTH;
  const by = (b[1] - p[1]) * RAD * R_EARTH;
  const vx = bx - ax;
  const vy = by - ay;
  const len2 = vx * vx + vy * vy;
  let t = len2 ? -(ax * vx + ay * vy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  const dx = ax + t * vx;
  const dy = ay + t * vy;
  return Math.hypot(dx, dy);
}

/** Lista de linhas (arrays de [lon,lat]) de uma geometria GeoJSON. */
export function linesOf(geometry) {
  if (!geometry) return [];
  const t = geometry.type;
  if (t === "LineString") return [geometry.coordinates];
  if (t === "MultiLineString") return geometry.coordinates;
  if (t === "Polygon") return geometry.coordinates;
  if (t === "MultiPolygon") return geometry.coordinates.flat();
  return [];
}

/** Distância mínima (m) de um ponto a uma geometria de linha/área. */
export function distanceToGeometryM(point, geometry) {
  if (geometry?.type === "Point") return distanceM(point, geometry.coordinates);
  let best = Infinity;
  for (const line of linesOf(geometry)) {
    for (let i = 0; i < line.length - 1; i++) {
      best = Math.min(best, segmentDistanceM(point, line[i], line[i + 1]));
    }
    if (line.length === 1) best = Math.min(best, distanceM(point, line[0]));
  }
  return best;
}

/** Ponto representativo (média) de uma geometria GeoJSON, como [lon, lat]. */
export function pointOf(geometry) {
  if (!geometry) return null;
  if (geometry.type === "Point") return geometry.coordinates;
  const pts = [];
  const walk = (o) => {
    if (Array.isArray(o) && typeof o[0] === "number") pts.push(o);
    else if (Array.isArray(o)) o.forEach(walk);
  };
  walk(geometry.coordinates);
  if (!pts.length) return null;
  const s = pts.reduce((a, c) => [a[0] + c[0], a[1] + c[1]], [0, 0]);
  return [s[0] / pts.length, s[1] / pts.length];
}
