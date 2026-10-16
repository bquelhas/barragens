"""
Utilitários partilhados para traduzir o id do OSM (coluna "OSM" do Notion)
para o `dam_id` da barragem correspondente.

Aceita o id de uma **barragem** (`waterway=dam`) ou de uma **albufeira**
(reservoir): uma albufeira é traduzida para a barragem associada, usando a
ligação que o pipeline já calculou (`reservoir_id -> dam_id`).

Os dados são lidos de `data/dams_*.geojson` e `data/reservoirs_*.geojson`.
Não acede à rede.
"""

from __future__ import annotations

import glob
import json
import re
import unicodedata

import config

# Aceita "way/123", "way 123", "relation/1" e URLs completas do OSM.
_ID_RE = re.compile(r"(node|way|relation)\s*[/ ]\s*(\d+)", re.IGNORECASE)
_URL_RE = re.compile(r"openstreetmap\.org/(node|way|relation)/(\d+)", re.IGNORECASE)


def normalize_osm_id(raw: str | None) -> str | None:
    """Normaliza um valor colado pelo utilizador para `tipo/id` (minúsculas)."""
    if not raw:
        return None
    text = str(raw).strip()
    m = _URL_RE.search(text) or _ID_RE.search(text)
    if not m:
        return None
    return f"{m.group(1).lower()}/{m.group(2)}"


def find_property(props: dict | None, *names: str) -> tuple[str | None, dict | None]:
    """Encontra uma propriedade pelo nome, ignorando maiúsculas/minúsculas.

    Devolve (nome_original, propriedade) ou (None, None).
    """
    if not props:
        return None, None
    want = {n.strip().lower() for n in names if n}
    for name, prop in props.items():
        if name.strip().lower() in want:
            return name, prop
    return None, None


# Código de tipo no início do título do Notion: `AS` = Aldeia submersa,
# `BN` = Bairro novo (ex.: "AS Venda Nova", "BN Salamonde"). É só um marcador
# de tipo — `Tipo_objeto` já o diz e a ficha já o mostra — por isso sai do nome
# que vai para o mapa. Exige maiúsculas e um separador (ou o fim do título),
# para não cortar topónimos que comecem por "As…"/"Bn…".
_TITLE_CODE_RE = re.compile(r"^(?:AS|BN)(?:[\s\-–—:.]+|$)")


def clean_title(title: str | None) -> str:
    """Tira o código de tipo (`AS `/`BN `) do início do título."""
    text = (title or "").strip()
    if not text:
        return text
    stripped = _TITLE_CODE_RE.sub("", text, count=1).strip()
    return stripped or text


def _override_key(title: str | None) -> str:
    """Chave de comparação de títulos: sem código de tipo, acentos ou caixa."""
    text = unicodedata.normalize("NFKD", clean_title(title))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.casefold().split())


_OVERRIDES_CACHE: dict[str, str] | None = None


def manual_dam(title: str | None) -> str | None:
    """Id OSM definido à mão para esta página (`config.NOTION_OSM_OVERRIDES`)."""
    global _OVERRIDES_CACHE
    if _OVERRIDES_CACHE is None:
        _OVERRIDES_CACHE = {_override_key(k): v
                            for k, v in (config.NOTION_OSM_OVERRIDES or {}).items()}
    return _OVERRIDES_CACHE.get(_override_key(title))


def _iter_features(layer: str):
    patterns = [str(config.DATA_DIR / f"{layer}_*.geojson")]
    single = config.DATA_DIR / f"{layer}.geojson"
    if single.exists():
        patterns.append(str(single))
    for path in sorted({p for pat in patterns for p in glob.glob(pat)}):
        try:
            with open(path, encoding="utf-8") as fh:
                yield from json.load(fh).get("features", [])
        except Exception:  # noqa: BLE001
            continue


def _alt_area_ids(osm_id: str):
    """Ids alternativos de área do pyosmium (2n / 2n+1), nos dois sentidos.

    Extrações anteriores a 2026-10-16 guardavam o id codificado em vez do id
    real do OSM. Geramos as duas hipóteses e só aceitamos a que existir nos
    dados, para valores antigos e novos continuarem a ligar à mesma barragem.
    Nós nunca foram codificados, por isso não têm alternativas.
    """
    if "/" not in osm_id:
        return ()
    kind, _, num = osm_id.partition("/")
    try:
        i = int(num)
    except ValueError:
        return ()
    if kind == "way":
        return (f"way/{i // 2}", f"way/{2 * i}")
    if kind == "relation":
        return (f"relation/{(i - 1) // 2}", f"relation/{2 * i + 1}")
    return ()


class DamResolver:
    """Traduz ids do OSM (barragem ou albufeira) para o `dam_id` da barragem."""

    def __init__(self):
        self.dams: set[str] = set()
        self.res_to_dam: dict[str, str | None] = {}
        self._load()

    def _load(self):
        for f in _iter_features("dams"):
            dam_id = (f.get("properties") or {}).get("dam_id")
            if dam_id:
                self.dams.add(dam_id)
        for f in _iter_features("reservoirs"):
            p = f.get("properties") or {}
            rid = p.get("reservoir_id")
            if rid:
                self.res_to_dam[rid] = p.get("dam_id")

    @property
    def ready(self) -> bool:
        return bool(self.dams)

    def resolve(self, raw: str | None) -> tuple[str | None, str]:
        """Devolve (dam_id, motivo). `dam_id` é None se não for resolúvel."""
        osm_id = normalize_osm_id(raw)
        if not osm_id:
            return None, "sem id"
        for candidate, nota in ((osm_id, ""), *((a, "id antigo→") for a in _alt_area_ids(osm_id))):
            found = self._lookup(candidate)
            if found is not None:
                dam_id, motivo = found
                return dam_id, nota + motivo
        return None, "id não encontrado nos dados"

    def _lookup(self, osm_id: str) -> tuple[str | None, str] | None:
        if osm_id in self.dams:
            return osm_id, "barragem"
        if osm_id in self.res_to_dam:
            dam = self.res_to_dam[osm_id]
            return (dam, "albufeira→barragem") if dam else (None, "albufeira sem barragem associada")
        return None
