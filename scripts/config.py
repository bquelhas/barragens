"""
Configuração central do pipeline de dados (barragens PT + ES).

Todos os valores que se ajustam com frequência (endpoints, raios de
associação, tolerâncias de simplificação, cores, etc.) vivem aqui.
O script `build_data.py` e o `fetch_notion.py` importam este módulo,
tal como o frontend espelha parte destes valores em `js/config.js`.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SCRIPTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = SCRIPTS_DIR / "fixtures"

# Ficheiro com o resultado da última extração boa (para validação mínima).
LAST_GOOD_FILE = DATA_DIR / "manifest.json"

# ---------------------------------------------------------------------------
# Overpass API
# ---------------------------------------------------------------------------
# Vários espelhos: em caso de falha/timeout passamos para o seguinte.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

# User-Agent identificado (obrigatório pela política de uso da Overpass).
# Substitui o email/URL pelos teus antes de publicar.
USER_AGENT = (
    "barragens-pt-es/1.0 "
    "(+https://github.com/bquelhas/barragens; contacto: bquelhas@users.noreply.github.com)"
)

# Timeout do lado do servidor Overpass (segundos) e do cliente HTTP.
# Nota: algumas queries (ex.: todas as albufeiras de um país) demoram
# vários minutos, por isso o timeout do servidor é generoso. O timeout do
# cliente é o limite máximo de espera por resposta de um espelho.
OVERPASS_TIMEOUT = 900
HTTP_TIMEOUT = 600

# Retries com backoff exponencial (segundos).
MAX_RETRIES = 5
BACKOFF_BASE = 15
BACKOFF_MAX = 180

# Pausa entre pedidos para respeitar a política de uso da Overpass.
PAUSE_BETWEEN_QUERIES = 8

# ---------------------------------------------------------------------------
# Âmbito geográfico
# ---------------------------------------------------------------------------
# Países a extrair, com a seleção de área Overpass correspondente.
COUNTRIES = {
    "PT": 'area["ISO3166-1"="PT"][admin_level=2]',
    "ES": 'area["ISO3166-1"="ES"][admin_level=2]',
}

# Fallback: se a query por país der timeout, dividimos por subdivisões
# administrativas (distritos em PT, comunidades autónomas em ES).
SUBDIVISION = {
    "PT": {"admin_level": "6", "iso_prefix": "PT-"},  # distritos
    "ES": {"admin_level": "4", "iso_prefix": "ES-"},  # comunidades autónomas
}

# ---------------------------------------------------------------------------
# Queries OSM por camada
# ---------------------------------------------------------------------------
# Cada camada é descrita por filtros Overpass (sem área). A área/raio é
# acrescentado em `build_data.py`.
#
#  - camadas "base": extraídas para todo o país.
#  - camadas "infra": extraídas apenas num raio à volta das barragens
#    (evita descarregar centenas de milhares de linhas elétricas).
BASE_LAYERS = {
    "dams": [
        'nwr["waterway"="dam"]',
    ],
    "weirs": [
        'nwr["waterway"="weir"]',
    ],
    "reservoirs": [
        'nwr["natural"="water"]["water"="reservoir"]',
        'nwr["landuse"="reservoir"]',
    ],
}

INFRA_LAYERS = {
    # Centrais hidroelétricas (aceita plant:source=hydro e water por robustez).
    "plants": [
        'nwr["power"="plant"]["plant:source"~"^(hydro|water)$"]',
        'nwr["power"="generator"]["generator:source"~"^(hydro|water)$"]',
    ],
    # Subestações elétricas.
    "substations": [
        'nwr["power"="substation"]',
    ],
    # Linhas elétricas de alta tensão.
    "power_lines": [
        'way["power"="line"]',
    ],
    # Condutas, canais, descarregadores e eclusas.
    "conduits": [
        'way["man_made"="pipeline"]["substance"~"water"]',
        'way["waterway"="pressurised"]',
        'way["waterway"="canal"]',
        'nwr["waterway"="spillway"]',
        'nwr["lock"="yes"]',
    ],
}

# Raio (metros) a usar no `around` da Overpass para cada camada de infra.
INFRA_RADIUS_M = {
    "plants": 3000,
    "substations": 3000,
    "power_lines": 3000,
    "conduits": 3000,
}

# ---------------------------------------------------------------------------
# Associação espacial e classificação
# ---------------------------------------------------------------------------
# Distâncias máximas (metros) usadas nos cálculos com shapely.
RESERVOIR_NEAR_M = 200      # albufeira toca/interseta a barragem
RESERVOIR_FALLBACK_M = 200  # ou a mais próxima a <= 200 m
PLANT_NEAR_M = 2000         # central hidroelétrica associada
SUBSTATION_KEEP_M = 3000    # subestações a manter no GeoJSON
CONDUIT_KEEP_M = 3000       # condutas/canais a manter no GeoJSON
LINE_KEEP_M = 3000          # linhas elétricas a manter no GeoJSON

# Projeção métrica para os cálculos de distância/área.
METRIC_CRS = "EPSG:3035"    # ETRS89 / LAEA Europe (cobre PT + ES)

# Ordem de prioridade da classificação `uso`.
USO_VALUES = [
    "hidroelétrica",
    "regadio",
    "abastecimento",
    "misto",
    "desconhecido",
]

# ---------------------------------------------------------------------------
# Simplificação e saída
# ---------------------------------------------------------------------------
# Tolerância (metros) de simplificação Douglas-Peucker por camada.
SIMPLIFY_TOLERANCE_M = {
    "dams": 0.0,
    "weirs": 0.0,
    "reservoirs": 15.0,
    "plants": 0.0,
    "substations": 0.0,
    "power_lines": 30.0,
    "conduits": 20.0,
    "bairros": 10.0,
}

COORD_DECIMALS = 5  # arredondamento das coordenadas (~1 m)

# A partir deste tamanho (bytes) uma camada é dividida por país.
SPLIT_THRESHOLD_BYTES = 1_500_000

# ---------------------------------------------------------------------------
# Validação (o build só substitui dados bons se passar estes limites)
# ---------------------------------------------------------------------------
MIN_DAMS_RATIO = 0.8  # nova extração tem de ter >= 80% das barragens antigas

# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------
# Nome da propriedade de texto na base de dados do Notion onde se cola o ID.
NOTION_ID_PROPERTY = "ID Mapa"
# Campos de capa/resumo, por ordem de preferência.
NOTION_COVER_PROPERTY = "Foto"     # ficheiro ou URL
NOTION_SUMMARY_PROPERTY = "Resumo"
# Domínio público do Notion (usado para converter URLs internas).
NOTION_PUBLIC_DOMAIN = "notion.site"
