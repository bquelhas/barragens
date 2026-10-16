# 03 — Modelo de dados

Todos os dados vivem em `data/`. O frontend lê apenas estes ficheiros: o
`manifest.json` diz **que camadas existem** (e em que ficheiros), e cada
ficheiro é um `FeatureCollection` GeoJSON normal.

## 1. `manifest.json`

Índice e metadados. É também a **memória da última extração boa** usada na
validação.

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `generated_at` | ISO-8601 (UTC) | Data/hora de geração (o site usa-a para detetar atualizações) |
| `sample` | bool | `true` se há dados de amostra |
| `sample_countries` | string[] | Países com dados de amostra |
| `source` | string | Fonte (Overpass, extract Geofabrik, amostra local) |
| `attribution` | string | `"© OpenStreetMap contributors"` |
| `license` | string | `"ODbL"` |
| `countries` | string[] | Países presentes em disco (derivado dos ficheiros) |
| `counts` | object | Nº de features por camada |
| `counts_by_country` | object | `{ "PT": { "dams": n, ... }, "ES": { ... } }` |
| `layers` | object | `{ "dams": ["dams_es.geojson", "dams_pt.geojson"], ... }` |
| `total_features` | int | Soma de `counts` |
| `notion_count` | int | Nº de barragens com página Notion (se `notion.json` existir) |

### Camadas possíveis (`layers`)

`dams`, `dam_geoms`, `reservoirs`, `weirs`, `plants`, `substations`,
`power_lines`, `conduits`, `pois`, `bairros`, `submersos`.

Cada camada pode ter:

- **um ficheiro por país** — `<camada>_<cc>.geojson` (ex. `dams_pt.geojson`); ou
- **um ficheiro único** — `<camada>.geojson` (ex. `pois.geojson`,
  `submersos.geojson`); ou
- **ambos** — usado para juntar dados curados com dados do Notion (ex.
  `submersos.geojson` + `submersos_notion.geojson`).

O sufixo de país exige **exatamente duas letras**
(`dams_pt.geojson` → `PT`), o que evita confundir sufixos como
`submersos_notion.geojson` com um código de país.

## 2. Propriedades por camada

### 2.1 `dams` (pontos)

Camada principal. Cada ponto é o ponto representativo de uma barragem.

| Propriedade | Descrição |
| --- | --- |
| `dam_id` | **ID estável** `tipo/id` (ex. `way/123456`) — chave do Notion |
| `osm_type`, `osm_id` | Tipo e id OSM da feature primária |
| `country` | `PT` / `ES` |
| `name`, `name_pt`, `name_es` | Nomes |
| `uso` | `hidroelétrica` \| `regadio` \| `abastecimento` \| `misto` \| `desconhecido` |
| `uso_fonte` | Proveniência da classificação (texto) |
| `operator` | Operador |
| `height` | Altura (m) |
| `ele` | Elevação (m) |
| `volume` | Volume/capacidade (se existir) |
| `start_date` | Ano/data de construção |
| `river` | Rio (`waterway:name`, `river`, `is_in:river`) |
| `wikidata`, `wikipedia`, `ref` | Referências externas |
| `reservoir_id` | Albufeira associada (`tipo/id`) |
| `reservoir_name` | Nome da albufeira associada |
| `reservoir_area_ha` | Área da albufeira (ha) |
| `plant_ids` | Centrais associadas (`tipo/id`[]) |
| `plant_names` | Nomes das centrais |
| `plant_power_mw` | Potência máxima das centrais (MW) |
| `members` | Features OSM agrupadas nesta barragem (`tipo/id`[]) |

> O frontend **acrescenta** ainda, em memória, `fid` (id numérico para o
> clustering/`feature-state`), `dsize` (tamanho do ícone) e `notion_*`
> (quando existe página Notion). Não são escritos pelo pipeline.

### 2.2 `dam_geoms` (linhas/polígonos)

Contorno real da barragem, ligado por `dam_id`. Propriedades:
`dam_id`, `osm_type`, `osm_id`, `country`, `name`, `uso`.
(`minzoom` 12; camada interna, segue a visibilidade de `dams`.)

### 2.3 `reservoirs` (polígonos)

| Propriedade | Descrição |
| --- | --- |
| `reservoir_id` | `tipo/id` da albufeira |
| `dam_id` | Barragem associada (ou `null`) |
| `country` | `PT` / `ES` |
| `name`, `name_pt`, `name_es` | Nomes |
| `usage`, `reservoir_type` | Tags OSM de uso |
| `area_ha` | Área (ha) |

### 2.4 Camadas simples (`weirs`, `substations`, `power_lines`, `conduits`)

Propriedades comuns: `osm_type`, `osm_id`, `country`, `name`, `operator`,
`wikidata`, `wikipedia`.

- `plants` acrescenta `power_mw` e `method` (`generator:method`/`plant:method`).

### 2.5 `pois` (pontos de interesse, curados)

| Propriedade | Descrição |
| --- | --- |
| `name`, `kind` | Nome e tipo de património |
| `descricao` | Descrição curta |
| `dam_id` | Barragem associada (opcional) |
| `notion_url` | Ligação Notion (opcional) |
| `osm` | Referência OSM (`tipo/id`) |

### 2.6 `submersos` (povoados submersos, curados) e `bairros`

Camadas de pontos, com schema curado (não vem do OSM):

| Propriedade | Descrição |
| --- | --- |
| `id` | Identificador (slug) |
| `name` | Nome do povoado/bairro |
| `barragem` | Barragem-mãe (título) |
| `dam_id` | `dam_id` da barragem-mãe (liga o ponto à ficha no mapa) |
| `rio`, `concelho`, `pais` | Localização |
| `ano` | Ano(s) |
| `confianca` | `confirmado` \| `provavel` \| `por_verificar` |
| `fonte` | Fonte histórica |
| `ressalva` | Nota de incerteza (mostrada na ficha) |

Os registos vindos do Notion (`submersos_notion.geojson`,
`bairros_notion.geojson`) seguem o mesmo espírito, com `confianca` implícita e
uma `ressalva` escrita pelo geocodificador, e trazem ainda `dam_id` — o `dam_id`
da barragem-mãe, resolvido a partir do campo **`OSM`** da página ligada (para o
cartão da barragem poder listá-los).

## 3. `notion.json`

Mapa `dam_id → metadados da página`. Vazio (`{}`) quando o Notion não está
configurado.

```json
{
  "way/123456": {
    "url": "https://<workspace>.notion.site/<slug>",
    "titulo": "Barragem de …",
    "foto_capa": "https://…",
    "resumo": "Texto curto…",
    "last_edited": "2026-01-01T00:00:00.000Z"
  }
}
```

O frontend junta estes campos aos pontos da camada `dams` (`notion_url`,
`notion_titulo`, `notion_foto`, `notion_resumo`) no carregamento.

## 4. Identificadores e chaves

| ID | Formato | Papel |
| --- | --- | --- |
| `dam_id` | `tipo/id` (`way/123`, `node/9`, `relation/5`) | Chave pública que liga o mapa ao Notion |
| `reservoir_id` | `tipo/id` | Ligação barragem ↔ albufeira |
| `osm_id` | inteiro | Id **real** do OSM (o que aparece em `openstreetmap.org`) |
| `fid` | inteiro (0…n-1) | **Só em memória** — id numérico exigido pelo MapLibre (clustering/`feature-state`) |

Regras de normalização do ID no Notion: aceita `way/123`, `way 123` e URLs
completas `https://www.openstreetmap.org/way/123` (normaliza para
`way/123`).

### Ids vindos de áreas (armadilha do `pyosmium`)

O `pyosmium` identifica as **áreas** com um id codificado: `2 × id` para malhas
fechadas (`way`) e `2 × id + 1` para relações. A extração descodifica-o
(`a.id >> 1`) antes de guardar, para que `osm_id`/`dam_id` sejam o id real do
OSM. Sem esta descodificação, as albufeiras (todas) e as barragens mapeadas
como relação tinham ids que **não existem** em `openstreetmap.org` — o link
«OSM» da ficha dava 404 e um id colado do site não encontrava a barragem.

Os valores escritos na coluna `OSM` do Notion antes de 2026-10-16 podem ter a
forma antiga (codificada). O resolvedor aceita as duas formas — ver
`06-notion.md`.

## 5. Tamanhos e orçamento

- O objetivo é manter o carregamento inicial leve. As camadas são sempre
escritas **por país** (`<camada>_<cc>.geojson`), o que já limita o tamanho de
cada ficheiro; além disso, as camadas mais pesadas têm `minzoom` no frontend e
as menos usadas ficam desligadas por defeito.
  - Nota: a constante `SPLIT_THRESHOLD_BYTES` existe em `scripts/config.py` mas
    **não está a ser usada** no código atual (a divisão por país é sempre
    feita). Serve como reserva para uma futura divisão adicional por tamanho.
- Camadas pesadas (albufeiras, rede elétrica, condutas) têm `minzoom` no
  frontend e ficam desligadas por defeito quando aplicável.
- O `PROMPT_DEEPSEEK_v2.md` descreve um plano **condicional** para converter
  camadas pesadas em PMTiles se excederem o orçamento.

## 6. Aviso de dados de amostra

Se `manifest.sample` for `true` (ou `sample_countries` não vazio), o site
mostra um **aviso amarelo** e explica que são dados de amostra. O campo
`sample_countries` permite avisos parciais (ex.: "dados de amostra para PT, os
restantes são reais").
