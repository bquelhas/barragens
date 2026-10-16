# Documentação — Águas Represadas

Documentação técnica do projeto **Águas Represadas**: mapa interativo de
barragens, albufeiras e infraestruturas associadas de **Portugal e Espanha**,
com dados do **OpenStreetMap (OSM)**, site estático publicado no **GitHub
Pages**.

Este conjunto de documentos complementa o [`README.md`](../README.md) da raiz:
o README é o guia de utilizador (como publicar, como ligar o Notion); **estes
documentos são a referência técnica** (arquitetura, pipeline de dados, modelo
de dados, frontend, automação e configuração).

## Índice

| Documento | Conteúdo |
| --- | --- |
| [01 — Arquitetura](01-arquitetura.md) | Visão geral, stack, diagrama de componentes, fluxo de dados e decisões de desenho |
| [02 — Pipeline de dados](02-pipeline-dados.md) | Scripts Python, extração Overpass vs. Geofabrik (.pbf), associação espacial, validação e escrita |
| [03 — Modelo de dados](03-modelo-dados.md) | Esquema do `manifest.json`, dos GeoJSON por camada, do `notion.json` e das chaves/IDs |
| [04 — Frontend](04-frontend.md) | `index.html`, módulos JS, camadas do mapa, interações, estado no URL e acessibilidade |
| [05 — Automação (CI)](05-automacao.md) | GitHub Actions: `data.yml`, `notion.yml`, `pages.yml` |
| [06 — Integração Notion](06-notion.md) | Base de barragens ("ID Mapa") e base de investigação "Lost Cities - BD" |
| [07 — Desenvolvimento](07-desenvolvimento.md) | Correr localmente, testar, convenções, resolução de problemas |
| [08 — Referência de configuração](08-referencia-config.md) | Todos os parâmetros de `scripts/config.py` e `js/config.js` |

## Resumo em 30 segundos

- **Frontend**: HTML + CSS + JavaScript vanilla (módulos ES), **MapLibre GL JS**
  e **maplibre-contour** via CDN, mapa base **OpenFreeMap**, curvas de nível
  geradas no browser. Sem framework, sem passo de build.
- **Dados**: ficheiros estáticos em `data/` (`*.geojson` + `manifest.json` +
  `notion.json`), gerados por um pipeline em **Python**.
- **Pipeline**: extrai do **OSM** (Overpass API **ou** extracts do Geofabrik
  `.pbf`), associa barragem ↔ albufeira ↔ central, classifica o **uso** e
  escreve GeoJSON leves.
- **Automação**: GitHub Actions regeneram os dados do OSM (semanal), atualizam
  o Notion (manual) e publicam o site (a cada `push` em `main`).
- **Ligação externa**: cada barragem tem um **ID estável** (`tipo/id`, ex.
  `way/123456`) que a liga a uma página pública do **Notion**.

## Mapa rápido do repositório

```
index.html                 Página do mapa
css/style.css              Estilos (claro/escuro, responsivo)
js/                        Frontend (módulos ES)
data/                      Dados gerados (GeoJSON + manifest + notion)
scripts/                   Pipeline Python
.github/workflows/         Automação (dados, Notion, publicação)
docs/                      Esta documentação
```

> **Nota sobre a licença dos dados:** os dados derivam do OpenStreetMap e estão
> sob **ODbL**; a atribuição **© OpenStreetMap contributors** é obrigatória e
> está presente no frontend (controlo de atribuição do MapLibre) e no manifest.
