"""
Repara a ligação **barragem ↔ albufeira** nos ficheiros já gerados
(`data/dams_*.geojson`, `data/reservoirs_*.geojson`).

Numa cascata, a associação geométrica liga por vezes a barragem à albufeira da
vizinha (ex.: «Barragem de Picote → Albufeira de Bemposta»). Aqui aplica-se a
regra de `reservoir_links.py`: fica ligada a albufeira **cujo nome corresponde ao
da barragem**, e só quando a ligação actual aponta, pelo nome, para outra
barragem. Obras secundárias (descarregadores, diques, tomadas), que não têm
albufeira com o seu nome, mantêm a escolha geométrica.

Corre em ensaio por omissão; `--apply` escreve. Não muda geometria nem contagens —
só `reservoir_id`/`reservoir_name`/`reservoir_area_ha` (barragens) e `dam_id`
(albufeiras).

Uso:
    python scripts/fix_reservoir_links.py            # ensaio
    python scripts/fix_reservoir_links.py --apply    # escreve
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import reservoir_links as rl  # noqa: E402

LAYERS = ("dams", "reservoirs")
COUNTRIES = ("pt", "es")


def load(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return json.load(fh).get("features", [])


def save(path, features):
    fc = {"type": "FeatureCollection", "features": features}
    with path.open("w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False, separators=(",", ":"))


def names_of(p: dict):
    return [p.get("name"), p.get("name_pt"), p.get("name_es")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="escreve os ficheiros")
    args = ap.parse_args()

    files = {(layer, cc): config.DATA_DIR / f"{layer}_{cc}.geojson"
             for layer in LAYERS for cc in COUNTRIES}
    dams = {k: load(v) for k, v in files.items() if k[0] == "dams"}
    reservoirs = {k: load(v) for k, v in files.items() if k[0] == "reservoirs"}

    # Índices id -> [(ficheiro, propriedades), ...] de **todas** as cópias (PT/ES).
    # Uma barragem de fronteira existe nos dois ficheiros e as duas têm de ficar
    # iguais, senão quem lê os dois (ex.: o resolvedor do Notion) vê a última.
    def index_props(store, id_field):
        out: dict[str, list[tuple[tuple, dict]]] = {}
        for key, feats in store.items():
            for f in feats:
                p = f.get("properties") or {}
                if p.get(id_field):
                    out.setdefault(p[id_field], []).append((key, p))
        return out

    dam_props = index_props(dams, "dam_id")
    res_props = index_props(reservoirs, "reservoir_id")

    dam_rows = [(did, names_of(copies[0][1]), copies[0][1].get("reservoir_id"),
                 copies[0][1].get("reservoir_name"))
                for did, copies in dam_props.items()]
    res_rows = [(rid, names_of(copies[0][1]), copies[0][1].get("dam_id"))
                for rid, copies in res_props.items()]
    relink, owner = rl.resolve(dam_rows, res_rows)

    changed: set[tuple] = set()
    mudados = []
    for did, target in relink.items():
        rp = res_props[target][0][1]
        mudados.append((did, dam_props[did][0][1].get("name"),
                        dam_props[did][0][1].get("reservoir_name"), rp.get("name")))
        for key, p in dam_props[did]:
            p["reservoir_id"] = target
            p["reservoir_name"] = rp.get("name")
            p["reservoir_area_ha"] = rp.get("area_ha")
            changed.add(key)

    reversos = []
    for rid, new_owner in owner.items():
        old = res_props[rid][0][1].get("dam_id")
        if old != new_owner:
            reversos.append((rid, res_props[rid][0][1].get("name"), old, new_owner))
        for key, p in res_props[rid]:
            if p.get("dam_id") != new_owner:
                p["dam_id"] = new_owner
                changed.add(key)

    print(f"[ligações] {len(mudados)} barragens re-ligadas, {len(reversos)} albufeiras com sentido inverso corrigido")
    for did, dn, old, new in mudados:
        print(f"  barragem {did} '{dn}': albufeira '{old}' -> '{new}'")
    for rid, rn, old, new in reversos[:60]:
        print(f"  albufeira {rid} '{rn}': dam_id {old} -> {new}")
    if len(reversos) > 60:
        print(f"  ... e mais {len(reversos) - 60} albufeiras")

    # Salvaguarda: nenhuma albufeira relevante pode ficar sem barragem.
    min_area = getattr(config, "MIN_RESERVOIR_AREA_HA", 5.0)
    soltas = [(rid, copies[0][1].get("name"), copies[0][1].get("area_ha"))
              for rid, copies in res_props.items()
              if not copies[0][1].get("dam_id") and (copies[0][1].get("area_ha") or 0) >= min_area]
    print(f"[ligações] albufeiras >= {min_area} ha sem barragem: {len(soltas)}")

    if not args.apply:
        print("[ligações] ensaio (nada escrito). Usa --apply.")
        return 0
    if not changed:
        print("[ligações] nada a corrigir.")
        return 0

    for key in sorted(changed):
        feats = (dams if key[0] == "dams" else reservoirs)[key]
        save(files[key], feats)
        print(f"[ligações] escrito {files[key].name} ({len(feats)} feições)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
