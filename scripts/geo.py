"""
Ferramentas de geometria e SIG.

Converte os elementos OSM devolvidos pela Overpass em geometrias shapely
(EPSG:4326), incluindo a montagem de multipolígonos de relações, e oferece
utilitários métricos (distância, área, simplificação) usando EPSG:3035.

As geometrias são calculadas em memória; o resultado é convertido de volta
para WGS84 antes de ser escrito para GeoJSON.
"""

from __future__ import annotations

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    shape,
)
from shapely.ops import transform, unary_union
from pyproj import Transformer

import config

# Transformadores reutilizáveis (sempre com ordem x=lon, y=lat).
_TO_METRIC = Transformer.from_crs("EPSG:4326", config.METRIC_CRS, always_xy=True)
_FROM_METRIC = Transformer.from_crs(config.METRIC_CRS, "EPSG:4326", always_xy=True)


# ---------------------------------------------------------------------------
# Conversão Overpass -> shapely
# ---------------------------------------------------------------------------

def _node_index(elements: list[dict]) -> dict[int, tuple[float, float]]:
    """Índice id->(lon,lat) só com os nodes presentes na resposta."""
    idx = {}
    for el in elements:
        if el.get("type") == "node" and "lon" in el and "lat" in el:
            idx[el["id"]] = (el["lon"], el["lat"])
    return idx


def _coords_from_geometry(geom: list[dict]) -> list[tuple[float, float]]:
    """Converte a lista [{lat,lon}, ...] da Overpass em [(lon,lat), ...]."""
    return [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]


def _stitch_rings(ways: list[list[tuple[float, float]]]) -> list[list]:
    """
    Costura segmentos (listas de coordenadas) em anéis fechados.

    Algoritmo simples: junta repetidamente segmentos cujas extremidades
    coincidem. Segmentos que não fecham são devolvidos na mesma lista (o
    chamador decide o que fazer com eles).
    """
    segments = [list(w) for w in ways if len(w) >= 2]
    rings: list[list] = []
    while segments:
        current = segments.pop(0)
        changed = True
        while changed and current[0] != current[-1]:
            changed = False
            for i, seg in enumerate(segments):
                if seg[0] == current[-1]:
                    current.extend(seg[1:])
                elif seg[-1] == current[-1]:
                    current.extend(list(reversed(seg))[1:])
                elif seg[-1] == current[0]:
                    current = seg[:-1] + current
                elif seg[0] == current[0]:
                    current = list(reversed(seg))[:-1] + current
                else:
                    continue
                segments.pop(i)
                changed = True
                break
        rings.append(current)
    return rings


def _relation_to_polygon(members: list[dict]) -> Polygon | MultiPolygon | None:
    """Monta um (Multi)Polygon a partir dos membros outer/inner de uma relação."""
    outer_ways = []
    inner_ways = []
    for m in members:
        coords = _coords_from_geometry(m.get("geometry") or [])
        if len(coords) < 2:
            continue
        role = m.get("role", "")
        if role == "inner":
            inner_ways.append(coords)
        else:  # "outer" e o que não tiver role
            outer_ways.append(coords)
    if not outer_ways:
        return None

    outers = []
    for ring in _stitch_rings(outer_ways):
        if len(ring) >= 4 and ring[0] == ring[-1]:
            poly = Polygon(ring)
            if poly.is_valid and not poly.is_empty:
                outers.append(poly)
    if not outers:
        return None

    inners = []
    for ring in _stitch_rings(inner_ways):
        if len(ring) >= 4 and ring[0] == ring[-1]:
            poly = Polygon(ring)
            if not poly.is_empty:
                inners.append(poly)

    if len(outers) == 1:
        geom = outers[0]
        for hole in inners:
            geom = geom.difference(hole)
        return geom if not geom.is_empty else None

    # Vários anéis exteriores: subtrai os interiores ao conjunto.
    outer_union = unary_union(outers)
    if inners:
        geom = outer_union.difference(unary_union(inners))
    else:
        geom = outer_union
    if geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type == "MultiPolygon":
        return geom
    return None


def elements_to_features(elements: list[dict]) -> list[dict]:
    """
    Converte elementos OSM em features com geometria shapely (EPSG:4326).

    Devolve uma lista de dicts:
        {"osm_type", "osm_id", "tags", "geom", "parts"}
    onde `parts` é a lista de geometrias individuais (útil para barragens
    com linha + área, por exemplo).
    """
    nodes = _node_index(elements)
    features = []

    for el in elements:
        etype = el.get("type")
        eid = el.get("id")
        tags = el.get("tags") or {}
        geom = None
        parts = []

        if etype == "node":
            if "lon" in el and "lat" in el:
                geom = Point(el["lon"], el["lat"])
                parts = [geom]

        elif etype == "way":
            coords = _coords_from_geometry(el.get("geometry") or [])
            if not coords and "nodes" in el:
                coords = [nodes[n] for n in el["nodes"] if n in nodes]
            if len(coords) >= 4 and coords[0] == coords[-1]:
                geom = Polygon(coords)
                if not geom.is_valid:
                    geom = geom.buffer(0)
            elif len(coords) >= 2:
                geom = LineString(coords)
            if geom is not None and not geom.is_empty:
                parts = [geom]

        elif etype == "relation":
            geom = _relation_to_polygon(el.get("members") or [])
            if geom is not None:
                parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]

        if geom is None or geom.is_empty:
            continue

        features.append(
            {
                "osm_type": etype,
                "osm_id": eid,
                "tags": tags,
                "geom": geom,
                "parts": parts,
            }
        )

    return features


# ---------------------------------------------------------------------------
# Utilitários métricos
# ---------------------------------------------------------------------------

def to_metric(geom):
    """Reprojetar uma geometria WGS84 para EPSG:3035."""
    return transform(_TO_METRIC.transform, geom)


def from_metric(geom):
    """Reprojetar uma geometria métrica de volta para WGS84."""
    return transform(_FROM_METRIC.transform, geom)


def area_ha(geom) -> float:
    """Área em hectares de uma geometria WGS84."""
    return to_metric(geom).area / 10_000.0


def simplify_metric(geom, tolerance_m: float):
    """Simplifica (Douglas-Peucker) mantendo a geometria em WGS84."""
    if not tolerance_m or tolerance_m <= 0:
        return geom
    metric = to_metric(geom)
    simplified = metric.simplify(tolerance_m, preserve_topology=True)
    if simplified.is_empty:
        return geom
    return from_metric(simplified)


def representative_point(geom) -> Point:
    """Ponto representativo (garantidamente dentro) de uma geometria."""
    return geom.representative_point()


def round_coords(value, decimals: int = None):
    """Arredonda recursivamente coordenadas de um objeto GeoJSON-friendly."""
    d = config.COORD_DECIMALS if decimals is None else decimals
    if isinstance(value, float):
        return round(value, d)
    if isinstance(value, (list, tuple)):
        return [round_coords(v, d) for v in value]
    if isinstance(value, dict):
        return {k: round_coords(v, d) for k, v in value.items()}
    return value


def strip_z(geom):
    """Remove a 3.ª dimensão, se existir, de uma geometria."""
    if geom.has_z:
        return transform(lambda x, y, z=None: (x, y), geom)
    return geom
