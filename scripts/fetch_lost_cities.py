"""
Integra a base "Lost Cities - BD" do Notion no mapa.

Lê a base de dados do Notion (API oficial) ou, em alternativa, um export
local (`--from-export`), seleciona os registos de **Aldeia Submersa** e
**Bairro Novo**, geocodifica o campo `Coordenadas` (Nominatim/OSM, com cache
em disco) e gera:

    data/submersos_notion.geojson   (aldeias submersas -> camada `submersos`)
    data/bairros_notion.geojson     (bairros novos     -> camada `bairros`)

e atualiza `data/manifest.json` (camadas/contagens) sem depender do pipeline
OSM (não exige `shapely`).

Via API (recomendada):
    NOTION_TOKEN         token da integração (GitHub Secret)
    NOTION_DATABASE_ID   id da base de dados "Lost Cities - BD"

Uso:
    python scripts/fetch_lost_cities.py                    # via Notion API
    python scripts/fetch_lost_cities.py --from-export DIR  # export local (.md)
    python scripts/fetch_lost_cities.py --dry-run          # não escreve
    python scripts/fetch_lost_cities.py --no-geocode       # só usa a cache
    python scripts/fetch_lost_cities.py --offline          # não acede à rede

Se o token não estiver definido e não houver `--from-export`, o script
termina sem erro (o site continua a funcionar sem estes dados).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import notion_ids  # noqa: E402

API_QUERY = "https://api.notion.com/v1/databases/{db}/query"
NOTION_VERSION = "2022-06-28"
GEOCODE_URL = "https://nominatim.openstreetmap.org/search"
GEOCODE_CACHE = config.SCRIPTS_DIR / "geocode_cache.json"
GEOCODE_PAUSE_S = 1.1   # política do Nominatim: <= 1 pedido/s

# Tipos de resultado do Nominatim considerados fiáveis (ponto) vs. demasiado
# genéricos. Os restantes (pub, hotel, cemitério…) marcam-se como "duvidosa".
POINT_TYPES = {
    "dam", "village", "hamlet", "town", "city", "residential",
    "neighbourhood", "suburb", "locality", "isolated_dwelling", "farm",
    "quarter", "borough", "water", "stream",
}
COARSE_TYPES = {
    "administrative", "country", "state", "region", "county",
    "municipality", "province", "district",
}

# Nomes das propriedades na base "Lost Cities - BD".
P_TITLE = "Objeto"
P_CAMADAS = "Camadas"
P_COORD = "Coordenadas"
P_CONCLUSAO = "Data conclusão"
P_INICIAL = "Data inicial"
P_LOCALIZACAO = "Localização"
P_NOTAS_CR = "Notas CR"
P_NOTAS_IHP = "Notas IHP"
P_PROMOTOR = "Promotor"
P_RIO = "Rio"
P_RUINAS = "Ruínas"
P_TIPO = "Tipo"
P_TIPO_OBJ = "Tipo_objeto"
P_ARQUIVOS = "Arquivos"
P_FOTOS = "Fotografias"
P_RELATED = "Related Lost Cities - BD"
P_OSM = "OSM"   # id do OSM da barragem-mãe (mesma coluna da base única)

# Chaves aceites no parser do export (.md).
EXPORT_KEYS = [
    P_ARQUIVOS, P_CAMADAS, P_COORD, P_CONCLUSAO, P_INICIAL, P_FOTOS,
    P_LOCALIZACAO, P_NOTAS_CR, P_NOTAS_IHP, P_PROMOTOR, P_RELATED, P_OSM,
    P_RIO, P_RUINAS, P_TIPO, P_TIPO_OBJ,
]

# Propriedades cujo valor pode ocupar várias linhas no export (.md).
EXPORT_CONT_KEYS = {P_NOTAS_CR, P_NOTAS_IHP, P_ARQUIVOS}

SUBMERSO = "submersos"
BAIRRO = "bairros"


def log(msg: str):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Utilitários de texto
# ---------------------------------------------------------------------------

def slug(text: str) -> str:
    """Slug ASCII simples (id estável do ponto)."""
    norm = unicodedata.normalize("NFKD", text or "")
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    norm = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()
    return norm or "sem-nome"


def _year(value: str) -> str:
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", value or "")
    return m.group(1) if m else ""


def _first(value):
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


# ---------------------------------------------------------------------------
# Normalização de propriedades do Notion (API)
# ---------------------------------------------------------------------------

def prop_text(prop: dict | None) -> str:
    """Texto simples de uma propriedade Notion, seja qual for o tipo."""
    if not prop:
        return ""
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(p.get("plain_text", "") for p in prop.get(t, [])).strip()
    if t == "select":
        return (prop.get("select") or {}).get("name", "")
    if t == "status":
        return (prop.get("status") or {}).get("name", "")
    if t == "multi_select":
        return ", ".join(o.get("name", "") for o in prop.get("multi_select", []))
    if t == "date":
        return (prop.get("date") or {}).get("start", "") or ""
    if t == "number":
        v = prop.get("number")
        return "" if v is None else str(v)
    if t == "url":
        return prop.get("url") or ""
    if t == "email":
        return prop.get("email") or ""
    if t == "phone_number":
        return prop.get("phone_number") or ""
    if t in ("formula", "rollup"):
        inner = prop.get(t, {})
        return prop_text(inner) if isinstance(inner, dict) else ""
    if t == "files":
        return ", ".join(f.get("name", "") for f in prop.get("files", []))
    if t == "relation":
        return ", ".join(r.get("id", "") for r in prop.get("relation", []))
    return ""


def prop_list(prop: dict | None) -> list[str]:
    if not prop:
        return []
    t = prop.get("type")
    if t == "multi_select":
        return [o.get("name", "") for o in prop.get("multi_select", [])]
    if t in ("title", "rich_text"):
        return [p.get("plain_text", "") for p in prop.get(t, []) if p.get("plain_text")]
    txt = prop_text(prop)
    return [x.strip() for x in re.split(r",\s*", txt) if x.strip()]


def prop_relation_ids(prop: dict | None) -> list[str]:
    if not prop or prop.get("type") != "relation":
        return []
    return [r.get("id", "") for r in prop.get("relation", [])]


def _prop(props: dict, name: str) -> dict | None:
    """Propriedade da base pelo nome, ignorando maiúsculas/minúsculas."""
    _, p = notion_ids.find_property(props, name)
    return p


def record_from_page(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "page_id": page.get("id"),
        "url": page.get("url"),
        "name": prop_text(_prop(props, P_TITLE)) or "(sem título)",
        "tipo_objeto": prop_text(_prop(props, P_TIPO_OBJ)),
        "camadas": prop_list(_prop(props, P_CAMADAS)),
        "coordenadas": prop_text(_prop(props, P_COORD)),
        "localizacao": prop_text(_prop(props, P_LOCALIZACAO)),
        "rio": prop_text(_prop(props, P_RIO)),
        "tipo": prop_text(_prop(props, P_TIPO)),
        "promotor": prop_text(_prop(props, P_PROMOTOR)),
        "ruinas": prop_list(_prop(props, P_RUINAS)),
        "ano": _year(prop_text(_prop(props, P_CONCLUSAO))),
        "ano_inicial": _year(prop_text(_prop(props, P_INICIAL))),
        "notas_cr": prop_text(_prop(props, P_NOTAS_CR)),
        "notas_ihp": prop_text(_prop(props, P_NOTAS_IHP)),
        "arquivos": prop_list(_prop(props, P_ARQUIVOS)),
        "fotografias": prop_text(_prop(props, P_FOTOS)),
        "related_ids": prop_relation_ids(_prop(props, P_RELATED)),
        "related_osm": [],
        "osm": prop_text(_prop(props, P_OSM)),
        "related_titles": [],
    }


# ---------------------------------------------------------------------------
# Carregamento: API do Notion
# ---------------------------------------------------------------------------

def query_database(token: str, database_id: str) -> list[dict]:
    pages: list[dict] = []
    cursor: str | None = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        req = urllib.request.Request(
            API_QUERY.format(db=database_id),
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages


def load_from_api() -> list[dict]:
    token = os.environ.get("NOTION_TOKEN")
    database_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not database_id:
        return []
    pages = query_database(token, database_id)
    if pages:
        log(f"[notion] propriedades da base: {sorted(pages[0].get('properties', {}).keys())}")
    # índices id -> título / id -> OSM (para resolver relações)
    id_to_title = {p["id"]: prop_text(p.get("properties", {}).get(P_TITLE)) for p in pages}
    id_to_osm = {p["id"]: prop_text(p.get("properties", {}).get(P_OSM)) for p in pages}
    records = []
    for p in pages:
        rec = record_from_page(p)
        rec["related_titles"] = [id_to_title.get(i, "") for i in rec["related_ids"]]
        rec["related_osm"] = [id_to_osm.get(i, "") for i in rec["related_ids"]]
        records.append(rec)
    log(f"[notion] {len(records)} registos lidos via API.")
    com_coord = sum(1 for r in records if r.get("coordenadas"))
    log(f"[notion] {com_coord} de {len(records)} registos com «{P_COORD}» preenchido.")
    return records


# ---------------------------------------------------------------------------
# Carregamento: export local (.md)
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(r"^(" + "|".join(re.escape(k) for k in EXPORT_KEYS) + r"):\s?(.*)$")


def _related_titles_from_text(value: str) -> list[str]:
    """'Aguieira (path.md), AS Foz do Dão (path.md)' -> ['Aguieira', 'AS Foz do Dão']."""
    out = []
    for part in re.split(r",\s*(?=[^)]*(?:\(|$))", value or ""):
        title = part.split(" (")[0].strip()
        if title:
            out.append(title)
    return out


def load_from_export(dirpath: str) -> list[dict]:
    root = Path(dirpath)
    mds = sorted(root.glob("*.md"))
    if not mds:
        # aceita apontar para a pasta-pai do export
        mds = sorted(root.rglob("*.md"))
    records: list[dict] = []
    for md in mds:
        text = md.read_text(encoding="utf-8")
        title = None
        props: dict[str, list[str]] = {}
        cur = None
        in_sections = False
        for ln in text.splitlines():
            if in_sections:
                continue
            if ln.startswith("# ") and title is None:
                title = ln[2:].strip()
                continue
            if ln.startswith("### "):
                in_sections = True
                cur = None
                continue
            m = _KEY_RE.match(ln)
            if m:
                cur = m.group(1)
                props.setdefault(cur, []).append(m.group(2).strip())
            elif cur and ln.strip() and cur in EXPORT_CONT_KEYS:
                props[cur].append(ln.strip())
        if title is None:
            title = re.sub(r"\s+[0-9a-f]{32}\.md$", "", md.name)
        if not props.get(P_TIPO_OBJ):
            continue  # página sem propriedades (índice/media)
        joined = {k: "\n".join(v) for k, v in props.items()}
        records.append({
            "page_id": None,
            "url": None,
            "name": title,
            "tipo_objeto": joined.get(P_TIPO_OBJ, ""),
            "camadas": [x.strip() for x in joined.get(P_CAMADAS, "").split(",") if x.strip()],
            "coordenadas": joined.get(P_COORD, ""),
            "localizacao": joined.get(P_LOCALIZACAO, ""),
            "rio": joined.get(P_RIO, ""),
            "tipo": joined.get(P_TIPO, ""),
            "promotor": joined.get(P_PROMOTOR, ""),
            "ruinas": [x.strip() for x in joined.get(P_RUINAS, "").split(",") if x.strip()],
            "ano": _year(joined.get(P_CONCLUSAO, "")),
            "ano_inicial": _year(joined.get(P_INICIAL, "")),
            "notas_cr": joined.get(P_NOTAS_CR, ""),
            "notas_ihp": joined.get(P_NOTAS_IHP, ""),
            "arquivos": [x.strip() for x in joined.get(P_ARQUIVOS, "").split(",") if x.strip()],
            "fotografias": joined.get(P_FOTOS, ""),
            "related_ids": [],
            "related_osm": [],
            "osm": joined.get(P_OSM, ""),
            "related_titles": _related_titles_from_text(joined.get(P_RELATED, "")),
        })
    log(f"[export] {len(records)} registos lidos de {root}.")
    return records


# ---------------------------------------------------------------------------
# Geocodificação (Nominatim + cache)
# ---------------------------------------------------------------------------

def load_cache() -> dict:
    if GEOCODE_CACHE.exists():
        try:
            return json.loads(GEOCODE_CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_cache(cache: dict):
    GEOCODE_CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def geocode(query: str, cache: dict, allow_network: bool) -> dict | None:
    key = (query or "").strip().lower()
    if not key:
        return None
    if key in cache:
        return cache[key]
    if not allow_network:
        return None
    params = urllib.parse.urlencode({
        "q": query, "format": "jsonv2", "limit": 1,
        "countrycodes": "pt", "addressdetails": 0,
    })
    req = urllib.request.Request(
        f"{GEOCODE_URL}?{params}", headers={"User-Agent": config.USER_AGENT})
    time.sleep(GEOCODE_PAUSE_S)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        log(f"[geocode] falha em «{query}»: {exc}")
        return None
    if not data:
        cache[key] = None
        return None
    hit = data[0]
    result = {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "type": hit.get("type", ""),
        "place_rank": hit.get("place_rank"),
        "display_name": hit.get("display_name", ""),
    }
    cache[key] = result
    log(f"[geocode] «{query}» -> {result['lat']:.5f}, {result['lon']:.5f} ({result['type']})")
    return result


# ---------------------------------------------------------------------------
# Classificação e construção de features
# ---------------------------------------------------------------------------

def classify(rec: dict) -> str | None:
    obj = (rec.get("tipo_objeto") or "").strip().lower()
    if obj == "aldeia submersa":
        return SUBMERSO
    if obj in ("bairro", "bairro novo"):
        return BAIRRO
    if obj == "barragem":
        return None
    # Sem Tipo_objeto útil: usar `Camadas` como fallback.
    camadas = {c.strip().lower() for c in rec.get("camadas", [])}
    if "aldeia submersa" in camadas:
        return SUBMERSO
    if "bairro novo" in camadas:
        return BAIRRO
    return None


def parent_barragem(rec: dict, tipo_by_title: dict) -> str:
    """Título da barragem-mãe (via relação), se existir."""
    for title in rec.get("related_titles", []):
        if (tipo_by_title.get(title.strip().lower()) or "").strip().lower() == "barragem":
            return title
    return ""


def resolve_parent_dam_id(rec: dict, by_name: dict, resolver: "notion_ids.DamResolver") -> str | None:
    """`dam_id` da barragem-mãe, a partir do id OSM (da relação ou pelo nome)."""
    for raw in rec.get("related_osm", []) or []:
        dam_id, _ = resolver.resolve(raw)
        if dam_id:
            return dam_id
    for title in rec.get("related_titles", []) or []:
        brec = by_name.get(title.strip().lower())
        if brec:
            dam_id, _ = resolver.resolve(brec.get("osm"))
            if dam_id:
                return dam_id
    return None


def geocode_precision(geo: dict | None) -> str:
    """Classifica a confiança do resultado do geocoder pelo tipo devolvido."""
    if not geo:
        return "nenhuma"
    t = (geo.get("type") or "").lower()
    if t in POINT_TYPES:
        return "boa"
    if t in COARSE_TYPES:
        return "grosseira"
    return "duvidosa"


def build_feature(rec: dict, geo: dict | None, barragem: str,
                  anchored: bool = False, prec: str = "boa",
                  dam_id: str | None = None) -> dict:
    name = rec["name"]
    confianca = "confirmado" if (rec.get("arquivos") or rec.get("notas_cr")) else "provavel"
    local = rec["coordenadas"] or "sem campo Coordenadas"
    if anchored:
        ressalva = (f"Posição ancorada na barragem «{barragem}» (a povoação situava-se "
                    f"na sua albufeira; não geocodificada a partir de «{local}») — confirmar.")
    elif prec == "grosseira":
        ressalva = (f"Geocodificação de «{local}» resulta num ponto grosseiro "
                    f"({(geo or {}).get('type')}) — confirmar a localização.")
    elif prec == "duvidosa":
        ressalva = (f"Geocodificação duvidosa de «{local}» (tipo: "
                    f"{(geo or {}).get('type')}); pode não corresponder ao local — confirmar.")
    elif prec == "nenhuma":
        ressalva = f"Sem coordenadas — não foi possível geocodificar «{local}»."
    else:
        ressalva = ""
    props = {
        "id": slug(name),
        "name": name,
        "barragem": barragem,
        "dam_id": dam_id,   # liga o ponto à ficha da barragem no mapa
        "rio": rec.get("rio", ""),
        "local": rec.get("coordenadas", ""),
        "pais": "PT",
        "ano": rec.get("ano", ""),
        "tipo": rec.get("tipo", ""),
        "camadas": ", ".join(rec.get("camadas", [])),
        "promotor": rec.get("promotor", ""),
        "confianca": confianca,
        "fonte": "Notion — Lost Cities - BD",
        "notion_url": rec.get("url") or "",
        "geocode": (geo or {}).get("display_name", ""),
        "geocode_rank": (geo or {}).get("place_rank"),
        "geocode_prec": prec,
        "ancorado": anchored or None,
        "ressalva": ressalva,
    }
    return {
        "type": "Feature",
        "properties": {k: v for k, v in props.items() if v not in ("", None)},
        "geometry": ({"type": "Point", "coordinates": [geo["lon"], geo["lat"]]}
                     if geo else None),
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def list_layer_files(name: str) -> list[str]:
    files = sorted(p.name for p in config.DATA_DIR.glob(f"{name}_*.geojson"))
    single = config.DATA_DIR / f"{name}.geojson"
    if single.exists():
        files = [single.name] + files
    return files


def count_features(filename: str) -> int:
    try:
        data = json.loads((config.DATA_DIR / filename).read_text(encoding="utf-8"))
        return len(data.get("features", []))
    except Exception:  # noqa: BLE001
        return 0


def update_manifest(keys: list[str]):
    path = config.DATA_DIR / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    layers = manifest.setdefault("layers", {})
    counts = manifest.setdefault("counts", {})
    for key in keys:
        files = list_layer_files(key)
        if not files:
            continue
        layers[key] = files
        counts[key] = sum(count_features(f) for f in files)
    manifest["total_features"] = sum(counts.values())
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[manifest] atualizado: {keys} -> total {manifest['total_features']}")


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------

def write_geojson(path: Path, features: list[dict]):
    fc = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def emit(records: list[dict], cache: dict, allow_network: bool, dry_run: bool) -> dict:
    tipo_by_title = {r["name"].strip().lower(): r["tipo_objeto"] for r in records}
    by_name = {r["name"].strip().lower(): r for r in records}

    classified = [(r, k) for r, k in ((r, classify(r)) for r in records) if k]

    # Barragem-mãe de cada povoação/bairro (via relação).
    parents = {r["name"]: parent_barragem(r, tipo_by_title) for r, _ in classified}
    resolver = notion_ids.DamResolver()
    parent_dam_ids = {r["name"]: resolve_parent_dam_id(r, by_name, resolver)
                      for r, _ in classified}

    # Ancora: geocodifica a barragem-mãe — o seu campo Coordenadas costuma
    # ser fiável (ex.: "Barragem da Aguieira").
    anchors: dict[str, dict | None] = {}
    for p in sorted({v for v in parents.values() if v}):
        brec = by_name.get(p.strip().lower())
        if brec:
            anchors[p] = geocode(brec.get("coordenadas", ""), cache, allow_network)

    buckets: dict[str, list] = {SUBMERSO: [], BAIRRO: []}
    sem_coords = {SUBMERSO: [], BAIRRO: []}

    for rec, kind in classified:
        own = geocode(rec.get("coordenadas", ""), cache, allow_network)
        own_prec = geocode_precision(own)
        parent = parents[rec["name"]]
        anchor = anchors.get(parent) if parent else None

        geo, anchored, prec = own, False, own_prec
        if own_prec != "boa" and anchor:
            geo, anchored, prec = anchor, True, "boa"
        if not geo:
            sem_coords[kind].append(rec["name"])
            continue
        buckets[kind].append(build_feature(rec, geo, parent, anchored, prec,
                                           dam_id=parent_dam_ids[rec["name"]]))

    if not dry_run:
        save_cache(cache)
        escritos = []
        # Salvaguarda: nunca substituir um ficheiro com pontos por um vazio
        # (ex.: porque o campo `Coordenadas` ficou sem valores na base).
        for kind, fname in ((SUBMERSO, "submersos_notion.geojson"),
                            (BAIRRO, "bairros_notion.geojson")):
            existentes = count_features(fname)
            if not buckets[kind] and existentes:
                log(f"[{kind}] aviso: 0 pontos novos — mantenho o ficheiro "
                    f"existente ({existentes}). Verifica o campo «{P_COORD}» na base.")
                continue
            write_geojson(config.DATA_DIR / fname, buckets[kind])
            escritos.append(fname)
        if escritos:
            update_manifest([SUBMERSO, BAIRRO])

    for kind, features in buckets.items():
        log(f"[{kind}] {len(features)} pontos"
            + (f"; sem coordenadas: {', '.join(sem_coords[kind])}" if sem_coords[kind] else ""))
    return buckets


def main():
    parser = argparse.ArgumentParser(description="Integra a base Notion 'Lost Cities - BD'.")
    parser.add_argument("--from-export", metavar="DIR",
                        help="lê um export local do Notion (pasta com os .md)")
    parser.add_argument("--dry-run", action="store_true", help="não escreve ficheiros")
    parser.add_argument("--no-geocode", action="store_true",
                        help="não acede ao Nominatim (usa só a cache)")
    parser.add_argument("--offline", action="store_true",
                        help="não acede a nenhuma rede (Notion nem Nominatim)")
    args = parser.parse_args()

    if args.from_export:
        records = load_from_export(args.from_export)
    elif args.offline:
        records = []
    else:
        records = load_from_api()

    if not records:
        log("[lost-cities] sem registos (define NOTION_TOKEN/NOTION_DATABASE_ID "
            "ou usa --from-export). A saltar.")
        return

    cache = load_cache()
    allow_network = not (args.offline or args.no_geocode)
    emit(records, cache, allow_network, args.dry_run)
    log(f"[lost-cities] concluído ({datetime.now(timezone.utc).isoformat(timespec='seconds')})")


if __name__ == "__main__":
    main()
