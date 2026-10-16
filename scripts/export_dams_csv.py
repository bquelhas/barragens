"""
Gera a lista de barragens em CSV, para servir de fonte a um dropdown no Notion.

Objetivo: teres, no Notion, uma lista de barragens de onde **escolhes** (sem
adivinhar) a que corresponde cada página da tua tabela. O valor que interessa
é o `ID OSM` (`way/…`), que é o que liga a página à barragem no mapa.

Não acede à rede nem escreve no Notion: lê apenas `data/dams_*.geojson`.

Uso:
    python scripts/export_dams_csv.py                    # só barragens com nome
    python scripts/export_dams_csv.py --all              # inclui as sem nome
    python scripts/export_dams_csv.py --out lista.csv    # outro caminho
    python scripts/export_dams_csv.py --sep ';'          # outro separador
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402

# Cabeçalho do CSV. A primeira coluna é o "Nome" (vira o título na importação).
COLUNAS = ["Nome", "ID OSM", "Pais", "Rio", "Uso", "Altura (m)", "Altitude (m)",
           "Latitude", "Longitude"]

DEFAULT_OUT = config.ROOT / "exports" / "barragens_osm.csv"


def _best_name(p: dict) -> str:
    for key in ("name", "name_pt", "name_es"):
        val = p.get(key)
        if val:
            return str(val).strip()
    return ""


def _sort_key(texto: str) -> str:
    """Minúsculas sem acentos, para ordenar de forma natural em português."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto)
                   if not unicodedata.combining(c)).lower()


def load_rows(include_unnamed: bool) -> list[list]:
    rows = []
    paths = sorted(glob.glob(str(config.DATA_DIR / "dams_*.geojson"))) + \
        sorted(glob.glob(str(config.DATA_DIR / "dams.geojson")))
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                features = json.load(fh).get("features", [])
        except Exception as exc:  # noqa: BLE001
            print(f"[aviso] não consegui ler {path}: {exc}", file=sys.stderr)
            continue
        for f in features:
            p = f.get("properties") or {}
            dam_id = p.get("dam_id")
            if not dam_id:
                continue
            nome = _best_name(p)
            if not nome and not include_unnamed:
                continue
            if not nome:
                nome = f"(sem nome) {dam_id}"
            coord = (f.get("geometry") or {}).get("coordinates") or [None, None]
            lon = coord[0] if len(coord) > 0 else None
            lat = coord[1] if len(coord) > 1 else None
            rows.append([
                nome,
                dam_id,
                p.get("country") or "",
                p.get("river") or "",
                p.get("uso") or "",
                p.get("height") if p.get("height") is not None else "",
                p.get("ele") if p.get("ele") is not None else "",
                lat if lat is not None else "",
                lon if lon is not None else "",
            ])
    # Ordena por país e depois por nome.
    rows.sort(key=lambda r: (_sort_key(str(r[2])), _sort_key(str(r[0]))))
    return rows


def main():
    ap = argparse.ArgumentParser(
        description="Exporta a lista de barragens (CSV) para usar como dropdown no Notion.")
    ap.add_argument("--all", action="store_true",
                    help="inclui barragens sem nome")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"ficheiro de saída (por omissão {DEFAULT_OUT})")
    ap.add_argument("--sep", default=",", help="separador (por omissão vírgula)")
    args = ap.parse_args()

    rows = load_rows(args.all)
    if not rows:
        print("[lista] sem barragens para exportar (data/dams_*.geojson vazio?)")
        return

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=args.sep)
        writer.writerow(COLUNAS)
        writer.writerows(rows)

    print(f"[lista] {len(rows)} barragens -> {out}")
    print("[lista] importa este CSV no Notion como uma base nova "
          "(ex.: 'Barragens OSM') e usa-a como fonte do dropdown.")


if __name__ == "__main__":
    main()
