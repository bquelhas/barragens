"""
Extração a partir dos extracts do Geofabrik (.osm.pbf).

Alternativa fiável à Overpass API (que se satura com frequência). Descarrega
o extract do país, filtra em memória com a biblioteca `pyosmium` e gera os
mesmos ficheiros que `build_data.py` (reutiliza a associação espacial, a
classificação de uso e a escrita em `data/`).

Uso:
    python scripts/build_data_pbf.py --countries PT
    python scripts/build_data_pbf.py --countries PT --skip-infra
    python scripts/build_data_pbf.py --countries PT,ES

Os ficheiros .pbf ficam em cache (por omissão /tmp/osm-cache; muda com a
variável de ambiente OSM_CACHE).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import geo  # noqa: E402
import build_data  # noqa: E402
import osmium  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

log = build_data.log

# Extract oficial de cada país (PT inclui Açores e Madeira; ES inclui
# Baleares e Canárias).
PBF_URLS = {
    "PT": "https://download.geofabrik.de/europe/portugal-latest.osm.pbf",
    "ES": "https://download.geofabrik.de/europe/spain-latest.osm.pbf",
}
CACHE_DIR = Path(os.environ.get("OSM_CACHE", "/tmp/osm-cache"))

BASE = ["dams", "weirs", "reservoirs"]
INFRA = ["plants", "substations", "power_lines", "conduits"]


# ---------------------------------------------------------------------------
# Correspondência de tags (equivalente às queries Overpass de config.py)
# ---------------------------------------------------------------------------

def matches(layer: str, t: dict) -> bool:
    if layer == "dams":
        return t.get("waterway") == "dam"
    if layer == "weirs":
        return t.get("waterway") == "weir"
    if layer == "reservoirs":
        return (t.get("natural") == "water" and t.get("water") == "reservoir") \
            or t.get("landuse") == "reservoir"
    if layer == "plants":
        return (t.get("power") == "plant" and t.get("plant:source") in ("hydro", "water")) \
            or (t.get("power") == "generator" and t.get("generator:source") in ("hydro", "water"))
    if layer == "substations":
        return t.get("power") == "substation"
    if layer == "power_lines":
        return t.get("power") == "line"
    if layer == "conduits":
        return (t.get("man_made") == "pipeline" and t.get("substance") == "water") \
            or t.get("waterway") in ("pressurised", "canal", "spillway") \
            or t.get("lock") == "yes"
    return False


def _coords(ring) -> list:
    return [(nd.location.lon, nd.location.lat) for nd in ring]


def _rings_to_polygon(area):
    """Constrói um (Multi)Polygon a partir dos anéis de uma área pyosmium."""
    outer_polys = []
    for oring in area.outer_rings():
        coords = _coords(oring)
        if len(coords) < 4:
            continue
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        # Subtrai os anéis interiores que pertencem a este anel exterior.
        for iring in area.inner_rings(oring):
            icoords = _coords(iring)
            if len(icoords) >= 4:
                hole = Polygon(icoords)
                if not hole.is_valid:
                    hole = hole.buffer(0)
                poly = poly.difference(hole)
        if not poly.is_empty:
            outer_polys.append(poly)

    if not outer_polys:
        return None
    geom = unary_union(outer_polys)
    if geom.is_empty:
        return None
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    return None


# ---------------------------------------------------------------------------
# Handler pyosmium
# ---------------------------------------------------------------------------

class Extractor(osmium.SimpleHandler):
    def __init__(self, layers: list[str], country: str):
        super().__init__()
        self.layers = set(layers)
        self.country = country
        self.out: dict[str, list] = {k: [] for k in layers}

    def _add(self, layer, osm_type, osm_id, tags, geom, parts=None):
        if geom is None or geom.is_empty:
            return
        parts = parts or ([geom] if geom.geom_type != "MultiPolygon" else list(geom.geoms))
        self.out[layer].append({
            "osm_type": osm_type, "osm_id": osm_id, "tags": dict(tags),
            "geom": geom, "parts": parts, "country": self.country,
        })

    def node(self, n):
        t = n.tags
        for layer in ("dams", "weirs", "plants", "substations", "conduits"):
            if layer in self.layers and matches(layer, t):
                self._add(layer, "node", n.id, t,
                          Point(n.location.lon, n.location.lat))

    def way(self, w):
        t = w.tags
        closed = w.is_closed()
        for layer in ("dams", "weirs", "power_lines", "conduits"):
            if layer in self.layers and matches(layer, t):
                coords = [(nd.lon, nd.lat) for nd in w.nodes]
                if len(coords) < 2:
                    continue
                geom = Polygon(coords) if (closed and len(coords) >= 4) else LineString(coords)
                if geom.geom_type == "Polygon" and not geom.is_valid:
                    geom = geom.buffer(0)
                self._add(layer, "way", w.id, t, geom)

    def area(self, a):
        # `area()` é chamado tanto para relações multipolígono como para
        # malhas fechadas. Interessa-nos sobretudo as albufeiras.
        if "reservoirs" in self.layers and matches("reservoirs", a.tags):
            geom = _rings_to_polygon(a)
            from_way = a.from_way() if hasattr(a, "from_way") else False
            osm_type = "way" if from_way else "relation"
            self._add("reservoirs", osm_type, a.id, a.tags, geom)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def ensure_pbf(country: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{country.lower()}-latest.osm.pbf"
    if path.exists() and path.stat().st_size > 1_000_000:
        log(f"[pbf] {country}: cache {path} ({path.stat().st_size/1e6:.0f} MB)")
        return path

    url = PBF_URLS[country]
    log(f"[pbf] {country}: a descarregar {url} ...")
    tmp = path.with_suffix(".pbf.part")
    from urllib.request import urlopen
    with urlopen(url, timeout=120) as resp, tmp.open("wb") as fh:
        total = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            total += len(chunk)
            if total % (50 << 20) < (1 << 20):
                log(f"[pbf] {country}: {total/1e6:.0f} MB ...")
    tmp.rename(path)
    log(f"[pbf] {country}: descarregado {path.stat().st_size/1e6:.0f} MB")
    return path


# ---------------------------------------------------------------------------
# Extracção e finalização
# ---------------------------------------------------------------------------

def extract_country(country: str, layers: list[str]) -> dict[str, list]:
    pbf = ensure_pbf(country)
    log(f"[pbf] {country}: a processar {pbf.name} (camadas: {', '.join(layers)})...")
    t0 = time.time()
    handler = Extractor(layers, country)
    handler.apply_file(str(pbf), locations=True)
    log(f"[pbf] {country}: processado em {time.time()-t0:.0f}s")
    for layer, feats in handler.out.items():
        log(f"[pbf] {country}/{layer}: {len(feats)} elementos")
    return handler.out


def within_dams(feats, dam_points, max_m):
    if not dam_points or not feats:
        return []
    tree = STRtree(dam_points)
    kept = []
    for f in feats:
        gm = geo.to_metric(f["geom"])
        if any(dam_points[i].distance(gm) <= max_m for i in tree.query(gm.buffer(max_m))):
            kept.append(f)
    return kept


def run(countries, skip_infra, force):
    build_data.CURRENT_COUNTRIES = countries
    prev = build_data.read_previous_manifest()

    sample_countries = set(prev.get("sample_countries") or []) if prev else set()
    if prev and prev.get("sample") and not sample_countries:
        sample_countries = {"PT", "ES"}
    sample_countries -= set(countries)  # extração PBF = dados reais

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample": bool(sample_countries),
        "sample_countries": sorted(sample_countries),
        "source": "OpenStreetMap (extract Geofabrik .osm.pbf)",
        "attribution": "© OpenStreetMap contributors",
        "license": "ODbL",
        "countries": countries,
        "counts": {},
        "layers": {},
    }
    log(f"[build] países={countries} fonte=pbf skip_infra={skip_infra} "
        f"amostra={sorted(sample_countries) or 'nenhuma'}")

    layers = list(BASE) + ([] if skip_infra else list(INFRA))

    all_dams, all_reservoirs, all_weirs = [], [], []
    all_plants, all_substations, all_lines, all_conduits = [], [], [], []

    for cc in countries:
        out = extract_country(cc, layers)
        all_dams.extend(build_data.build_dams(out.get("dams", []), cc))
        all_reservoirs.extend(out.get("reservoirs", []))
        all_weirs.extend(out.get("weirs", []))
        all_plants.extend(out.get("plants", []))
        all_substations.extend(out.get("substations", []))
        all_lines.extend(out.get("power_lines", []))
        all_conduits.extend(out.get("conduits", []))

    if not all_dams:
        raise SystemExit("[validação] nenhuma barragem extraída. A abortar.")

    log("[build] a associar albufeiras e centrais às barragens...")
    build_data.associate(all_dams, all_reservoirs, all_plants)

    if not skip_infra:
        dam_points = [geo.to_metric(d["point"]) for d in all_dams]
        all_substations = within_dams(all_substations, dam_points, config.SUBSTATION_KEEP_M)
        all_lines = within_dams(all_lines, dam_points, config.LINE_KEEP_M)
        all_conduits = within_dams(all_conduits, dam_points, config.CONDUIT_KEEP_M)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    build_data.write_dams(all_dams)
    build_data.write_reservoirs(all_reservoirs)
    build_data.write_simple(all_weirs, "weirs", "name")
    build_data.write_simple(all_plants, "plants", "name", extra=build_data.attrs_power)
    build_data.write_simple(all_substations, "substations", "name")
    build_data.write_simple(all_lines, "power_lines", "name")
    build_data.write_simple(all_conduits, "conduits", "name")

    build_data.rebuild_manifest(manifest)

    if not force and prev and not prev.get("sample"):
        prev_dams = prev.get("counts", {}).get("dams", 0)
        new_dams = manifest["counts"].get("dams", 0)
        if prev_dams and new_dams < prev_dams * config.MIN_DAMS_RATIO:
            raise SystemExit(
                f"[validação] total de barragens {new_dams} < 80% de {prev_dams}. "
                f"A abortar sem commit. Usa --force para forçar."
            )
    log(f"[validação] barragens: {manifest['counts'].get('dams', 0)} "
        f"(anterior: {prev.get('counts', {}).get('dams', 'n/a') if prev else 'n/a'})")

    notion_file = config.DATA_DIR / "notion.json"
    if notion_file.exists():
        try:
            with notion_file.open(encoding="utf-8") as fh:
                manifest["notion_count"] = len(json.load(fh))
        except Exception:  # noqa: BLE001
            pass

    with (config.DATA_DIR / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    log(f"[build] concluído: {manifest['total_features']} features no total")


def main():
    p = argparse.ArgumentParser(description="Gera dados a partir de extracts PBF.")
    p.add_argument("--countries", default="PT,ES")
    p.add_argument("--skip-infra", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    invalid = [c for c in countries if c not in PBF_URLS]
    if invalid:
        raise SystemExit(f"Países inválidos: {invalid}. Válidos: {list(PBF_URLS)}")
    run(countries, args.skip_infra, args.force)


if __name__ == "__main__":
    main()
