"""
Ligação **barragem ↔ albufeira pelo nome**.

Partilhado entre o pipeline (`build_data.associate`) e o script de reparação
`fix_reservoir_links.py`.

Numa cascata (Douro, Tejo…), uma barragem *toca* duas albufeiras: a que represa
(a montante) e o início da de jusante. A associação geométrica escolhe às vezes a
errada, e a ficha passa a mostrar o nome da vizinha (ex.: «Barragem de Picote →
Albufeira de Bemposta»), a albufeira abre a barragem errada e o id de uma
albufeira colado no Notion resolve para a barragem vizinha.

Regra: **se existe uma albufeira cujo nome corresponde ao da barragem, é essa
que fica ligada.** Obras secundárias (descarregadores, diques, tomadas) não têm
albufeira com o seu nome, por isso mantêm a escolha geométrica.
"""

from __future__ import annotations

import re
import unicodedata

# Prefixos de tipo: «Barragem de X» e «Albufeira de X» têm de dar a mesma chave.
# Ordenados do mais longo para o mais curto, para o corte ser o mais específico.
_PREFIXES = tuple(sorted((
    "barragem de ", "barragem da ", "barragem do ", "barragem ",
    "presa de ", "presa del ", "presa da ", "presa ",
    "salto de ", "salto del ", "salto ",
    "embalse de ", "embalse del ", "embalse ",
    "albufeira de ", "albufeira da ", "albufeira do ", "albufeira ",
    "encoro de ", "encoro da ", "encoro do ", "encoro ",
    "acude de ", "acude del ", "acude da ", "acude ",
    "azude de ", "azude da ", "azude ",
    "panta de ", "panta del ", "panta ",
    "pantano de ", "pantano del ", "pantano ",
    "dique de ", "dique del ", "dique da ", "dique ",
    "reservatorio de ", "reservatorio ",
    "represa de ", "represa del ", "represa ",
    "central hidroelectrica de ", "central hidroelectrica do ", "central hidroelectrica ",
    "central hidroeletrica de ", "central hidroeletrica do ", "central hidroeletrica ",
    "aproveitamento hidroelectrico de ", "aproveitamento hidroelectrico do ",
    "aproveitamento hidroelectrico ",
    "aproveitamento hidroeletrico de ", "aproveitamento hidroeletrico do ",
    "aproveitamento hidroeletrico ",
    "aproveitamento de ", "aproveitamento do ", "aproveitamento ",
    "barrage de ", "barrage ",
), key=len, reverse=True))

# Nomes que não distinguem nada (só o tipo): não servem para casar.
_GENERIC = frozenset({
    "barragem", "barragens", "presa", "presas", "salto", "embalse", "albufeira",
    "albufeiras", "encoro", "acude", "azude", "panta", "pantano", "dique",
    "reservatorio", "represa", "barrage", "lago", "lagoa",
})


def name_key(name: str | None) -> str:
    """Chave de comparação de nomes: sem acentos nem maiúsculas, pontuação → espaço
    e sem o prefixo de tipo, para que «Barragem de Picote», «Albufeira de Picote»,
    «Barragem do Alto Rabagão» e «Alto-Rabagão» se possam comparar.

    Devolve `""` quando o nome não distingue nada: vazio, só um prefixo de tipo
    («Barragem», «Embalse») ou demasiado curto."""
    text = unicodedata.normalize("NFD", name or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn").lower()
    text = re.sub(r"[^\w]+", " ", text).strip()
    if text in _GENERIC:
        return ""
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.strip()
    return "" if text in _GENERIC or len(text) < 3 else text


def name_index(pairs) -> dict[str, str]:
    """Índice `chave → id` a partir de pares `(id, nome_ou_lista_de_nomes)`.

    Em caso de chave repetida fica o primeiro (a ordem de entrada manda)."""
    index: dict[str, str] = {}
    for ident, names in pairs:
        if isinstance(names, str) or names is None:
            names = [names]
        for name in names:
            key = name_key(name)
            if key and key not in index:
                index[key] = ident
    return index


def match_by_name(names, index: dict[str, str]) -> str | None:
    """Id do índice cujo nome corresponde a algum de `names` (por prioridade)."""
    for name in names or []:
        key = name_key(name)
        if key and key in index:
            return index[key]
    return None


def first_key(names) -> str:
    """Primeira chave não vazia de uma lista de nomes."""
    for name in names or []:
        key = name_key(name)
        if key:
            return key
    return ""


def resolve(dams, reservoirs):
    """Aplica a regra. **São precisas listas** (percorridas mais de uma vez).

    `dams`: `(dam_id, [nomes], reservoir_id_atual, reservoir_name_atual)`
    `reservoirs`: `(reservoir_id, [nomes], dam_id_atual)`

    Devolve `(relink, owner)`:
      - `relink`: `{dam_id: reservoir_id}` — só as ligações a corrigir;
      - `owner`: `{reservoir_id: dam_id}` — o sentido inverso, preferindo a
        barragem cujo nome corresponde ao da albufeira; sem correspondência,
        mantém o dono actual (só muda com razão de nome).
    """
    res_index = name_index((rid, names) for rid, names, _cur in reservoirs)
    dam_index = name_index((did, names) for did, names, _rid, _rn in dams)

    relink: dict[str, str] = {}
    for did, names, rid, rname in dams:
        dam_key = first_key(names)
        if not dam_key:
            continue
        cur_key = name_key(rname)
        owner_by_name = dam_index.get(cur_key) if cur_key else None
        # Só se a albufeira ligada pertencer (pelo nome) a OUTRA barragem.
        suspicious = bool(cur_key) and cur_key != dam_key and owner_by_name not in (None, did)
        if rid is not None and not suspicious:
            continue
        target = res_index.get(dam_key)
        if target and target != rid:
            relink[did] = target

    claims: dict[str, list] = {}
    for did, names, rid, _rn in dams:
        target = relink.get(did, rid)
        if target:
            claims.setdefault(target, []).append((did, names))

    owner: dict[str, str] = {}
    for rid, names, current in reservoirs:
        rkey = first_key(names)
        candidates = claims.get(rid) or []
        if not candidates:
            continue
        chosen = None
        for cdid, cnames in candidates:
            if rkey and first_key(cnames) == rkey:
                chosen = cdid
                break
        if chosen is None:
            ids = [c[0] for c in candidates]
            chosen = current if current in ids else min(ids)
        owner[rid] = chosen
    return relink, owner
