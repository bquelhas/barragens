"""
Extrai a geometria dos Pontos de Interesse (POIs curados) e escreve
`data/pois.geojson`.

A lista curada vive em `scripts/config.py` (`POIS`). A geometria é obtida da
**API do OSM** (`/{tipo}/{id}/full`), que é rápida e fiável (não usa Overpass),
montando multipolígonos quando necessário.

Uso:
    python scripts/build_pois.py
    python scripts/build_pois.py --offline   # não vai à rede; mostra o que faria
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import geo  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, mapping  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

API = "https://api.openstreetmap.org/api/0.6/{typ}/{oid}/full"


def fetch_full(typ: str, oid: int) -> ET.Element:
    req = urllib.request.Request(API.format(typ=typ, oid=oid),
                                 headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return ET.fromstring(resp.read())


def geometry_from_xml(typ: str, oid: int, root: ET.Element):
    nodes = {n.get("id"): (float(n.get("lon")), float(n.get("lat")))
             for n in root.findall("node")}
    ways = {w.get("id"): [nd.get("ref") for nd in w.findall("nd")]
            for w in root.findall("way")}

    def way_coords(ref):
        return [nodes[r] for r in ways.get(str(ref), []) if r in nodes]

    if typ == "node":
        return Point(nodes[str(oid)]) if str(oid) in nodes else None

    if typ == "way":
        coords = way_coords(oid)
        if len(coords) >= 4 and coords[0] == coords[-1]:
            p = Polygon(coords)
            return p.buffer(0) if not p.is_valid else p
        return LineString(coords) if len(coords) >= 2 else None

    if typ == "relation":
        rel = root.find("relation")
        if rel is None:
            return None
        outers, inners = [], []
        for m in rel.findall("member"):
            if m.get("type") != "way":
                continue
            coords = way_coords(m.get("ref"))
            if len(coords) < 2:
                continue
            (inners if m.get("role") == "inner" else outers).append(coords)

        polys = []
        for ring in geo._stitch_rings(outers):
            if len(ring) >= 4 and ring[0] == ring[-1]:
                p = Polygon(ring)
                polys.append(p.buffer(0) if not p.is_valid else p)
        if not polys:
            return None
        geom = unary_union(polys)
        for ring in geo._stitch_rings(inners):
            if len(ring) >= 4 and ring[0] == ring[-1]:
                hole = Polygon(ring)
                if not hole.is_valid:
                    hole = hole.buffer(0)
                geom = geom.difference(hole)
        return geom if not geom.is_empty else None

    return None


def build(offline: bool) -> list[dict]:
    features = []
    for poi in config.POIS:
        ref = poi.get("osm")
        if not ref:
            continue
        typ, _, oid = ref.partition("/")
        typ, oid = typ.strip().lower(), int(oid)
        if offline:
            print(f"[pois] (offline) faria {ref} — {poi.get('name')}")
            continue
        try:
            root = fetch_full(typ, oid)
            geom = geometry_from_xml(typ, oid, root)
        except Exception as exc:  # noqa: BLE001
            print(f"[pois] falha ao obter {ref}: {exc}")
            continue
        if geom is None:
            print(f"[pois] geometria vazia para {ref} ({poi.get('name')})")
            continue
        simplified = geo.simplify_metric(geom, config.POI_SIMPLIFY_M)
        features.append({
            "type": "Feature",
            "properties": {
                "name": poi.get("name"),
                "kind": poi.get("kind") or "património",
                "descricao": poi.get("descricao"),
                "dam_id": poi.get("dam_id") or None,
                "notion_url": poi.get("notion_url") or None,
                "osm": ref,
            },
            "geometry": geo.round_coords(mapping(simplified)),
        })
        print(f"[pois] ok: {poi.get('name')} ({ref}, {geom.geom_type})")
    return features


def main():
    ap = argparse.ArgumentParser(description="Gera data/pois.geojson dos POIs curados.")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    features = build(args.offline)
    if args.offline:
        return
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = config.DATA_DIR / "pois.geojson"
    with out.open("w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"[pois] escrito {out} com {len(features)} feições")


if __name__ == "__main__":
    main()
