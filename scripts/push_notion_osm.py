"""
Preenche a coluna "OSM" das páginas do Notion com o ID do OpenStreetMap.

Cada barragem tem um ID estável `tipo/id` (ex.: `way/107571431`), o mesmo
`dam_id` que o pipeline escreve em `data/dams_*.geojson`. Este script escreve
esse ID na propriedade `OSM` de cada página da base de barragens do Notion.

Estratégia (por página):
  1. Se já tiver um valor em `OSM` ou em `ID Mapa`, usa-o (não inventa nada).
  2. Caso contrário, casa o **título da página** com o nome das barragens de
     `data/dams_*.geojson` (ignora acentos e prefixos como "Barragem de").
     Se houver mais do que um candidato, tenta desempatar pelo país.
  3. Escreve o `dam_id` na propriedade `OSM`.

Por omissão corre em modo de ensaio (--dry-run): mostra o que faria, sem
escrever. Usa --apply para escrever mesmo.

Variáveis de ambiente (as mesmas do fetch_notion.py):
    NOTION_TOKEN          token da integração (PRECISA de permissão de escrita:
                          "Insert content" e "Update content")
    NOTION_DATABASE_ID    id da base de barragens

Uso:
    python scripts/push_notion_osm.py                    # ensaio (não escreve)
    python scripts/push_notion_osm.py --apply            # escreve
    python scripts/push_notion_osm.py --apply --ensure-property
    python scripts/push_notion_osm.py --value url        # guarda o URL do OSM
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import notion_ids  # noqa: E402

NOTION_VERSION = "2022-06-28"
API = "https://api.notion.com/v1"
OSM_PROPERTY = "OSM"
ID_PROPERTY = config.NOTION_ID_PROPERTY   # "ID Mapa"
TIPO_PROPERTY = "Tipo_objeto"            # só linhas com Tipo_objeto = barragem

# Nomes de propriedade onde pode estar o país (para desempate).
COUNTRY_PROP_NAMES = {"país", "pais", "country"}

# Pausa entre escritas (a API do Notion é ~3 pedidos/s, em média).
WRITE_PAUSE_S = 0.34

# Prefixos de nome a remover, para casar "Barragem de X"/"Albufeira de X" com "X".
NAME_PREFIXES = (
    "barragem de ", "barragem da ", "barragem do ", "barragem ",
    "presa de ", "presa da ", "presa del ", "presa ",
    "embalse de ", "embalse del ", "embalse ",
    "albufeira de ", "albufeira do ", "albufeira da ", "albufeira ",
    "encoro de ", "encoro do ", "encoro da ", "encoro ",
    "açude de ", "açude do ", "açude da ", "açude ",
)


def log(msg: str):
    print(msg, flush=True)


def normalize_name(name: str | None) -> str:
    """Minúsculas, sem acentos e sem prefixos comuns (igual ao pipeline)."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    for prefix in NAME_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    # Colapsa conectores: "Castelo de Bode" passa a casar com "Castelo do Bode".
    text = " " + text + " "
    for con in (" de ", " do ", " da ", " dos ", " das ", " del ", " la ", " el ", " y "):
        text = text.replace(con, " ")
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Cliente Notion
# ---------------------------------------------------------------------------

def _request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def query_database(token: str, database_id: str) -> list[dict]:
    """Percorre toda a base de dados (paginada)."""
    pages: list[dict] = []
    cursor: str | None = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = _request("POST", f"/databases/{database_id}/query", token, body)
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages


def ensure_osm_property(token: str, database_id: str, value_kind: str) -> str:
    """Garante que a propriedade `OSM` existe; devolve o seu tipo."""
    schema = _request("GET", f"/databases/{database_id}", token)
    props = schema.get("properties", {})
    if OSM_PROPERTY in props:
        return props[OSM_PROPERTY]["type"]
    if value_kind == "url":
        conf = {"url": {}}
    else:
        conf = {"rich_text": {}}
    _request("PATCH", f"/databases/{database_id}", token,
             {"properties": {OSM_PROPERTY: conf}})
    log(f"[notion] propriedade '{OSM_PROPERTY}' criada (tipo {value_kind}).")
    return value_kind


# ---------------------------------------------------------------------------
# Leitura de páginas
# ---------------------------------------------------------------------------

def _rich_text(prop: dict | None) -> str:
    if not prop:
        return ""
    parts = prop.get("rich_text") or prop.get("title") or []
    return "".join(p.get("plain_text", "") for p in parts).strip()


def page_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return _rich_text(prop)
    return ""


def page_tipo(page: dict) -> str:
    """Valor de `Tipo_objeto` (ex.: 'barragem'), ou '' se não existir."""
    _, prop = notion_ids.find_property(page.get("properties"), TIPO_PROPERTY)
    if not prop:
        return ""
    kind = prop.get("type")
    if kind in ("select", "status"):
        return ((prop.get(kind) or {}).get("name") or "").strip()
    if kind in ("rich_text", "title"):
        return _rich_text(prop)
    return ""


def page_country(page: dict) -> str | None:
    for name, prop in page.get("properties", {}).items():
        if name.lower() not in COUNTRY_PROP_NAMES:
            continue
        kind = prop.get("type")
        if kind == "select" and prop.get("select"):
            return prop["select"].get("name")
        if kind in ("rich_text", "title"):
            val = _rich_text(prop)
            if val:
                return val
    return None


def page_existing_id(page: dict) -> str | None:
    """Valor já existente em `OSM` ou `ID Mapa`, se houver."""
    for alt in (OSM_PROPERTY, ID_PROPERTY):
        _, prop = notion_ids.find_property(page.get("properties"), alt)
        if not prop:
            continue
        kind = prop.get("type")
        val = prop.get("url") if kind == "url" else _rich_text(prop)
        if val:
            return val.strip()
    return None


# ---------------------------------------------------------------------------
# Barragens de data/dams_*.geojson
# ---------------------------------------------------------------------------

def load_dams() -> list[dict]:
    props: list[dict] = []
    for path in sorted(glob.glob(str(config.DATA_DIR / "dams_*.geojson"))) + \
            sorted(glob.glob(str(config.DATA_DIR / "dams.geojson"))):
        try:
            with open(path, encoding="utf-8") as fh:
                features = json.load(fh).get("features", [])
        except Exception as exc:  # noqa: BLE001
            log(f"[dados] não consegui ler {path}: {exc}")
            continue
        props.extend(f["properties"] for f in features if f.get("properties"))
    log(f"[dados] {len(props)} barragens carregadas de data/")
    return props


def build_index(dams: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for p in dams:
        # Inclui o nome da albufeira associada (`reservoir_name`): muitas
        # barragens grandes não têm nome próprio no OSM (o nome está na albufeira).
        # Inclui também o link Wikipédia (`pt:Barragem de X`), que muitas vezes
        # tem o nome que falta.
        wiki = p.get("wikipedia") or ""
        if ":" in wiki:
            wiki = wiki.split(":", 1)[1]
        for raw in (p.get("name"), p.get("name_pt"), p.get("name_es"),
                    p.get("reservoir_name"), wiki):
            key = normalize_name(raw)
            if key:
                index.setdefault(key, []).append(p)
    return index


def match_dam(title: str, country: str | None,
              index: dict[str, list[dict]]) -> tuple[dict | None, str]:
    """Casa um título de página com uma barragem. Devolve (dam, motivo)."""
    key = normalize_name(title)
    if not key:
        return None, "sem nome no título"

    candidates = list(index.get(key, []))
    if not candidates:
        # Último recurso: correspondência parcial (contém).
        for k, v in index.items():
            if key in k or k in key:
                candidates.extend(v)

    # Deduplica por barragem (o mesmo dam_id pode entrar por mais do que um nome).
    uniq: dict[str, dict] = {}
    for c in candidates:
        uniq.setdefault(c.get("dam_id"), c)

    if not uniq:
        return None, "sem correspondência por nome"
    if len(uniq) == 1:
        return next(iter(uniq.values())), "ok"

    if country:
        cc = [c for c in uniq.values() if (c.get("country") or "").upper() == country.upper()]
        if len(cc) == 1:
            return cc[0], "ok (desempate por país)"

    return None, f"ambíguo ({len(uniq)} candidatos)"


# ---------------------------------------------------------------------------
# Ações
# ---------------------------------------------------------------------------

def set_page_osm(token: str, page_id: str, value: str, kind: str):
    if kind == "url":
        props = {OSM_PROPERTY: {"url": value}}
    else:
        props = {OSM_PROPERTY: {
            "rich_text": [{"type": "text", "text": {"content": value}}]
        }}
    _request("PATCH", f"/pages/{page_id}", token, {"properties": props})


def osm_value(dam_id: str, value_kind: str) -> str:
    if value_kind == "url":
        return f"https://www.openstreetmap.org/{dam_id}"
    return dam_id


REPORT_PATH = config.ROOT / "exports" / "notion_osm_propostas.csv"


def write_report(rows: list[list[str]]):
    """Escreve o relatório (para revisão) com o estado de cada página."""
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Pagina", "ID_OSM", "Estado", "Nota"])
            w.writerows(rows)
    except Exception as exc:  # noqa: BLE001
        log(f"[relatorio] não consegui escrever {REPORT_PATH}: {exc}")


def main():
    parser = argparse.ArgumentParser(
        description="Preenche a coluna OSM das páginas do Notion com o dam_id.")
    parser.add_argument("--apply", action="store_true",
                        help="escreve mesmo (por omissão é só ensaio)")
    parser.add_argument("--ensure-property", action="store_true",
                        help="cria a propriedade OSM se não existir")
    parser.add_argument("--value", choices=["id", "url"], default="id",
                        help="guarda o id (way/…) ou o URL completo do OSM")
    parser.add_argument("--database", default=os.environ.get("NOTION_DATABASE_ID"),
                        help="id da base (por omissão NOTION_DATABASE_ID)")
    args = parser.parse_args()

    token = os.environ.get("NOTION_TOKEN")
    if not token or not args.database:
        log("[notion] NOTION_TOKEN/NOTION_DATABASE_ID em falta — nada a fazer.")
        return

    mode = "ESCRITA" if args.apply else "ENSAIO (--dry-run)"
    log(f"[notion] modo: {mode}")

    prop_kind = args.value
    if args.ensure_property and args.apply:
        prop_kind = ensure_osm_property(token, args.database, args.value)
    elif args.value == "url":
        prop_kind = "url"

    pages = query_database(token, args.database)
    log(f"[notion] {len(pages)} páginas lidas.")

    dams = load_dams()
    index = build_index(dams)
    resolver = notion_ids.DamResolver()

    counts = {"ok": 0, "ja_tinha": 0, "manual": 0, "ambiguo": 0, "sem_match": 0, "erro": 0}
    relatorio: list[list[str]] = []   # [pagina, id_osm, estado, nota]

    for page in pages:
        page_id = page.get("id")
        titulo = page_title(page) or "<sem título>"

        # Só linhas de barragem levam id do OSM (aldeias/bairros não são feições OSM).
        tipo = page_tipo(page)
        if tipo and tipo.strip().lower() != "barragem":
            relatorio.append([titulo, "", "ignorado", f"Tipo_objeto={tipo}"])
            continue

        existing = page_existing_id(page)

        # Ligação definida à mão (nome ambíguo, sem correspondência, id que
        # aponta para outra barragem). A lista manda: se o valor for diferente,
        # é corrigido.
        manual = notion_ids.manual_dam(titulo)
        if manual and not resolver.resolve(manual)[0]:
            log(f"[aviso] {titulo}: id manual {manual} não existe nos dados — ignorado.")
            manual = None
        if manual and manual != notion_ids.normalize_osm_id(existing):
            if args.apply:
                try:
                    set_page_osm(token, page_id, osm_value(manual, prop_kind), prop_kind)
                    counts["manual"] += 1
                    log(f"[manual] {titulo} -> {manual}")
                    relatorio.append([titulo, manual, "ligação manual", ""])
                    time.sleep(WRITE_PAUSE_S)
                except urllib.error.HTTPError as exc:
                    counts["erro"] += 1
                    relatorio.append([titulo, manual, "erro", f"HTTP {exc.code}"])
                    log(f"[erro] {titulo}: HTTP {exc.code} "
                        f"{exc.read().decode('utf-8', 'replace')[:200]}")
            else:
                counts["manual"] += 1
                relatorio.append([titulo, manual, "ligação manual (ensaio)", ""])
                log(f"[manual?] {titulo} -> {manual}")
            continue

        if existing:
            counts["ja_tinha"] += 1
            relatorio.append([titulo, existing, "já tinha", ""])
            continue

        dam, motivo = match_dam(titulo, page_country(page), index)
        if dam is None:
            amb = motivo.startswith("ambíguo")
            counts["ambiguo" if amb else "sem_match"] += 1
            relatorio.append([titulo, "", "ambíguo" if amb else "sem correspondência", motivo])
            log(f"[--] {titulo}: {motivo}")
            continue

        dam_id = dam.get("dam_id")
        counts["ok"] += 1

        if args.apply:
            try:
                set_page_osm(token, page_id, osm_value(dam_id, prop_kind), prop_kind)
                log(f"[ok] {titulo} -> {dam_id}")
                relatorio.append([titulo, dam_id, "preenchido", motivo])
                time.sleep(WRITE_PAUSE_S)
            except urllib.error.HTTPError as exc:
                counts["ok"] -= 1
                counts["erro"] += 1
                relatorio.append([titulo, dam_id, "erro", f"HTTP {exc.code}"])
                log(f"[erro] {titulo}: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')[:200]}")
        else:
            relatorio.append([titulo, dam_id, "a preencher", motivo])
            log(f"[ok?] {titulo} -> {dam_id}  ({motivo})")

    write_report(relatorio)

    log("")
    log(f"[resumo] já tinham ID: {counts['ja_tinha']} | "
        f"a preencher: {counts['ok']} | ligações manuais: {counts['manual']} | "
        f"ambíguos: {counts['ambiguo']} | "
        f"sem correspondência: {counts['sem_match']} | erros: {counts['erro']}")
    log(f"[resumo] relatório para revisão: {REPORT_PATH}")
    if not args.apply:
        log("[resumo] ensaio — nada foi escrito. Reexecuta com --apply para gravar.")


if __name__ == "__main__":
    main()
