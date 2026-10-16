# 08 — Referência de configuração

A configuração está centralizada em dois ficheiros que se **espelham**:

- `scripts/config.py` — pipeline Python.
- `js/config.js` — frontend.

## 1. `scripts/config.py`

### Caminhos

| Nome | Valor | Descrição |
| --- | --- | --- |
| `ROOT` | raiz do repositório | `Path` do projeto |
| `DATA_DIR` | `ROOT / "data"` | Onde se escrevem os dados |
| `SCRIPTS_DIR` | `scripts/` | Pasta dos scripts |
| `FIXTURES_DIR` | `scripts/fixtures` | Amostra offline |
| `LAST_GOOD_FILE` | `data/manifest.json` | Memória da última extração boa |

### Overpass

| Nome | Predefinição | Descrição |
| --- | --- | --- |
| `OVERPASS_ENDPOINTS` | 4 espelhos | Rodam por ordem aleatória |
| `USER_AGENT` | identificado | **Muda para o teu contacto antes de publicar** |
| `OVERPASS_TIMEOUT` | `900` s | Timeout do servidor Overpass |
| `HTTP_TIMEOUT` | `600` s | Timeout do cliente HTTP |
| `MAX_RETRIES` | `5` | Tentativas por query |
| `BACKOFF_BASE` | `15` s | Base do backoff exponencial |
| `BACKOFF_MAX` | `180` s | Teto do backoff |
| `PAUSE_BETWEEN_QUERIES` | `8` s | Pausa entre pedidos (política de uso) |

### Âmbito geográfico

| Nome | Descrição |
| --- | --- |
| `COUNTRIES` | `PT`/`ES` → expressão de área Overpass (`ISO3166-1`, `admin_level=2`) |
| `SUBDIVISION` | Fallback por divisões (PT `admin_level=6`, ES `admin_level=4`) |

### Camadas e raios

| Nome | Descrição |
| --- | --- |
| `BASE_LAYERS` | Query Overpass por camada base (dams, weirs, reservoirs) |
| `INFRA_LAYERS` | Query por camada de infraestrutura (plants, substations, power_lines, conduits) |
| `INFRA_RADIUS_M` | Raio do `around` por camada de infra (todos `3000` m) |

### Associação e classificação

| Nome | Valor | Descrição |
| --- | --- | --- |
| `RESERVOIR_NEAR_M` | `200` | Barragem "toca" a albufeira |
| `RESERVOIR_FALLBACK_M` | `200` | Albufeira mais próxima aceitável |
| `PLANT_NEAR_M` | `2000` | Central associada |
| `SUBSTATION_KEEP_M` | `3000` | Subestações a manter |
| `CONDUIT_KEEP_M` | `3000` | Condutas a manter |
| `LINE_KEEP_M` | `3000` | Linhas elétricas a manter |
| `METRIC_CRS` | `EPSG:3035` | Projeção métrica (ETRS89/LAEA Europe) |
| `USO_VALUES` | lista | Ordem dos valores de `uso` |

### POIs (camada curada)

| Nome | Descrição |
| --- | --- |
| `POIS` | Lista curada (`osm`, `name`, `kind`, `descricao`, `dam_id`, `notion_url`) |
| `POI_SIMPLIFY_M` | `1.5` — tolerância de simplificação dos POIs |

### Simplificação e saída

| Nome | Valor | Descrição |
| --- | --- | --- |
| `SIMPLIFY_TOLERANCE_M` | por camada | Douglas–Peucker (m): dams 0, dam_geoms 2, reservoirs 20, power_lines 40, conduits 30, bairros 10 |
| `MIN_RESERVOIR_AREA_HA` | `5.0` | Área mínima de albufeira (se não ligada a barragem) |
| `MIN_DAM_SIZE_M` | `15.0` | Tamanho mínimo de barragem sem nome/álveo/central |
| `COORD_DECIMALS` | `5` | Casas decimais das coordenadas (~1 m) |
| `MIN_AREA_M2` | `1.0` | Descarta polígonos degenerados |
| `MIN_LEN_M` | `1.0` | Descarta linhas degeneradas |
| `SPLIT_THRESHOLD_BYTES` | `1_500_000` | **Não usado atualmente** — reservado para futura divisão por tamanho (a escrita já é sempre por país) |

### Validação

| Nome | Valor | Descrição |
| --- | --- | --- |
| `MIN_DAMS_RATIO` | `0.8` | Nova extração ≥ 80 % das barragens anteriores |

### Notion

| Nome | Valor | Descrição |
| --- | --- | --- |
| `NOTION_ID_PROPERTY` | `"ID Mapa"` | Propriedade de texto com o `dam_id` |
| `NOTION_COVER_PROPERTY` | `"Foto"` | Propriedade da capa |
| `NOTION_SUMMARY_PROPERTY` | `"Resumo"` | Propriedade do resumo |
| `NOTION_PUBLIC_DOMAIN` | `"notion.site"` | Domínio para converter URLs internas |

> O `build_data.py` define ainda `LAYER_KEYS` (camadas que o manifest pode
> anunciar) e `CURRENT_COUNTRIES` (países da execução atual).

## 2. `js/config.js`

### Identidade

| Nome | Descrição |
| --- | --- |
| `PROJECT` | `name`, `subtitle` |

### Mapa

| Nome | Predefinição | Descrição |
| --- | --- | --- |
| `MAP.center` | `[-4.2, 40.0]` | Centro (Península Ibérica) |
| `MAP.zoom` | `5.2` | Zoom inicial |
| `MAP.minZoom` / `maxZoom` | `3` / `18` | Limites |
| `MAP.styles.light` / `dark` | OpenFreeMap | Estilos do mapa base |
| `MAP.attribution` | OSM | Atribuição obrigatória |

### Paleta e cores

| Nome | Descrição |
| --- | --- |
| `PALETTE` | `water`, `waterOutline`, `waterSelected`, `related`, `notion`, `poi`, `submerged`, `cluster` |
| `USO_COLORS` / `USO_LABELS` / `USO_ORDER` | Cores, rótulos e ordem dos usos |
| `CONFIANCA_COLORS` / `CONFIANCA_LABELS` / `CONFIANCA_ORDER` | Grau de confiança dos povoados submersos |
| `HIGHLIGHT`, `NOTION_COLOR` | Cores de destaque |

### Camadas

`LAYERS` — lista de camadas com:

| Campo | Descrição |
| --- | --- |
| `key` | Identificador (igual ao do manifest) |
| `label` | Rótulo na UI |
| `kind` | `dams` \| `point` \| `line` \| `polygon` \| `outline` \| `poi` \| `curated` |
| `minzoom` | Zoom mínimo de visibilidade |
| `default` | Visível ao arrancar? |
| `color` | Cor base |
| `legendSwatch` | Forma na legenda (`circle`/`line`/`polygon`) |
| `internal` | (`true` para `dam_geoms`) segue a visibilidade de `dams` |
| `primary` | (`true` para `dams`) camada principal |

### Outros

| Nome | Descrição |
| --- | --- |
| `DAM_ICON` | `size` (px), `minSize`, `maxSize` — dimensionamento do ícone |
| `RELATED` | `line` (300 m), `sub` (400 m), `dim` (0.16) — destaque da rede |
| `HILLSHADE` | `enabled`, `tiles`, `encoding`, `tileSize`, `maxzoom`, `exaggeration`, `attribution` |
| `FEATURED` | Destaques do ecrã de boas-vindas (por `name` ou `id`) |
| `DATA` | `manifest`, `notion` (caminhos) |
| `CLUSTER` | `enabled` (`false`), `radius`, `maxZoom` |
| `STORAGE` | Chaves de `localStorage` (`theme`, `welcome`) |

## 3. O que se espelha entre os dois

Alguns valores existem em ambos os ficheiros e devem ser mantidos coerentes:

- **Intervalos de associação** (raios) influenciam que features existem;
  o frontend assume que já vêm resolvidas nos dados.
- **Cores e rótulos de `uso`** são definidos no frontend (`USO_COLORS`), mas a
  *ordem* dos valores espelha `USO_VALUES` do backend.
- **Limiares** (área mínima de albufeira, tamanho mínimo de barragem) são do
  backend; o frontend não os repete.
