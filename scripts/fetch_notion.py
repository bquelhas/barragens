"""
Liga as barragens às páginas do Notion.

Lê a **base única** (com `Tipo_objeto` = barragem / Aldeia Submersa / Bairro)
através da API oficial e gera `data/notion.json` no formato:

    { "way/123456": { "url": "...", "titulo": "...",
                      "foto_capa": "...", "resumo": "..." }, ... }

Só trata os registos com `Tipo_objeto` = "barragem" (as aldeias submersas e os
bairros são tratados por `fetch_lost_cities.py`). O id lido da coluna **`OSM`**
(ou, em alternativa, **`ID Mapa`**) é normalizado e **resolvido para o `dam_id`**
da barragem: aceita o id de uma barragem (`waterway=dam`) **ou de uma albufeira**
(que é traduzida para a barragem associada).

Se dois registos apontarem para a mesma barragem, ganha o mais recente
(`last_edited_time`) e é registado um aviso.

Variáveis de ambiente:
    NOTION_TOKEN          token da integração (GitHub Secret)
    NOTION_DATABASE_ID    id da base de dados
    NOTION_PUBLIC_DOMAIN  domínio público do Notion (opcional)

Se o token não estiver definido, o script termina sem erro: o site funciona
na mesma, apenas sem links para o Notion.

Uso:
    python scripts/fetch_notion.py
    python scripts/fetch_notion.py --dry-run   # não escreve ficheiro
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import notion_ids  # noqa: E402

API_URL = "https://api.notion.com/v1/databases/{db}/query"
NOTION_VERSION = "2022-06-28"

# Propriedades na base do Notion.
TIPO_PROPERTY = "Tipo_objeto"
OSM_PROPERTY = "OSM"


def log(msg: str):
    print(msg, flush=True)


def text_of(prop: dict | None) -> str:
    """Texto simples de uma propriedade Notion (vários tipos)."""
    if not prop:
        return ""
    kind = prop.get("type")
    if kind in ("rich_text", "title"):
        return "".join(p.get("plain_text", "") for p in prop.get(kind, [])).strip()
    if kind in ("select", "status"):
        val = prop.get(kind) or {}
        return (val.get("name") or "").strip()
    if kind in ("url", "email", "phone_number"):
        return (prop.get(kind) or "").strip()
    if kind == "number":
        v = prop.get("number")
        return "" if v is None else str(v)
    if kind == "date":
        return ((prop.get("date") or {}).get("start") or "").strip()
    if kind == "multi_select":
        return ", ".join(o.get("name", "") for o in prop.get("multi_select", []))
    if kind in ("formula", "rollup"):
        inner = prop.get(kind) or {}
        return text_of(inner) if isinstance(inner, dict) else ""
    if kind == "string":
        return (prop.get("string") or "").strip()
    if kind == "boolean":
        return str(prop.get("boolean"))
    return ""


def page_tipo(props: dict) -> str:
    """Valor de `Tipo_objeto` (ex.: 'barragem'), ou '' se não existir."""
    _, prop = notion_ids.find_property(props, TIPO_PROPERTY)
    return text_of(prop)


def page_id_value(props: dict) -> str:
    """Id do OSM: coluna `OSM` ou, em alternativa, `ID Mapa`."""
    _, osm = notion_ids.find_property(props, OSM_PROPERTY)
    if text_of(osm):
        return text_of(osm)
    _, alt = notion_ids.find_property(props, config.NOTION_ID_PROPERTY)
    return text_of(alt)


def page_title(props: dict) -> str:
    for prop in props.values():
        if prop.get("type") == "title":
            return text_of(prop)
    return ""


def extract_cover(page: dict) -> str | None:
    """
    URL da capa. Aviso: capas carregadas para o Notion expiram (~1h); para
    fotos estáveis, usar URLs externas.
    """
    cover = page.get("cover")
    if not cover:
        return None
    kind = cover.get("type")
    data = cover.get(kind, {}) if kind else {}
    return data.get("url")


def files_url(prop: dict | None) -> str | None:
    """
    Primeira imagem de uma propriedade **Files & Media** (tipo `files`).

    Aviso: ficheiros carregados para o Notion geram URLs que expiram (~1h);
    para fotos estáveis, usar URLs externas.
    """
    if not prop or prop.get("type") != "files":
        return None
    for f in prop.get("files", []):
        kind = f.get("type")
        if kind == "external":
            return (f.get("external") or {}).get("url")
        if kind == "file":
            return (f.get("file") or {}).get("url")
        if kind == "file_upload":
            return (f.get("file_upload") or {}).get("url")
    return None


def public_url(page: dict) -> str:
    """URL público da página (usa `public_url` se a página estiver publicada)."""
    if page.get("public_url"):
        return page["public_url"]
    domain = os.environ.get("NOTION_PUBLIC_DOMAIN") or config.NOTION_PUBLIC_DOMAIN
    url = page.get("url", "")
    if domain and "notion.so" in url:
        return url.replace("www.notion.so", f"www.{domain}")
    return url


def query_database(token: str, database_id: str) -> list[dict]:
    """Percorre toda a base de dados (paginada)."""
    pages: list[dict] = []
    cursor: str | None = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        req = urllib.request.Request(
            API_URL.format(db=database_id),
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


def build_index(pages: list[dict], resolver: notion_ids.DamResolver) -> dict:
    """Constrói o índice dam_id -> metadados, filtrando e validando."""
    index: dict[str, dict] = {}
    invalid: list[str] = []
    unresolved: list[str] = []
    conflicts: list[str] = []

    for page in pages:
        props = page.get("properties", {})

        # Base única: só interessam os registos de barragem.
        tipo = page_tipo(props)
        if tipo and tipo.strip().lower() != "barragem":
            continue

        raw_id = page_id_value(props)
        dam_id, motivo = resolver.resolve(raw_id)
        if not dam_id:
            if motivo == "sem id":
                invalid.append(raw_id or f"<página sem '{OSM_PROPERTY}'/'{config.NOTION_ID_PROPERTY}'>")
            else:
                unresolved.append(f"{raw_id or page_title(props)} ({motivo})")
            continue

        _, resumo = notion_ids.find_property(props, config.NOTION_SUMMARY_PROPERTY)
        # A foto pode estar em "Foto", "Fotos" ou "Fotografias" (Files & Media).
        _, foto = notion_ids.find_property(
            props, config.NOTION_COVER_PROPERTY, "Fotos", "Fotografias")
        meta = {
            "url": public_url(page),
            "titulo": page_title(props),
            # Prioridade: propriedade "Foto" (Files & Media) -> capa da página.
            "foto_capa": files_url(foto) or extract_cover(page),
            "resumo": text_of(resumo),
            "last_edited": page.get("last_edited_time"),
        }

        prev = index.get(dam_id)
        if prev is not None:
            conflicts.append(dam_id)
            # Ganha o mais recente (last_edited_time ISO ordena bem como texto).
            if (meta.get("last_edited") or "") <= (prev.get("last_edited") or ""):
                continue
        index[dam_id] = meta

    if invalid:
        log(f"[notion] {len(invalid)} registo(s) sem id válido: {invalid[:20]}")
    if unresolved:
        log(f"[notion] {len(unresolved)} id(s) não resolvidos nos dados (barragem/albufeira): "
            f"{unresolved[:20]}")
    if conflicts:
        log(f"[notion] {len(set(conflicts))} barragem(ns) com mais do que uma página "
            f"(ficou a mais recente): {sorted(set(conflicts))[:20]}")
    return index


def main():
    parser = argparse.ArgumentParser(description="Gera data/notion.json.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default=str(config.DATA_DIR / "notion.json"))
    args = parser.parse_args()

    token = os.environ.get("NOTION_TOKEN")
    database_id = os.environ.get("NOTION_DATABASE_ID")

    if not token or not database_id:
        log("[notion] NOTION_TOKEN/NOTION_DATABASE_ID não definidos — "
            "a saltar (o site continua a funcionar sem links).")
        return

    resolver = notion_ids.DamResolver()
    if not resolver.ready:
        log("[notion] aviso: não encontrei barragens em data/dams_*.geojson; "
            "os ids não vão poder ser resolvidos (corre o pipeline de dados primeiro).")

    try:
        pages = query_database(token, database_id)
    except urllib.error.HTTPError as exc:
        log(f"[notion] erro HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}")
        raise SystemExit(1)

    index = build_index(pages, resolver)
    log(f"[notion] {len(pages)} páginas lidas; {len(index)} barragens com página.")

    if args.dry_run:
        log("[notion] --dry-run: não escreveu ficheiro.")
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Salvaguarda: não substituir um notion.json com conteúdo por um vazio.
    if not index:
        existentes = 0
        if out.exists():
            try:
                existentes = len(json.loads(out.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                existentes = 0
        if existentes:
            log(f"[notion] aviso: 0 barragens resolvidas — mantenho o "
                f"notion.json existente ({existentes}).")
            return

    with out.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2, sort_keys=True)
    log(f"[notion] escrito {out} (atualizado {datetime.now(timezone.utc).isoformat(timespec='seconds')})")


if __name__ == "__main__":
    main()
