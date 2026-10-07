"""
Cliente Overpass minimalista.

Responsabilidades:
  * Enviar uma query Overpass (QL) com retries e backoff exponencial.
  * Rodar por vários espelhos quando um falha ou dá timeout.
  * Descobrir subdivisões administrativas (distritos/comunidades) para
    usar como fallback quando a query por país inteiro dá timeout.
  * Respeitar a política de uso: User-Agent identificado e pausas.

Não conhece o domínio do projeto (barragens); é genérico de propósito.
"""

from __future__ import annotations

import json
import random
import sys
import time
import urllib.parse
import urllib.request

import config


class OverpassError(RuntimeError):
    """Erro recuperável ou fatal ao falar com a Overpass."""


def _http_post(endpoint: str, query: str) -> str:
    """Faz um POST form-urlencoded à Overpass e devolve o corpo em texto."""
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _looks_like_error(body: str) -> str | None:
    """Deteta erros da Overpass devolvidos com HTTP 200."""
    low = body.lower()
    if "<html" in low or "error" in low[:2000]:
        # Extrai uma mensagem curta, se existir.
        for marker in ("Error</strong>:", "error:"):
            idx = body.find(marker)
            if idx != -1:
                return body[idx : idx + 300].strip()
        return body[:200].strip()
    return None


def overpass_query(query: str, logger=print, context: str = "") -> dict:
    """
    Executa uma query Overpass e devolve o JSON já desserializado.

    Roda pelos espelhos configurados, com backoff exponencial. Se todos
    falharem, levanta `OverpassError`.
    """
    endpoints = list(config.OVERPASS_ENDPOINTS)
    random.shuffle(endpoints)  # evita bater sempre no mesmo espelho

    last_error: str | None = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        for endpoint in endpoints:
            try:
                if context:
                    logger(f"[overpass] {context} -> {endpoint} "
                           f"(tentativa {attempt})")
                body = _http_post(endpoint, query)
                err = _looks_like_error(body)
                if err:
                    last_error = err
                    logger(f"[overpass] resposta com erro: {err[:160]}")
                    continue
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError as exc:
                    last_error = f"JSON inválido: {exc}"
                    logger(f"[overpass] {last_error}")
                    continue
                return parsed
            except Exception as exc:  # noqa: BLE001 - queremos robustez
                last_error = f"{type(exc).__name__}: {exc}"
                logger(f"[overpass] falha em {endpoint}: {last_error}")
                continue

        # Backoff antes de tentar novamente (com jitter).
        if attempt < config.MAX_RETRIES:
            delay = min(config.BACKOFF_BASE * (2 ** (attempt - 1)),
                        config.BACKOFF_MAX)
            delay += random.uniform(0, 5)
            logger(f"[overpass] a aguardar {delay:.0f}s antes de repetir...")
            time.sleep(delay)

    raise OverpassError(
        f"Todas as tentativas falharam para {context or 'query'}: {last_error}"
    )


def pause():
    """Pausa educada entre pedidos (política de uso da Overpass)."""
    time.sleep(config.PAUSE_BETWEEN_QUERIES)


def discover_subareas(country: str, logger=print) -> list[dict]:
    """
    Descobre subdivisões administrativas de um país.

    Devolve uma lista de {"name": ..., "area": "<expressão Overpass>"} que
    pode ser usada para dividir uma extração que dê timeout.
    """
    spec = config.SUBDIVISION.get(country)
    if not spec:
        return []

    query = (
        f"[out:json][timeout:120];"
        f'area["ISO3166-1"="{country}"][admin_level=2]->.c;'
        f'relation(area.c)["boundary"="administrative"]'
        f'["admin_level"="{spec["admin_level"]}"];'
        f"out ids tags;"
    )
    data = overpass_query(query, logger, context=f"descobrir subáreas {country}")

    areas = []
    for el in data.get("elements", []):
        if el.get("type") != "relation":
            continue
        osm_id = el["id"]
        name = (el.get("tags") or {}).get("name", str(osm_id))
        # area(3600000000 + id) seleciona a área de uma relação.
        area_expr = f"area(3600000000 + {osm_id})"
        areas.append({"name": name, "area": area_expr, "id": osm_id})
    logger(f"[overpass] {country}: {len(areas)} subáreas descobertas")
    return areas


def overpass_area_by_iso(iso_code: str) -> str:
    """Devolve a expressão de área para um código ISO3166-2 (ex.: PT-11)."""
    return f'area["ISO3166-2"="{iso_code}"]'


if __name__ == "__main__":  # teste rápido manual
    q = '[out:json][timeout:60];node["waterway"="dam"](38.7,-9.3,38.8,-9.2);out count;'
    print(json.dumps(overpass_query(q, context="teste"), indent=2)[:500])
    sys.exit(0)
