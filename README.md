# Barragens de Portugal e Espanha 🗺️

Mapa interativo das **barragens**, **açudes**, **albufeiras** e
**infraestruturas associadas** (centrais hidroelétricas, subestações, linhas
elétricas, condutas e canais) de Portugal e Espanha, com dados do
**OpenStreetMap (OSM)**.

Cada barragem pode ser ligada a uma **página pública do Notion** com fotos e
mais informação.

O site é 100% estático (não precisa de servidor), usa **MapLibre GL JS** e o
mapa base do **OpenFreeMap**. Os dados são gerados por um pequeno programa em
Python e publicados automaticamente no **GitHub Pages**.

---

## 1. Ver o site agora (sem instalar nada)

Se estiveres a ver isto no GitHub, o site já pode estar publicado em:

```
https://<o-teu-utilizador>.github.io/<o-teu-repo>/
```

> **Importante:** neste momento `data/` contém uma **amostra** pequena (algumas
> barragens conhecidas) para o site funcionar de imediato. O site mostra um
> aviso amarelo "dados de amostra". Para carregar os dados reais do OSM, segue
> o passo 4.

---

## 2. Estrutura do projeto

```
index.html                     Página do mapa
css/style.css                  Estilos (claro/escuro, responsivo)
js/config.js                   Configuração do frontend (cores, camadas, estilos)
js/main.js                     Arranque: mapa, tema, estado no URL
js/layers.js                   Camadas do mapa, clustering e filtros
js/panel.js                    Painel de camadas, filtros e detalhe
js/search.js                   Pesquisa (ignora acentos)
js/utils.js                    Utilidades pequenas
data/                          Dados gerados (GeoJSON + manifest + notion.json)
scripts/config.py              Configuração do pipeline (endpoints, raios, tolerâncias)
scripts/build_data.py          Extrai do OSM e gera os GeoJSON
scripts/fetch_notion.py        Lê a base de dados do Notion
scripts/overpass.py            Cliente da Overpass API (com retries)
scripts/geo.py                 Geometria/SIG (multipolígonos, distâncias)
scripts/fixtures/              Amostra local (usada por `--offline`)
requirements.txt               Dependências Python
.github/workflows/             Ações automáticas (dados, notícia, publicação)
```

---

## 3. Como funcionam os dados

1. `scripts/build_data.py` (Overpass) ou `scripts/build_data_pbf.py` (extracts
   do Geofabrik, o método usado pela GitHub Action) vão buscar ao
   **OpenStreetMap** as barragens, albufeiras, açudes e — num raio de 3 km —
   centrais, subestações, linhas elétricas e condutas.
2. Associa cada barragem à sua **albufeira** e às **centrais** mais próximas e
   classifica o **uso**: `hidroelétrica`, `regadio`, `abastecimento`, `misto`
   ou `desconhecido`.
3. Escreve ficheiros leves em `data/` (`*.geojson`) e um `data/manifest.json`.

Cada barragem tem um **ID estável** no formato `tipo/id` (ex.: `way/123456`).
É este o ID que liga ao Notion.

---

## 4. Correr o pipeline de dados no teu computador

Precisas de **Python 3.10 ou mais recente**.

### Passo a passo

1. Abre um terminal na pasta do projeto.
2. Cria um ambiente Python isolado e instala as dependências:

   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS / Linux:
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

3. Antes de publicar, **edita** `scripts/config.py` e troca o `USER_AGENT`
   pelo teu contacto (é pedido pela política de uso da Overpass):

   ```python
   USER_AGENT = "barragens-pt-es/1.0 (+https://github.com/o-teu-utilizador/o-teu-repo)"
   ```

4. Extrai os dados reais (pode demorar bastante — são dois países):

   ```bash
   python scripts/build_data.py
   ```

   > Se só quiseres testar rapidamente, sem ir à internet:
   > ```bash
   > python scripts/build_data.py --offline
   > ```
   > (usa a amostra em `scripts/fixtures/`).

5. Ver o site localmente:

   ```bash
   python -m http.server 8000
   ```

   Depois abre <http://localhost:8000> no navegador.

### Se a Overpass estiver ocupada

A API pública da Overpass é gratuita e por vezes está sobrecarregada. O script
já tenta vários espelhos, espera e repete, e divide a extração por regiões se
o país inteiro der *timeout*. Mesmo assim, tenta novamente mais tarde se falhar.

### Alternativa recomendada: extracts do Geofabrik (.pbf)

Quando a Overpass está saturada (502/504/timeout), há um caminho **mais fiável**:
usar os ficheiros oficiais do [Geofabrik](https://download.geofabrik.de/europe/),
que não dependem da Overpass:

```bash
python scripts/build_data_pbf.py --countries PT          # Portugal
python scripts/build_data_pbf.py --countries PT --skip-infra
python scripts/build_data_pbf.py --countries PT,ES       # ambos
```

Este script descarrega o `.pbf` do país (com cache em `/tmp/osm-cache`, ou o
diretório indicado na variável `OSM_CACHE`), filtra em memória com a biblioteca
`pyosmium` e produz exatamente os mesmos ficheiros em `data/`. É a forma mais
robusta para Portugal + Espanha (PT ~425 MB, ES ~1,5 GB).

> Nota: processar os `.pbf` exige alguma memória RAM (o índice de nós do
> `locations=True` fica em memória). Em máquinas com pouca RAM, corre um país
de cada vez.

---

## 5. Publicar no GitHub Pages (passo a passo, sem experiência técnica)

1. **Cria um repositório** no GitHub (pode ser público) e envia este projeto
   para lá. Pela interface web: *Add file → Upload files* (arrasta tudo).
   Pela linha de comandos:

   ```bash
   git init
   git add .
   git commit -m "Versão inicial"
   git branch -M main
   git remote add origin https://github.com/<utilizador>/<repo>.git
   git push -u origin main
   ```

2. No repositório, vai a **Settings → Pages**.
3. Em **Build and deployment → Source**, escolhe **GitHub Actions**.
4. Vai ao separador **Actions**. O workflow **"Publicar no GitHub Pages"**
   corre sozinho a cada `push` para `main`. Ao fim de 1–2 minutos, o site
   fica disponível no URL indicado no topo do workflow (ou em *Settings → Pages*).

---

## 6. Ligar as barragens ao Notion

O objetivo: cada barragem do mapa pode mostrar uma foto e um botão
**"Ver no Notion"**.

### 6.1. Preparar a base de dados no Notion

1. Cria no Notion uma **base de dados** com uma página por barragem.
2. Adiciona uma propriedade de texto chamada exatamente **`ID Mapa`**.
3. (Opcional) Adiciona as propriedades **`Resumo`** (texto) e **`Foto`** (URL
   externa, ver nota em baixo).
4. Copia o `ID Mapa` a partir do mapa: clica numa barragem e usa o botão
   **"Copiar ID"**; cola esse valor na propriedade `ID Mapa` da página.
   Também podes colar o link completo do OpenStreetMap
   (`https://www.openstreetmap.org/way/123456`) — o script normaliza sozinho.

> **Nota sobre fotos:** capas/imagens carregadas para o Notion geram ligações
> que **expiram ao fim de ~1 hora**. Por isso, para fotos estáveis, usa uma
> **URL externa** (ex.: imagem num site ou num serviço de imagens).

### 6.2. Criar uma integração do Notion

1. Vai a <https://www.notion.so/my-integrations> e cria uma **nova integração**.
2. Copia o **token** (começa por `secret_` ou `ntn_`).
3. **Partilha a base de dados com a integração**: abre a base de dados no
   Notion → menu **…** → **Connections** → adiciona a tua integração.
4. Copia o **ID da base de dados** (está no URL da base de dados, entre a barra
   e o `?`; são 32 caracteres).

### 6.3. Guardar os segredos no GitHub

1. No repositório: **Settings → Secrets and variables → Actions → New repository secret**.
2. Cria duas entradas:
   * `NOTION_TOKEN` → o token da integração.
   * `NOTION_DATABASE_ID` → o ID da base de dados.
3. Pronto. O workflow **"Dados Notion (a cada hora)"** vai gerar
   `data/notion.json` automaticamente. Podes também lançá-lo à mão no
   separador **Actions** (*Run workflow*).

Se não configurares os segredos, **o site continua a funcionar** — apenas sem
links para o Notion.

### 6.4. (Opcional) Ver o site antes de publicar

```bash
python scripts/fetch_notion.py            # gera data/notion.json
python scripts/fetch_notion.py --dry-run  # só valida, sem escrever
```

---

## 7. Atualizações automáticas

| Workflow | Quando corre | O que faz |
| --- | --- | --- |
| **Dados OSM (semanal)** | Segundas, 04:17 UTC (+ manual) | Regenera `data/*.geojson` a partir dos extracts do **Geofabrik (.pbf)** e faz commit, país a país |
| **Dados Notion (a cada hora)** | De hora a hora (+ manual) | Atualiza `data/notion.json` |
| **Publicar no GitHub Pages** | A cada `push` em `main` (+ manual) | Publica o site |

Podes mudar as frequências editando as linhas `cron:` nos ficheiros em
`.github/workflows/`.

**Segurança dos dados:** se uma extração OSM falhar ou trouxer menos de 80%
das barragens anteriores, o script **não substitui** os dados bons (usa
`--force` para ignorar, se tiveres a certeza).

---

## 8. Fase 2 — bairros barragistas

Já está preparado, mas ainda **não implementado**:

* Existe `data/bairros.geojson` (vazio) e a camada **"Bairros barragistas"** no
  painel (desligada por defeito).
* O esquema previsto para cada polígono é:

  ```json
  {
    "id": "bairro-alqueva",
    "nome": "Bairro dos Operários",
    "dam_id": "way/123456",
    "periodo": "1942-1975",
    "notion_url": "https://...",
    "descricao": "Texto curto"
  }
  ```

Para desenhar bairros, usa o [geojson.io](https://geojson.io) ou o
[QGIS](https://qgis.org), exporta **GeoJSON**, coloca as propriedades acima e
faz commit do ficheiro em `data/bairros.geojson`. (No futuro podem também vir
do Notion.)

---

## 9. Limitações conhecidas

* **Qualidade do OSM:** o *tagging* é inconsistente. Algumas barragens não têm
  nome, uso, altura ou operador; algumas albufeiras usam etiquetas antigas.
* **Associação espacial:** a ligação barragem↔albufeira↔central é feita por
  proximidade (200 m / 2 km / 3 km). Pode haver falsos positivos (sobretudo em
  vales com várias infraestruturas próximas).
* **Filtros e agrupamento:** os filtros aplicam-se às barragens individuais;
  os grupos ("bolhas") mostram sempre o total de barragens que contêm.
* **Tamanho:** para Portugal + Espanha, alguns ficheiros podem ficar grandes.
  O pipeline divide automaticamente as camadas maiores por país e o site
  carrega as camadas pesadas só a partir de um certo zoom.
* **Overpass:** a API pública pode estar ocupada; a extração pode ter de ser
  repetida.
* **Notion:** só funciona com uma integração e a base de dados partilhada com
  ela; capas carregadas no Notion expiram (~1 h).

## 10. Próximos passos sugeridos

* Correr a extração real e verificar barragens sem nome/uso.
* Preencher o Notion e ligar as primeiras barragens.
* Melhorar a associação espacial (usar também o nome do rio).
* Adicionar a camada de bairros barragistas (fase 2).
* Opcional: estatísticas (nº de barragens por país/uso) e exportação CSV.

---

## Licenças e atribuição

* **Código:** MIT (ver `LICENSE`).
* **Dados:** derivados do OpenStreetMap, sob licença **ODbL**.
  Atribuição obrigatória: **© OpenStreetMap contributors**.
* **Mapa base:** [OpenFreeMap](https://openfreemap.org) (estilos `positron` e
  `dark`), sobre dados do OpenStreetMap.
