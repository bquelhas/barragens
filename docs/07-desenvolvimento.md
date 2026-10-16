# 07 — Desenvolvimento

## 1. Requisitos

- **Python 3.10+** (a automação usa 3.12).
- Um browser moderno (o site usa módulos ES e MapLibre GL JS).
- Para `build_data_pbf.py`, `pyosmium` (pacote `osmium`) e memória RAM
  suficiente (o extract de Espanha tem ~1,5 GB).

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Correr o site localmente

O site é estático, mas usa `fetch` para `data/` — **não abras `index.html` com
`file://`** (bloqueio de CORS). Serve por HTTP:

```bash
python -m http.server 8000
# abre http://localhost:8000
```

## 3. Gerar dados

```bash
# Overpass (real) — pode ser lento/instável
python scripts/build_data.py

# Fixtures locais (offline, rápido) — amostra pequena
python scripts/build_data.py --offline

# Geofabrik (.pbf) — recomendado para PT+ES
python scripts/build_data_pbf.py --countries PT
python scripts/build_data_pbf.py --countries PT,ES

# Só reconstruir o manifest a partir do que está em data/
python scripts/build_data.py --manifest-only
```

Opções úteis: `--countries PT,ES`, `--force` (ignora a validação mínima),
`--skip-infra`, `--offline`.

> Antes de publicar, **edita `config.USER_AGENT`** em `scripts/config.py` e põe
> o teu contacto/URL (é exigido pela política de uso da Overpass).

### Cache dos `.pbf`

Por omissão em `/tmp/osm-cache`; muda com `OSM_CACHE`. O índice de nós é
controlado por `OSM_IDX` (`flex_mem` em RAM; `sparse_file_array,<ficheiro>`
para poupar RAM).

## 4. Notion (opcional, local)

```bash
export NOTION_TOKEN=...
export NOTION_DATABASE_ID=...
python scripts/fetch_notion.py
python scripts/fetch_lost_cities.py
```

## 5. Pipeline de POIs

```bash
python scripts/build_pois.py             # vai à API do OSM
python scripts/build_pois.py --offline   # mostra o que faria
```

## 6. Validar o trabalho

- **Dados**: confirma que `data/manifest.json` tem `generated_at` recente e que
  `counts` não caíram abruptamente; abre o site e verifica a ficha de uma
  barragem conhecida.
- **Frontend**: usa `?debug=1` para expor `window.__map` na consola; testa
  troca de tema, filtros, pesquisa e deep-link `#dam=way/123`.
- **Workflows**: usa *Run workflow* no separador Actions para testar
  manualmente (dados, Notion) sem esperar pelo cron.

> Não há suite de testes automatizada no repositório. A validação é manual e,
> no pipeline, por guardas (`MIN_DAMS_RATIO`, extração vazia → abortar).

## 7. Convenções de código

- **Idioma**: comentários, mensagens e UI em **português de Portugal**.
- **Configuração centralizada**: nada de números mágicos espalhados — vive em
  `scripts/config.py` (backend) e `js/config.js` (frontend), que se espelham.
- **Funções pequenas** e nomes descritivos; erros e logs claros no Python.
- **Robustez**: `try/catch` no frontend onde o ambiente pode falhar
  (`localStorage`, `clipboard`, `setPaintProperty`); *retries/backoff* no
  `overpass.py`.
- **Escrita atómica por país**: novas camadas devem entrar em `LAYER_KEYS`
  (`build_data.py`) para o manifest as apanhar.

## 8. Resolução de problemas

| Sintoma | Causa provável | Solução |
| --- | --- | --- |
| Overpass 502/504/timeout | API pública saturada | Usa `build_data_pbf.py` ou tenta mais tarde |
| Site vazio / sem dados | A abrir por `file://` | Serve com `http.server` |
| "Dados de amostra" | `manifest.sample = true` | Corre o pipeline real e faz commit |
| Sem links Notion | Segredos ausentes | Define `NOTION_TOKEN`/`NOTION_DATABASE_ID` |
| Fotos Notion desaparecem | Capas internas expiram (~1 h) | Usa URLs externas para as fotos |
| Build aborta "80%" | Extração trouxe poucas barragens | Investiga; usa `--force` só se tiveres a certeza |
| Alerta de atualização no site | `generated_at` mudou | Comportamento esperado (recarrega a cada 60 s) |

## 9. Fluxo de contribuição sugerido

1. Cria um ramo a partir de `main`.
2. Faz a alteração (frontend e/ou backend).
3. Testa localmente (`http.server` + pipeline `--offline`/`.pbf`).
4. Atualiza a documentação relevante em `docs/` e o `README.md` se for
   orientação de utilizador.
5. Abre um *pull request*.

## 10. Documentos-irmãos

- [`README.md`](../README.md) — guia de utilizador (publicar, Notion, limitações).
- [`PROMPT_DEEPSEEK.md`](../PROMPT_DEEPSEEK.md) — especificação original.
- [`PROMPT_DEEPSEEK_v2.md`](../PROMPT_DEEPSEEK_v2.md) — plano v2 (desempenho,
  design, PMTiles condicional).
