"""
Liga as barragens às páginas do Notion.

Lê uma base de dados pública do Notion através da API oficial e gera
`data/notion.json` no formato:

    { "way/123456": { "url": "...", "titulo": "...",
                      "foto_capa": "...", "resumo": "..." }, ... }

Variáveis de ambiente:
    NOTION_TOKEN         token da integração (GitHub Secret)
    NOTION_DATABASE_ID   id da base de dados de barragens
    NOTION_PUBLIC_DOMAIN domínio público do Notion (opcional, p/ URL pública)

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
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402

API_URL = "https://api.notion.com/v1/databases/{db}/query"
NOTION_VERSION = "2022-06-28"

# Aceita "way/123", "way 123", URL do OSM completa, e "relation/1".
ID_RE = re.compile(r"(node|way|relation)\s*[/ ]\s*(\d+)", re.IGNORECASE)
OSM_URL_RE = re.compile(
    r"openstreetmap\.org/(node|way|relation)/(\d+)", re.IGNORECASE)


def log(msg: str):
    print(msg, flush=True)


def normalize_dam_id(raw: str | None) -> str | None:
    """
    Normaliza um valor colado pelo utilizador para o formato `tipo/id`.

    Aceita `way/123456`, `way 123456` e
    `https://www.openstreetmap.org/way/123456`.
    """
    if not raw:
        return None
    text = raw.strip()
    m = OSM_URL_RE.search(text)
    if not m:
        m = ID_RE.search(text)
    if not m:
        return None
    return f"{m.group(1).lower()}/{m.group(2)}"


def rich_text(prop: dict | None) -> str:
    """Extrai o texto simples de uma propriedade rich_text/title."""
    if not prop:
        return ""
    parts = prop.get("rich_text") or prop.get("title") or []
    return "".join(p.get("plain_text", "") for p in parts).strip()


def extract_cover(page: dict) -> str | None:
    """
    Devolve o URL da capa.

    Aviso: capas carregadas para o Notion geram URLs que expiram (~1h).
    Nestes casos o site deve preferir capas externas; guardamos na mesma o
    URL e registamos a limitação no log.
    """
    cover = page.get("cover")
    if not cover:
        return None
    kind = cover.get("type")
    data = cover.get(kind, {}) if kind else {}
    return data.get("url")


def public_url(page: dict) -> str:
    """URL público da página (usa `public_url` se a página estiver publicada)."""
    if page.get("public_url"):
        return page["public_url"]
    domain = os.environ.get("NOTION_PUBLIC_DOMAIN") or config.NOTION_PUBLIC_DOMAIN
    url = page.get("url", "")
    # https://www.notion.so/<slug>-<id> -> https://<workspace>.<domain>/...
    if domain and "notion.so" in url:
        return url.replace("www.notion.so", f"www.{domain}")
    return url


def query_database(token: str, database_id: str) -> list[dict]:
    """Percorre toda a base de dados (paginada)."""
    pages: list[dict] = []
    cursor: str | None = None
    while True:
        body = {"page_size": 100}
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


def build_index(pages: list[dict]) -> dict:
    """Constrói o índice dam_id -> metadados, validando IDs."""
    index: dict[str, dict] = {}
    invalid: list[str] = []
    duplicates: list[str] = []

    for page in pages:
        props = page.get("properties", {})
        raw_id = rich_text(props.get(config.NOTION_ID_PROPERTY))
        dam_id = normalize_dam_id(raw_id)
        if not dam_id:
            invalid.append(raw_id or f"<página sem '{config.NOTION_ID_PROPERTY}'>")
            continue
        if dam_id in index:
            duplicates.append(dam_id)
            continue

        title = ""
        for prop in props.values():
            if prop.get("type") == "title":
                title = rich_text(prop)
                break

        index[dam_id] = {
            "url": public_url(page),
            "titulo": title,
            "foto_capa": extract_cover(page),
            "resumo": rich_text(props.get(config.NOTION_SUMMARY_PROPERTY)),
            "last_edited": page.get("last_edited_time"),
        }

    if invalid:
        log(f"[notion] {len(invalid)} página(s) com ID inválido/ausente: {invalid[:20]}")
    if duplicates:
        log(f"[notion] {len(duplicates)} ID(s) duplicado(s): {duplicates[:20]}")
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

    try:
        pages = query_database(token, database_id)
    except urllib.error.HTTPError as exc:
        log(f"[notion] erro HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}")
        raise SystemExit(1)

    index = build_index(pages)
    log(f"[notion] {len(index)} barragens com página Notion.")

    if args.dry_run:
        log("[notion] --dry-run: não escreveu ficheiro.")
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2, sort_keys=True)
    log(f"[notion] escrito {out} (atualizado {datetime.now(timezone.utc).isoformat(timespec='seconds')})")


if __name__ == "__main__":
    main()
