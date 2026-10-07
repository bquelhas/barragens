"""
Pipeline de dados das barragens (PT + ES).

Uso:
    python scripts/build_data.py                 # extrai da Overpass (real)
    python scripts/build_data.py --offline       # usa scripts/fixtures/*.json
    python scripts/build_data.py --countries PT  # só Portugal
    python scripts/build_data.py --force         # ignora a validação mínima

Fluxo:
    1. Extrai barragens, açudes e albufeiras de todo o país.
    2. Extrai infraestruturas (centrais, subestações, linhas, condutas)
       apenas num raio à volta das barragens.
    3. Converte para geometrias, associa barragem<->albufeira<->central e
       classifica o uso (hidroelétrica / regadio / abastecimento / misto).
    4. Simplifica, arredonda e escreve `data/*.geojson` + `data/manifest.json`.

O ficheiro `data/manifest.json` é também a memória da última extração boa:
o build recusa substituir dados se a nova extração tiver demasiado poucas
barragens (ver `config.MIN_DAMS_RATIO`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# Permite correr como `python scripts/build_data.py`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import geo  # noqa: E402
import overpass  # noqa: E402
from shapely.geometry import mapping, shape  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def log(msg: str):
    print(msg, flush=True)


def normalize_name(name: str | None) -> str:
    """Minúsculas, sem acentos, sem prefixos comuns (para agrupar/pesquisar)."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    for prefix in ("barragem de ", "barragem da ", "barragem do ",
                   "barragem ", "presa de ", "presa da ", "presa del ",
                   "presa ", "embalse de ", "embalse del ", "embalse "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.strip()


def first_tag(tags: dict, *keys: str):
    """Primeiro valor não vazio entre várias chaves de tag."""
    for k in keys:
        v = tags.get(k)
        if v not in (None, ""):
            return v
    return None


def to_float(value):
    """Converte tags numéricas (aceita '123', '123 m', '1,5')."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    num = ""
    for ch in text:
        if ch.isdigit() or ch in ".-":
            num += ch
        else:
            break
    try:
        return float(num)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Construção de queries Overpass
# ---------------------------------------------------------------------------

def ql_area(area_expr: str, filters: list[str]) -> str:
    """Query simples: todos os elementos que casam os filtros dentro da área."""
    body = "".join(f"{f}(area.a);" for f in filters)
    return f"[out:json][timeout:{config.OVERPASS_TIMEOUT}];{area_expr}->.a;({body});out geom;"


def ql_around(area_expr: str, dam_filters: list[str],
              collect: list[dict], plant_filters: list[str] | None = None) -> str:
    """
    Query de infraestrutura em torno das barragens.

    `collect` é uma lista de {"filter": "...", "ref": "dams"|"plants",
    "radius": int}. Usa `around` com o conjunto de barragens (e, se pedido,
    de centrais) para trazer só o que está perto.
    """
    q = f"[out:json][timeout:{config.OVERPASS_TIMEOUT}];{area_expr}->.a;"
    q += "(" + "".join(f"{f}(area.a);" for f in dam_filters) + ")->.dams;"
    if plant_filters:
        q += "(" + "".join(f"{f}(around.dams:3000);" for f in plant_filters) + ")->.plants;"
    body = ""
    for c in collect:
        radius = c.get("radius", 3000)
        body += f'{c["filter"]}(around.{c["ref"]}:{radius});'
    q += "(" + body + ");out geom;"
    return q


# ---------------------------------------------------------------------------
# Extração
# ---------------------------------------------------------------------------

def _fixture_path(country: str, layer: str) -> Path:
    return config.FIXTURES_DIR / f"{country}_{layer}.json"


def fetch_layer(country: str, layer: str, area_expr: str, area_label: str,
                filters: list[str], offline: bool, collect: list[dict] | None = None,
                plant_filters: list[str] | None = None) -> list[dict]:
    """
    Obtém os elementos de uma camada num país.

    Em `offline`, lê um fixture local. Caso contrário, tenta a área do país
    e, se falhar, divide por subdivisões administrativas.
    """
    if offline:
        path = _fixture_path(country, layer)
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        log(f"[dados] fixture {path.name}: {len(data.get('elements', []))} elementos")
        return data.get("elements", [])

    if collect is None:
        query = ql_area(area_expr, filters)
    else:
        query = ql_around(area_expr, filters, collect, plant_filters)

    # Infraestruturas: as queries `around` sobre TODAS as barragens do país
    # são demasiado pesadas para a Overpass pública (dão 502/504/timeout).
    # Por isso vamos diretamente às subdivisões administrativas, onde o
    # conjunto de barragens por distrito/comunidade é pequeno.
    if collect is not None and not offline:
        elements: list[dict] = []
        for sub in overpass.discover_subareas(country, log):
            try:
                sub_query = ql_around(sub["area"], filters, collect, plant_filters)
                data = overpass.overpass_query(
                    sub_query, log, context=f"{country}/{layer} ({sub['name']})")
                elements.extend(data.get("elements", []))
                overpass.pause()
            except overpass.OverpassError as exc:
                log(f"[dados] falhou {country}/{layer} em {sub['name']}: {exc}")
        log(f"[dados] {country}/{layer} (subáreas): {len(elements)} elementos")
        return elements

    try:
        data = overpass.overpass_query(query, log, context=f"{country}/{layer} ({area_label})")
        elements = data.get("elements", [])
        log(f"[dados] {country}/{layer} via {area_label}: {len(elements)} elementos")
        return elements
    except overpass.OverpassError as exc:
        log(f"[dados] falhou {country}/{layer} em {area_label}: {exc}")

    # Fallback: dividir por subdivisões administrativas.
    elements: list[dict] = []
    subareas = overpass.discover_subareas(country, log)
    for sub in subareas:
        try:
            if collect is None:
                sub_query = ql_area(sub["area"], filters)
            else:
                sub_query = ql_around(sub["area"], filters, collect, plant_filters)
            data = overpass.overpass_query(
                sub_query, log, context=f"{country}/{layer} ({sub['name']})")
            elements.extend(data.get("elements", []))
            overpass.pause()
        except overpass.OverpassError as exc:
            log(f"[dados] falhou {country}/{layer} em {sub['name']}: {exc}")
    return elements


def dedupe_elements(elements: list[dict]) -> list[dict]:
    """Remove elementos repetidos (type+id), juntando tags em falta."""
    by_key: dict[tuple, dict] = {}
    for el in elements:
        key = (el.get("type"), el.get("id"))
        if key not in by_key:
            by_key[key] = el
        else:
            # Completa tags/geometria em falta.
            existing = by_key[key]
            if not existing.get("geometry") and el.get("geometry"):
                existing["geometry"] = el["geometry"]
            existing_tags = existing.setdefault("tags", {})
            for k, v in (el.get("tags") or {}).items():
                existing_tags.setdefault(k, v)
    return list(by_key.values())


# ---------------------------------------------------------------------------
# Barragens: agrupamento e representação
# ---------------------------------------------------------------------------

def build_dams(features: list[dict], country: str) -> list[dict]:
    """
    Agrupa features que descrevem a mesma barragem (ex.: linha + área) e
    devolve uma entrada por barragem com ponto representativo.
    """
    if not features:
        return []

    metric_geoms = [geo.to_metric(f["geom"]) for f in features]
    tree = STRtree(metric_geoms)
    parent = list(range(len(features)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    # Junta features até 300 m cujo nome normalizado coincide (ou uma sem nome).
    for i, geom in enumerate(metric_geoms):
        name_i = normalize_name(features[i]["tags"].get("name"))
        for j in tree.query(geom.buffer(300)):
            if j <= i:
                continue
            name_j = normalize_name(features[j]["tags"].get("name"))
            if name_i and name_j and name_i != name_j:
                continue
            union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(features)):
        groups.setdefault(find(i), []).append(i)

    dams = []
    for members in groups.values():
        # Primário: com nome e com mais tags.
        members.sort(
            key=lambda idx: (
                bool(features[idx]["tags"].get("name")),
                len(features[idx]["tags"]),
            ),
            reverse=True,
        )
        primary = features[members[0]]
        tags = dict(primary["tags"])
        for idx in members[1:]:
            for k, v in features[idx]["tags"].items():
                tags.setdefault(k, v)

        priority = {"relation": 3, "way": 2, "node": 1}
        best_geom = max((features[idx]["geom"] for idx in members),
                        key=lambda g: (priority[primary["osm_type"]], g.area))
        point = geo.representative_point(best_geom)

        dams.append({
            "osm_type": primary["osm_type"],
            "osm_id": primary["osm_id"],
            "dam_id": f'{primary["osm_type"]}/{primary["osm_id"]}',
            "tags": tags,
            "geom": best_geom,
            "point": point,
            "country": country,
            "members": [f'{features[idx]["osm_type"]}/{features[idx]["osm_id"]}'
                        for idx in members],
        })
    return dams


# ---------------------------------------------------------------------------
# Associação espacial e classificação
# ---------------------------------------------------------------------------

def _tag_category(tags: dict) -> set[str]:
    """Categorias de uso inferidas a partir das tags de uma albufeira."""
    cats = set()
    usage = (tags.get("usage") or "").lower()
    rtype = (tags.get("reservoir_type") or "").lower()
    if usage in ("hydro", "power", "hydropower") or rtype in ("hydro", "power"):
        cats.add("hidroelétrica")
    if usage == "irrigation" or rtype == "irrigation":
        cats.add("regadio")
    if usage in ("water_supply", "drinking_water") or rtype in ("water_supply", "drinking_water"):
        cats.add("abastecimento")
    return cats


def associate(dams: list[dict], reservoirs: list[dict], plants: list[dict]):
    """Calcula reservoir_id, plant_ids e a classificação `uso` de cada barragem."""
    # Índices métricos.
    res_metric = [geo.to_metric(r["geom"]) for r in reservoirs]
    res_tree = STRtree(res_metric) if res_metric else None

    plant_metric = [geo.to_metric(p["geom"]) for p in plants]
    plant_tree = STRtree(plant_metric) if plant_metric else None

    for dam in dams:
        point_m = geo.to_metric(dam["point"])
        cats: set[str] = set()
        fontes: list[str] = []

        # ---- albufeira associada ------------------------------------
        reservoir = None
        if res_tree is not None:
            best_dist = None
            for idx in res_tree.query(point_m.buffer(config.RESERVOIR_FALLBACK_M + 5)):
                geom = res_metric[idx]
                dist = geom.distance(point_m)
                touches = geom.intersects(point_m.buffer(30)) or geom.distance(point_m) <= config.RESERVOIR_NEAR_M
                if touches and (best_dist is None or dist < best_dist):
                    best_dist, reservoir = dist, reservoirs[idx]
            if reservoir is None:
                # mais próxima a <= fallback
                for idx in res_tree.query(point_m.buffer(config.RESERVOIR_FALLBACK_M + 5)):
                    dist = res_metric[idx].distance(point_m)
                    if dist <= config.RESERVOIR_FALLBACK_M and (best_dist is None or dist < best_dist):
                        best_dist, reservoir = dist, reservoirs[idx]

        dam["reservoir_id"] = None
        dam["reservoir_name"] = None
        dam["reservoir_area_ha"] = None
        if reservoir is not None:
            dam["reservoir_id"] = f'{reservoir["osm_type"]}/{reservoir["osm_id"]}'
            dam["reservoir_name"] = reservoir["tags"].get("name")
            dam["reservoir_area_ha"] = round(geo.area_ha(reservoir["geom"]), 1)
            rcats = _tag_category(reservoir["tags"])
            if rcats:
                cats |= rcats
                usage = reservoir["tags"].get("usage") or reservoir["tags"].get("reservoir_type")
                fontes.append(f'albufeira (usage={usage})')

        # ---- centrais hidroelétricas associadas --------------------
        plant_ids, plant_names, power = [], [], 0.0
        if plant_tree is not None:
            for idx in plant_tree.query(point_m.buffer(config.PLANT_NEAR_M)):
                dist = plant_metric[idx].distance(point_m)
                if dist <= config.PLANT_NEAR_M:
                    p = plants[idx]
                    plant_ids.append(f'{p["osm_type"]}/{p["osm_id"]}')
                    if p["tags"].get("name"):
                        plant_names.append(p["tags"]["name"])
                    val = to_float(first_tag(p["tags"], "plant:output:electricity",
                                             "generator:output:electricity"))
                    if val:
                        power = max(power, val)
        dam["plant_ids"] = plant_ids
        dam["plant_names"] = plant_names
        dam["plant_power_mw"] = round(power, 1) if power else None
        if plant_ids:
            cats.add("hidroelétrica")
            fontes.append(f'central associada ({len(plant_ids)})')

        # ---- classificação final -----------------------------------
        if len(cats) > 1:
            dam["uso"] = "misto"
        elif len(cats) == 1:
            dam["uso"] = next(iter(cats))
        else:
            dam["uso"] = "desconhecido"
        dam["uso_fonte"] = "; ".join(fontes) if fontes else "sem tags de uso"

    return dams


# ---------------------------------------------------------------------------
# Albufeiras: ligação à barragem e filtragem
# ---------------------------------------------------------------------------

def filter_dams(dams: list[dict]) -> list[dict]:
    """
    Descarta barragens **sem nome**, **sem albufeira** e **sem central**
    associada quando a estrutura é minúscula (< `MIN_DAM_SIZE_M`). São
    tipicamente levadas, pequenos açudes ou ruído do OSM.
    """
    kept = []
    dropped = 0
    for d in dams:
        tags = d["tags"]
        named = bool(tags.get("name") or tags.get("name:pt") or tags.get("name:es"))
        if named or d.get("reservoir_id") or d.get("plant_ids"):
            kept.append(d)
            continue
        m = geo.to_metric(d["geom"])
        size = m.length if m.geom_type in ("LineString", "MultiLineString") else m.area
        if size < config.MIN_DAM_SIZE_M:
            dropped += 1
        else:
            kept.append(d)
    if dropped:
        log(f"[barragens] {dropped} estruturas minúsculas sem nome descartadas")
    return kept


def link_and_filter_reservoirs(reservoirs: list[dict], dams: list[dict]) -> list[dict]:
    """
    Liga cada albufeira à sua barragem (propriedade `dam_id`) e filtra as
    irrelevantes: ficam só as **ligadas a uma barragem** ou com
    **área >= `MIN_RESERVOIR_AREA_HA`** (descarta charcas/tanques).

    Também guarda `area_ha` na própria albufeira (usada pela interface).
    """
    # Mapa inverso albufeira -> barragem (a partir de dam["reservoir_id"]).
    by_reservoir: dict[str, str] = {}
    for d in dams:
        rid = d.get("reservoir_id")
        if rid and rid not in by_reservoir:
            by_reservoir[rid] = d["dam_id"]

    kept = []
    dropped = 0
    for r in reservoirs:
        rid = f'{r["osm_type"]}/{r["osm_id"]}'
        area = geo.area_ha(r["geom"])
        r["area_ha"] = area
        r["dam_id"] = by_reservoir.get(rid)
        if r["dam_id"] or area >= config.MIN_RESERVOIR_AREA_HA:
            kept.append(r)
        else:
            dropped += 1
    log(f"[albufeiras] {len(kept)} mantidas, {dropped} descartadas "
        f"(< {config.MIN_RESERVOIR_AREA_HA} ha e sem barragem)")
    return kept


# ---------------------------------------------------------------------------
# Conversão de features para GeoJSON
# ---------------------------------------------------------------------------

def feature_to_geojson(feature: dict, properties: dict, geometry: dict) -> dict:
    # `geometry` já é um dicionário GeoJSON (saída de `simplify_and_round`).
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties,
    }


def add_feature(features: list, feature: dict, properties: dict, geom_dict):
    """Acrescenta a feature, ignorando geometrias degeneradas (`None`)."""
    if geom_dict is None:
        return
    features.append(feature_to_geojson(feature, properties, geom_dict))


def simplify_and_round(geometry, layer: str):
    """
    Simplifica, arredonda e devolve um dicionário GeoJSON.

    Devolve `None` se a geometria ficar degenerada (área/comprimento ~0)
    depois do arredondamento — essas features são descartadas.
    """
    tol = config.SIMPLIFY_TOLERANCE_M.get(layer, 0.0)
    geom = geo.strip_z(geometry)
    geom = geo.simplify_metric(geom, tol)
    mapped = geo.round_coords(mapping(geom))

    rounded = shape(mapped)
    if rounded.is_empty:
        return None
    metric = geo.to_metric(rounded)
    if metric.geom_type in ("Polygon", "MultiPolygon") and metric.area < config.MIN_AREA_M2:
        return None
    if metric.geom_type in ("LineString", "MultiLineString") and metric.length < config.MIN_LEN_M:
        return None
    return mapped


# ---------------------------------------------------------------------------
# Escrita dos dados
# ---------------------------------------------------------------------------

# Todas as camadas que o manifest pode anunciar.
LAYER_KEYS = ["dams", "dam_geoms", "reservoirs", "weirs", "plants",
              "substations", "power_lines", "conduits", "bairros"]

# Países processados na execução atual (definido em `run`).
CURRENT_COUNTRIES: list[str] = []


def write_layer(name: str, features: list[dict]):
    """
    Escreve uma camada em `data/`, dividida por país.

    Cada país fica no seu ficheiro (`<camada>_<cc>.geojson`), para que uma
    extração de um só país não toque nos dados do outro. Os ficheiros dos
    países processados nesta execução são reescritos (ou removidos, se não
    houver dados); os restantes ficam intactos.
    """
    legacy = config.DATA_DIR / f"{name}.geojson"
    if legacy.exists():
        legacy.unlink()
    for cc in CURRENT_COUNTRIES:
        old = config.DATA_DIR / f"{name}_{cc.lower()}.geojson"
        if old.exists():
            old.unlink()

    by_country: dict[str, list] = {}
    for f in features:
        cc = (f["properties"].get("country") or "xx").lower()
        by_country.setdefault(cc, []).append(f)

    if not by_country:
        log(f"[saída] {name}: sem dados nos países {CURRENT_COUNTRIES}")
        return

    written = []
    for cc, feats in sorted(by_country.items()):
        fname = f"{name}_{cc}.geojson"
        write_geojson(config.DATA_DIR / fname, feats)
        written.append(f"{fname}({len(feats)})")
    log(f"[saída] {name}: {', '.join(written)}")


def _country_of(layer: str, filename: str) -> str | None:
    """Extrai o país do nome do ficheiro (ex.: dams_pt.geojson -> PT)."""
    m = re.match(rf"^{re.escape(layer)}_([a-zA-Z]+)\.geojson$", filename)
    return m.group(1).upper() if m else None


def rebuild_manifest(manifest: dict):
    """
    Reconstrói `layers`/`counts`/`countries`/`counts_by_country` a partir dos
    ficheiros que existem em `data/`.

    Assim, uma extração de um só país preserva os ficheiros do outro país que
    já estejam no repositório (comportamento de "merge").
    """
    layers: dict[str, list] = {}
    counts: dict[str, int] = {}
    by_country: dict[str, dict[str, int]] = {}
    countries: set[str] = set()

    for name in LAYER_KEYS:
        files = sorted(p.name for p in config.DATA_DIR.glob(f"{name}_*.geojson"))
        single = config.DATA_DIR / f"{name}.geojson"
        if single.exists():
            files = [single.name] + files
        if not files:
            continue
        layers[name] = files
        total = 0
        for fn in files:
            try:
                with (config.DATA_DIR / fn).open(encoding="utf-8") as fh:
                    n = len(json.load(fh).get("features", []))
            except Exception as exc:  # noqa: BLE001
                log(f"[aviso] não consegui ler {fn}: {exc}")
                n = 0
            total += n
            cc = _country_of(name, fn)
            if cc:
                countries.add(cc)
                by_country.setdefault(cc, {})[name] = by_country.setdefault(cc, {}).get(name, 0) + n
        counts[name] = total

    manifest["layers"] = layers
    manifest["counts"] = counts
    manifest["counts_by_country"] = by_country
    manifest["countries"] = sorted(countries)
    manifest["total_features"] = sum(counts.values())


def write_geojson(path: Path, features: list[dict]):
    fc = {"type": "FeatureCollection", "features": features}
    with path.open("w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def run(countries: list[str], offline: bool, force: bool, skip_infra: bool = False):
    global CURRENT_COUNTRIES
    CURRENT_COUNTRIES = countries
    prev = read_previous_manifest()

    # Países que ainda têm dados de amostra (mantido entre execuções).
    sample_countries = set(prev.get("sample_countries") or []) if prev else set()
    if prev and prev.get("sample") and not sample_countries:
        sample_countries = {"PT", "ES"}
    if offline:
        sample_countries |= set(countries)
    else:
        sample_countries -= set(countries)

    manifest: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample": bool(sample_countries),
        "sample_countries": sorted(sample_countries),
        "source": "OpenStreetMap (via Overpass API)" if not offline else
                  "Amostra local (scripts/fixtures)",
        "attribution": "© OpenStreetMap contributors",
        "license": "ODbL",
        "countries": countries,
        "counts": {},
        "layers": {},
    }
    log(f"[build] países={countries} offline={offline} "
        f"amostra={sorted(sample_countries) or 'nenhuma'}")

    all_dams: list[dict] = []          # barragens já agrupadas
    all_reservoirs: list[dict] = []    # (osm_type, osm_id, tags, geom, country)
    all_weirs: list[dict] = []
    all_plants: list[dict] = []
    all_substations: list[dict] = []
    all_lines: list[dict] = []
    all_conduits: list[dict] = []

    # -- Base (por país) --------------------------------------------------
    for cc in countries:
        area_expr = config.COUNTRIES[cc]

        def grab(layer):
            els = fetch_layer(cc, layer, area_expr, cc,
                              config.BASE_LAYERS[layer], offline)
            feats = geo.elements_to_features(dedupe_elements(els))
            for f in feats:
                f["country"] = cc
            return feats

        all_dams.extend(build_dams(grab("dams"), cc))
        all_reservoirs.extend(grab("reservoirs"))
        all_weirs.extend(grab("weirs"))

        if not offline:
            overpass.pause()

    log(f"[build] barragens agrupadas: {len(all_dams)}")

    # Salvaguarda: uma extração que não trouxe nenhuma barragem é uma falha
    # (Overpass indisponível), não deve substituir dados por vazio.
    if not offline and not all_dams:
        raise SystemExit(
            "[validação] nenhuma barragem extraída — provável falha da Overpass. "
            "A abortar sem commit."
        )

    # -- Infraestrutura (à volta das barragens, por país) -----------------
    collect_map = {
        "plants": [{"filter": f, "ref": "dams",
                    "radius": config.INFRA_RADIUS_M["plants"]}
                   for f in config.INFRA_LAYERS["plants"]],
        "substations": (
            [{"filter": f, "ref": "dams",
              "radius": config.INFRA_RADIUS_M["substations"]}
             for f in config.INFRA_LAYERS["substations"]]
            + [{"filter": f, "ref": "plants",
                "radius": config.INFRA_RADIUS_M["substations"]}
               for f in config.INFRA_LAYERS["substations"]]
        ),
        "power_lines": [{"filter": f, "ref": "dams",
                         "radius": config.INFRA_RADIUS_M["power_lines"]}
                        for f in config.INFRA_LAYERS["power_lines"]]
                       + [{"filter": f, "ref": "plants",
                           "radius": config.INFRA_RADIUS_M["power_lines"]}
                          for f in config.INFRA_LAYERS["power_lines"]],
        "conduits": [{"filter": f, "ref": "dams",
                      "radius": config.INFRA_RADIUS_M["conduits"]}
                     for f in config.INFRA_LAYERS["conduits"]],
    }

    # Com `--skip-infra` não vamos buscar centrais/subestações/linhas/condutas.
    if skip_infra:
        collect_map = {}
        log("[build] --skip-infra: a saltar infraestruturas")

    for cc in countries:
        area_expr = config.COUNTRIES[cc]
        for layer, collect in collect_map.items():
            plant_filters = config.INFRA_LAYERS["plants"] if layer != "plants" else None
            els = fetch_layer(cc, layer, area_expr, cc, config.INFRA_LAYERS[layer],
                              offline, collect=collect, plant_filters=plant_filters)
            feats = geo.elements_to_features(dedupe_elements(els))
            for f in feats:
                f["country"] = cc
            target = {"plants": all_plants, "substations": all_substations,
                      "power_lines": all_lines, "conduits": all_conduits}[layer]
            target.extend(feats)
            if not offline:
                overpass.pause()

    # -- Associação espacial ---------------------------------------------
    log("[build] a associar albufeiras e centrais às barragens...")
    associate(all_dams, all_reservoirs, all_plants)
    all_dams = filter_dams(all_dams)
    all_reservoirs = link_and_filter_reservoirs(all_reservoirs, all_dams)

    # -- Filtragem fina das infraestruturas ------------------------------
    def within_dams(feats, max_m):
        if not all_dams or not feats:
            return []
        dam_points = [geo.to_metric(d["point"]) for d in all_dams]
        tree = STRtree(dam_points)
        kept = []
        for f in feats:
            gm = geo.to_metric(f["geom"])
            if any(dam_points[i].distance(gm) <= max_m for i in tree.query(gm.buffer(max_m))):
                kept.append(f)
        return kept

    all_substations = within_dams(all_substations, config.SUBSTATION_KEEP_M)
    all_lines = within_dams(all_lines, config.LINE_KEEP_M)
    all_conduits = within_dams(all_conduits, config.CONDUIT_KEEP_M)

    # -- Escrever camadas (por país) -------------------------------------
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_dams(all_dams)
    write_dam_geoms(all_dams)
    write_reservoirs(all_reservoirs)
    write_simple(all_weirs, "weirs", "name")
    write_simple(all_plants, "plants", "name", extra=attrs_power)
    write_simple(all_substations, "substations", "name")
    write_simple(all_lines, "power_lines", "name")
    write_simple(all_conduits, "conduits", "name")

    # Reconstrói `layers`/`counts` a partir do disco (merge com o outro país).
    rebuild_manifest(manifest)

    # -- Validação mínima (após a escrita, antes do commit) ---------------
    if not force and not offline and prev and not prev.get("sample"):
        prev_dams = prev.get("counts", {}).get("dams", 0)
        new_dams = manifest["counts"].get("dams", 0)
        if prev_dams and new_dams < prev_dams * config.MIN_DAMS_RATIO:
            raise SystemExit(
                f"[validação] total de barragens {new_dams} < 80% de {prev_dams}. "
                f"A abortar sem commit (os dados bons mantêm-se). Usa --force para forçar."
            )
    log(f"[validação] barragens: {manifest['counts'].get('dams', 0)} "
        f"(anterior: {prev.get('counts', {}).get('dams', 'n/a') if prev else 'n/a'})")

    # -- Notion (se já existir) ------------------------------------------
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
    log("[build] manifest -> data/manifest.json")


def attrs_power(tags: dict) -> dict:
    return {
        "power_mw": to_float(first_tag(tags, "plant:output:electricity",
                                       "generator:output:electricity")),
        "method": first_tag(tags, "generator:method", "plant:method"),
    }


def common_attrs(tags: dict) -> dict:
    return {
        "name": tags.get("name"),
        "name_pt": first_tag(tags, "name:pt"),
        "name_es": first_tag(tags, "name:es"),
        "operator": tags.get("operator"),
        "height": to_float(tags.get("height")),
        "ele": to_float(tags.get("ele")),
        "start_date": tags.get("start_date"),
        "wikidata": tags.get("wikidata"),
        "wikipedia": tags.get("wikipedia"),
        "ref": tags.get("ref"),
        "volume": to_float(first_tag(tags, "volume", "capacity")),
    }


def write_dams(dams: list[dict]):
    features = []
    for d in dams:
        tags = d["tags"]
        props = common_attrs(tags)
        props.update({
            "dam_id": d["dam_id"],
            "osm_type": d["osm_type"],
            "osm_id": d["osm_id"],
            "country": d["country"],
            "uso": d["uso"],
            "uso_fonte": d["uso_fonte"],
            "river": first_tag(tags, "waterway:name", "river", "is_in:river"),
            "reservoir_id": d.get("reservoir_id"),
            "reservoir_name": d.get("reservoir_name"),
            "reservoir_area_ha": d.get("reservoir_area_ha"),
            "plant_ids": d.get("plant_ids", []),
            "plant_names": d.get("plant_names", []),
            "plant_power_mw": d.get("plant_power_mw"),
            "members": d.get("members", []),
        })
        add_feature(features, d, props, simplify_and_round(d["point"], "dams"))
    write_layer("dams", features)


def write_dam_geoms(dams: list[dict]):
    """
    Escreve a geometria real de cada barragem (linha ou polígono), separada
    da camada de pontos. O frontend desenha-a como contorno a partir de
    certo zoom, ligada por `dam_id`.
    """
    features = []
    for d in dams:
        props = {
            "dam_id": d["dam_id"],
            "osm_type": d["osm_type"],
            "osm_id": d["osm_id"],
            "country": d["country"],
            "name": d["tags"].get("name"),
            "uso": d["uso"],
        }
        add_feature(features, d, props, simplify_and_round(d["geom"], "dam_geoms"))
    write_layer("dam_geoms", features)


def write_reservoirs(reservoirs: list[dict]):
    features = []
    for r in reservoirs:
        tags = r["tags"]
        # Propriedades mínimas: só o que a interface usa (pesquisa, destaque).
        props = {
            "reservoir_id": f'{r["osm_type"]}/{r["osm_id"]}',
            "dam_id": r.get("dam_id"),
            "country": r["country"],
            "name": tags.get("name"),
            "name_pt": first_tag(tags, "name:pt"),
            "name_es": first_tag(tags, "name:es"),
            "usage": tags.get("usage"),
            "reservoir_type": tags.get("reservoir_type"),
            "area_ha": round(r.get("area_ha", geo.area_ha(r["geom"])), 1),
        }
        add_feature(features, r, props, simplify_and_round(r["geom"], "reservoirs"))
    write_layer("reservoirs", features)


def write_simple(feats: list[dict], layer: str, _name_field: str, extra=None):
    features = []
    for f in feats:
        tags = f["tags"]
        props = {
            "osm_type": f["osm_type"],
            "osm_id": f["osm_id"],
            "country": f.get("country"),
            "name": tags.get("name"),
            "operator": tags.get("operator"),
            "wikidata": tags.get("wikidata"),
            "wikipedia": tags.get("wikipedia"),
        }
        if extra:
            props.update(extra(tags))
        add_feature(features, f, props, simplify_and_round(f["geom"], layer))
    write_layer(layer, features)


def read_previous_manifest() -> dict | None:
    if config.LAST_GOOD_FILE.exists():
        try:
            with config.LAST_GOOD_FILE.open(encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return None
    return None


def main():
    parser = argparse.ArgumentParser(description="Gera os dados das barragens.")
    parser.add_argument("--offline", action="store_true",
                        help="usa fixtures locais em vez da Overpass")
    parser.add_argument("--countries", default="PT,ES",
                        help="lista separada por vírgulas (ex.: PT,ES)")
    parser.add_argument("--force", action="store_true",
                        help="ignora a validação mínima de barragens")
    parser.add_argument("--skip-infra", action="store_true",
                        help="não extrai centrais/subestações/linhas/condutas")
    args = parser.parse_args()

    countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    invalid = [c for c in countries if c not in config.COUNTRIES]
    if invalid:
        raise SystemExit(f"Países inválidos: {invalid}. Válidos: {list(config.COUNTRIES)}")

    run(countries, args.offline, args.force, args.skip_infra)


if __name__ == "__main__":
    main()
