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
