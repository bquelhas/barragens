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
        if osm_id in self.dams:
            return osm_id, "barragem"
        if osm_id in self.res_to_dam:
            dam = self.res_to_dam[osm_id]
            return (dam, "albufeira→barragem") if dam else (None, "albufeira sem barragem associada")
        return None, "id não encontrado nos dados"
