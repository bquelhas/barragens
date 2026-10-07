# Prompt para o DeepSeek — Mapa de Barragens PT + ES

---

És um programador sénior de SIG/web. Cria um projeto completo, pronto a publicar no **GitHub Pages**, que é um **mapa interativo de barragens de Portugal e Espanha**, das suas **albufeiras** e das **infraestruturas adjacentes**, com dados do **OpenStreetMap**. Cada barragem deve poder ligar-se a uma página pública no **Notion** com fotos e mais informação.

Entrega todos os ficheiros com o conteúdo completo (sem "..." nem "resto igual"), mais um README em português com instruções passo a passo para alguém **sem experiência técnica**.

## 1. Arquitetura (obrigatória)

- **Site estático** (HTML + CSS + JavaScript vanilla, módulos ES), sem framework e sem passo de build no frontend.
- Mapa com **MapLibre GL JS** (via CDN). Mapa base gratuito e sem chave (ex.: OpenFreeMap ou tiles raster OSM, com atribuição correta "© OpenStreetMap contributors").
- **Pipeline de dados em Python** (`scripts/`) que corre:
  - localmente (`python scripts/build_data.py`), e
  - numa **GitHub Action** agendada (semanal + botão manual `workflow_dispatch`) que regenera os dados e faz commit em `data/`.
- O site lê apenas ficheiros estáticos em `data/` (GeoJSON simplificado / leve). Nada de chamadas à Overpass a partir do browser.
- Deploy no GitHub Pages através de GitHub Action.

Estrutura sugerida:
```
/index.html
/css/style.css
/js/main.js, js/layers.js, js/panel.js, js/search.js
/data/*.geojson, data/notion.json
/scripts/build_data.py, scripts/fetch_notion.py, requirements.txt
/.github/workflows/data.yml, pages.yml
/README.md
```

## 2. Dados OSM a extrair (Overpass API)

Área: Portugal continental + ilhas e Espanha (incluindo Baleares e Canárias). Usar as áreas administrativas (`area["ISO3166-1"="PT"]`, `area["ISO3166-1"="ES"]`) e, se der timeout, dividir por regiões/distritos/comunidades autónomas e juntar. Usar `out geom;` / `out center;` conforme necessário, timeouts generosos, retries com backoff, e respeitar a política de uso da Overpass (User-Agent identificado, pausas entre pedidos).

Camadas (cada uma num GeoJSON próprio, cada feature com `osm_type`, `osm_id`, `name`, `name:pt`/`name:es` se existirem, e as tags relevantes):

1. **Barragens** — `waterway=dam` (ways lineares, áreas e nodes). Converter nodes/áreas também para um **ponto representativo** para a camada de marcadores.
2. **Açudes** — `waterway=weir` (camada separada, desligada por defeito, aparece só com zoom alto).
3. **Albufeiras** — `natural=water` + `water=reservoir` (ways e multipolygon relations), e também `landuse=reservoir` (tagging antigo). Montar corretamente multipolígonos de relações.
4. **Centrais hidroelétricas** — `power=plant` + `plant:source=hydro`, e `power=generator` + `generator:source=hydro` (incluir `generator:method` p.ex. `water-storage`, `water-pumped-storage`, `run-of-the-river` e `plant:output:electricity`).
   - Nota: no OSM a tag correta é `plant:source=hydro` (não `water`), mas aceitar ambas por robustez.
5. **Subestações** — `power=substation` a ≤ 3 km de uma barragem.
6. **Linhas elétricas** — `power=line` que toquem numa central/subestação associada (ou num raio de 3 km); simplificar geometria.
7. **Condutas e canais** — `man_made=pipeline` com `substance=water`, `waterway=pressurised`, `waterway=canal`, e descarregadores (`waterway=spillway` se existir; também `spillway=*`), eclusas (`lock=yes`), num raio de ~3 km da barragem.

## 3. Ligação espacial e classificação (no script Python)

Usar `shapely` (e opcionalmente `geopandas`) com projeção métrica (EPSG:3035 ou 3763/25830) para cálculos de distância.

Para cada barragem calcular:
- `reservoir_id` — albufeira que a barragem toca/interseta (ou mais próxima a ≤ 200 m).
- `plant_ids` — centrais hidroelétricas a ≤ 1–2 km (configurável).
- **`uso`** (classificação), por esta ordem:
  - `hidroelétrica` se houver central/gerador hydro associado, ou se a albufeira tiver `usage=hydro`/`usage=power`;
  - `regadio` se a albufeira tiver `usage=irrigation` ou `reservoir_type=irrigation`;
  - `abastecimento` se `usage=water_supply`/`drinking_water`;
  - `misto` se vários; `desconhecido` caso contrário.
  - Guardar também `uso_fonte` (de onde veio a classificação) para transparência.
- Agregar atributos úteis das tags: `height`, `ele`, `operator`, `start_date`, `wikidata`, `wikipedia`, `ref`, capacidade/volume se existirem.
- Gerar um **`dam_id` estável** = `"{osm_type}/{osm_id}"` (ex.: `way/123456`). É este o identificador público usado para ligar ao Notion.
- Se várias features descreverem a mesma barragem (ex.: linha + área), agrupar numa só entrada.

Simplificar geometrias para web (tolerância adequada por camada) e arredondar coordenadas a 5 casas decimais. Objetivo: o carregamento inicial < ~5 MB; se necessário dividir por país ou carregar camadas pesadas só a partir de certo zoom.

## 4. Ligação ao Notion (pensada para utilizadores leigos)

O Notion vai ter uma **base de dados pública** de barragens. Quem a preenche é pouco técnico, por isso:

- No Notion, cada página de barragem tem uma propriedade de texto **`ID Mapa`** onde se cola o `dam_id` (ex.: `way/123456`).
- **No site**, no painel de cada barragem, mostrar o `dam_id` com um botão **"Copiar ID"** grande e claro, e um texto curto: "Para ligar esta barragem ao Notion, cole este ID no campo *ID Mapa*". Aceitar também que colem o **link completo do OSM** (`https://www.openstreetmap.org/way/123456`) — o script normaliza.
- `scripts/fetch_notion.py` usa a **API oficial do Notion** (token de integração guardado como **GitHub Secret** `NOTION_TOKEN`, e `NOTION_DATABASE_ID`) para ler a base de dados e gerar `data/notion.json`: `{ dam_id: { url_publica, titulo, foto_capa, resumo } }`.
  - Converter o URL interno da página para o URL público (configurável, p.ex. domínio `*.notion.site`).
  - Se a página tiver capa/imagem, guardar o URL — atenção que URLs de ficheiros do Notion expiram (~1h); preferir capas externas ou documentar a limitação.
  - Validar e listar no log da Action IDs inválidos ou duplicados.
- A GitHub Action de dados corre o fetch do Notion **a cada hora/dia** (configurável), independentemente da extração OSM (que é semanal).
- Se não houver token configurado, o site funciona na mesma sem links.
- README: passo a passo com capturas descritas de como criar a integração Notion, partilhar a base de dados com ela, e meter os secrets no GitHub.

## 5. Interface (em português de Portugal)

- Mapa a ecrã inteiro centrado na Península Ibérica.
- **Barragens** como marcadores circulares coloridos por `uso` (legenda visível); **clustering** em zoom baixo. Barragens com página Notion têm um destaque (ex.: contorno ou ícone ★).
- **Albufeiras** como polígonos azul semi-transparente; destacar a albufeira ao selecionar a barragem.
- **Painel de camadas** com checkboxes: barragens, açudes, albufeiras, centrais, subestações, linhas, condutas/canais. Algumas desligadas por defeito e com `minzoom`.
- **Filtros**: país (PT/ES), uso, "só com página Notion".
- **Pesquisa** por nome de barragem/albufeira/rio (com acentos ignorados) e zoom ao resultado.
- **Painel lateral** ao clicar numa barragem: nome, país, rio, uso, operador, altura, ano, albufeira associada (área calculada em ha), centrais associadas (potência), links para OSM / Wikidata / Wikipedia, botão "Copiar ID", e se existir, foto e botão **"Ver no Notion"**.
- URL partilhável: o estado (barragem selecionada, zoom, posição) fica no hash do URL (ex.: `#dam=way/123456`).
- Responsivo (telemóvel: painel em bottom sheet), acessível (contraste, foco de teclado), modo escuro opcional.
- Atribuição OSM e data da última atualização dos dados no rodapé.

## 6. Preparar a próxima fase: bairros barragistas

Ainda não implementar, mas deixar a arquitetura pronta:
- Uma camada vazia `data/bairros.geojson` (polígonos) com schema definido: `id`, `nome`, `dam_id` associado, `periodo`, `notion_url`, `descricao`.
- O código de camadas deve permitir adicionar esta camada com uma linha de configuração.
- No README, sugerir como serão desenhados (ex.: geojson.io ou QGIS, exportar GeoJSON e fazer commit; ou futuramente vindos também do Notion).

## 7. Qualidade

- Código comentado em português, funções pequenas, configuração centralizada (`scripts/config.py` e `js/config.js`: raios, tolerâncias, cores, URLs).
- Tratamento de erros e logs claros no script; a Action não deve apagar dados bons se a extração falhar (só substituir se a nova extração passar validações mínimas, p.ex. nº de barragens > 80% do anterior).
- Instruções no README para correr tudo localmente (`python -m venv`, `pip install -r requirements.txt`, `python -m http.server`).
- Indica no fim limitações conhecidas (qualidade/consistência do tagging OSM, barragens sem nome, falsos positivos na associação espacial) e próximos passos.

Antes de escrever o código, apresenta brevemente o plano e as decisões; depois entrega todos os ficheiros.
