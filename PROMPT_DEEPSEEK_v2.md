# Prompt para o DeepSeek — v2 (revisto): desempenho + design

> **Revisão (aplica-se a este ficheiro):** este é o v2 original **corrigido**
> após revisão técnica do código atual. Alterações face ao v2:
> 1. **PMTiles passou a condicional** (só se, depois de A1–A2, os tamanhos
>    excederem o orçamento) — ver A3. É a maior fonte de risco e,
>    provavelmente, desnecessária.
> 2. Acrescentado **`counts_by_country`** ao manifest (a Parte E precisa dele).
> 3. Alertado o risco de **cirurgia no estilo do OpenFreeMap** (itens 10 e 12).
> 4. Alertada a **expiração das capas do Notion** (item 15).
> 5. Acrescentado **estado atual / já feito** e uma **ordem de execução**.
> 6. Nome provisório sugerido: **Águas Represadas**.

---

Estás a trabalhar no repositório existente `bquelhas/barragens` (mapa estático
de barragens PT + ES, MapLibre GL JS + JS vanilla, dados OSM gerados por
`scripts/build_data_pbf.py` a partir de extracts Geofabrik, publicado no
GitHub Pages). Lê primeiro o código atual (`index.html`, `css/style.css`,
`js/*.js`, `scripts/*.py`, `.github/workflows/*`) e mantém a arquitetura: site
estático, sem framework, sem build no frontend.

Faz as alterações abaixo. Entrega os ficheiros alterados **completos** (sem
"..." nem "resto igual"), e no fim um resumo do que mudou e como testar. Não
quebres: deep-link `#dam=way/123`, ligação ao Notion (`data/notion.json`,
campo "ID Mapa"), filtros, pesquisa, modo escuro, camada futura de bairros.

## Estado atual (já feito / a saber)

- **`_shot.png` já foi removido** do git e está no `.gitignore` (A5 feito).
- `manifest.json` tem `countries: ["ES"]` — **bug confirmado**. A Action corre
  por país e cada execução reescreve o manifest. Arranjar em `rebuild_manifest`
  (derivar os países dos ficheiros em disco).
- O manifest **não tem** `counts_by_country` (necessário para o item 16).
- `data/reservoirs_*.geojson` = **34,8 MB** (ES 20,6 + PT 14,2), 72 625 polígonos.
- Já existem: clustering, destaque de albufeira, **destaque da rede elétrica
  relacionada** (a rever em C12), `?debug=1` (expõe `window.__map`).

## Ordem de execução recomendada

1. **A1, A2** (filtrar + simplificar) e **medir**.
2. **A4, A6** + `counts_by_country`. Só depois decidir **A3 (PMTiles)**.
3. **B** (identidade visual) e **C** (hierarquia) — juntas.
4. **D** (ficha), depois **E** e **F**, possivelmente em passagens separadas.

---

## Parte A — Desempenho dos dados (prioridade máxima)

Problema: `data/reservoirs_*.geojson` ~35 MB (ES: 72 625 polígonos, inclui
charcas e tanques). Objetivo: **carregamento inicial < 3 MB** e **nenhuma
camada > 5 MB** (comprimido, como servido pelo GitHub Pages).

1. **Filtrar albufeiras** no script: manter só as que (a) estão associadas a
   uma barragem (`dam_id` ligado) **ou** (b) têm área ≥ 5 ha (configurável em
   `scripts/config.py`, p.ex. `MIN_RESERVOIR_AREA_HA`). Guardar `area_ha` e
   `dam_id` como propriedades. Construir o mapa inverso barragem→albufeira a
   partir de `dam["reservoir_id"]` (já calculado em `associate`).
   > Nota: manter em GeoJSON **as albufeiras ligadas a barragens** é também o
   > que preserva a pesquisa por nome de albufeira e o destaque da albufeira
   > selecionada — ver A3.

2. **Simplificação por camada** com tolerâncias em metros (projeção métrica),
   preservando topologia; descartar polígonos degenerados (já implementado);
   coordenadas a 5 casas decimais; **remover propriedades não usadas pela
   interface** (nas albufeiras, `operator`/`wikidata`/`wikipedia` não são
   usados pela UI hoje).

3. **PMTiles — CONDICIONAL.** Só avançar se, **depois de A1+A2, alguma camada
   continuar > 5 MB**. Se for necessário:
   - Converter para PMTiles (albufeiras, linhas elétricas, condutas, açudes,
     contornos de barragem) com `tippecanoe` na GitHub Action.
   - Servir com o protocolo `pmtiles` no MapLibre (lib via CDN).
   - Manter em GeoJSON **o que a pesquisa e os marcadores precisam**: pontos de
     barragem (leves) e um **índice de nomes de albufeiras**, porque a pesquisa
     e o destaque da albufeira selecionada dependem de GeoJSON.
   - **Cuidados a verificar:** instalar `tippecanoe` no runner (não está no
     `ubuntu-latest` — compilar ou usar binário *release*); confirmar que o
     GitHub Pages responde a **Range requests** (o PMTiles depende disso); e
     que a lógica "commit por país" continua coerente (um `.pmtiles` por país).

4. **Corrigir o `manifest.json`**:
   - `countries` deve listar **todos** os países presentes (derivar dos
     ficheiros em disco em `rebuild_manifest`).
   - Acrescentar **`counts_by_country`**: `{ "PT": {dams: .., ...}, "ES": {..} }`
     (necessário para o item 16).
   - Garantir que a Action processa PT e ES **na mesma execução** (o loop já o
     faz) e que a validação "não apagar dados bons" continua a funcionar
     (comparar com o total anterior).

5. `_shot.png` — **já feito** (removido do git e no `.gitignore`).

6. **Medir e reportar**: tamanho total transferido no primeiro carregamento e
   por camada (comprimido, como servido pelo Pages).

## Parte B — Identidade visual

7. **Nome e tom**: vertente cultural/patrimonial. Três propostas:
   1. **Águas Represadas** *(preferida — cultural, distinta)*
   2. **Pedra e Água** *(betão/xisto + albufeira)*
   3. **Barragens Ibéricas** *(descritivo)*
   Usar a **1.ª** como título provisório, fácil de trocar em `js/config.js`.
   Subtítulo: *"Barragens, albufeiras e o seu património — Portugal e Espanha"*.

8. **Tipografia**: serifada com carácter para títulos (Fraunces ou Source Serif 4)
   + sans legível para UI (Inter ou IBM Plex Sans). Escala tipográfica consistente.
   > Nota: as fontes via Google Fonts adicionam um pedido externo; avaliar
   > `preconnect` e um `font-display: swap`.

9. **Paleta** inspirada em betão, água, xisto e granito: tokens CSS em `:root`
   (cinza-betão quente para superfícies, azul-água profundo como acento, tons
   terra). Redefinir para modo escuro. Recolorir categorias de uso para
   combinarem com a paleta, mantendo contraste AA e distinção para daltónicos
   (testar deuteranopia).

10. **Mapa base com relevo**: hillshade (fonte raster-dem gratuita, p.ex.
    Terrarium da AWS `elevation-tiles-prod`, **sem chave**, com atribuição),
    subtil, por baixo das camadas temáticas, em ambos os modos. Atenuar
    elementos que competem (POIs, estradas secundárias).
    > **Atenção:** "atenuar o mapa base" exige **buscar o estilo do OpenFreeMap,
    > alterar camadas por id/tipo e injetá-lo** — para os **dois** estilos
    > (light/dark) — e é frágil se o estilo deles mudar. O hillshade tem de ser
    > inserido na **ordem correta** (acima dos preenchimentos base, abaixo de
    > linhas e rótulos).

## Parte C — Hierarquia no mapa

11. **Albufeiras distintas dos rios**: preenchimento azul-água próprio
    (diferente do azul de rios do mapa base), contorno fino; a albufeira da
    barragem selecionada fica com contorno mais escuro e ligeiramente mais opaca.

12. **Rede elétrica relacionada**: o destaque atual a laranja grosso é
    demasiado agressivo. Linhas mais finas, cor que combine com a paleta
    (âmbar dessaturado), opacidade moderada, halo discreto; o resto da rede
    fica esbatido quando há seleção.
    > Nota: "esbater o resto da rede" implica ajustar o `paint` das camadas
    > base quando há seleção — mesma técnica (e mesmos riscos) do item 10.

13. **Barragens como protagonistas**: ícone simples de barragem (SVG desenhado
    por ti, registado via `map.addImage`, colorido por uso com **SDF**), com
    tamanho em função da altura (`height`) ou potência da central
    (`plant:output:electricity`), com valor por defeito para as sem dados. Em
    zoom baixo manter clustering, com clusters na cor da paleta e contagem
    legível. Barragens com página Notion: ★ pequeno ou anel dourado.
    > Nota: passar de `circle` para `symbol` obriga a rever o realce da
    > barragem selecionada (hoje usa `feature-state` num `circle`) e o teste de
    > clique. Tratar valores **nulos** de `height`/potência com um valor por
    > defeito na expressão de `icon-size`.

## Parte D — Painéis

14. **Painel de camadas recolhível**: fechado por defeito num botão "Camadas"
    (canto superior esquerdo); abre como popover/drawer. Legenda de cores
    separada, compacta e sempre visível (canto inferior esquerdo), só com as
    categorias ativas.

15. **Ficha da barragem como "ficha"**:
    - Foto de capa grande no topo quando existir no `notion.json` (com fallback
      elegante sem foto: ilustração/padrão na cor do uso).
      > **Atenção:** capas carregadas **no** Notion expiram (~1 h). Preferir
      > **URLs externas** (documentar no README) e garantir que o fallback
      > funciona quando a imagem falha (`onerror`).
    - Título em serifada, país + rio + uso como chips.
    - Factos principais em grelha (altura, ano, albufeira em ha, potência).
    - **"Ver no Notion"** como botão primário quando existir ligação.
    - Bloco "Copiar ID" movido para uma secção/aba **"Contribuir"** (explicação
      curta para leigos), discreta.
    - Informação técnica (ex.: "Uso: albufeira (usage=power); central associada
      (4)", tags OSM brutas) num `<details>` "Detalhes técnicos".
    - Links OSM/Wikidata/Wikipédia como ícones pequenos no rodapé da ficha.

## Parte E — Descoberta

16. **Ecrã de boas-vindas** (overlay leve à primeira visita, recordado com
    `localStorage` em `try/catch`; reabrível pelo botão "?"): o que é o projeto,
    contadores a partir do `manifest.json` (nº de barragens, albufeiras,
    centrais **por país** — usar `counts_by_country`) e 4–6 destaques clicáveis
    que voam até à barragem (p.ex. Alqueva, Aldeadávila, Miranda, Castelo de
    Bode, Alcántara, Mequinenza — localizar por nome/osm_id; omitir se não
    encontrar).

17. **Lista "No mapa"**: painel lateral com as barragens visíveis no viewport
    (atualiza em `moveend`, com debounce), ordenável por nome, altura, ano e
    potência; clicar na lista seleciona no mapa e vice-versa; hover destaca.
    Limitar a ~200 itens com aviso "aproxima para ver mais".

## Parte F — Telemóvel e acessibilidade

18. Em ecrãs < 768 px: ficha e lista em **bottom sheet** com 3 posições
    (recolhido / meio / cheio), arrastável por gesto e com botões acessíveis;
    pesquisa compacta (ícone que expande) para não tapar o mapa; painel de
    camadas em ecrã inteiro.

19. Alvos de toque ≥ 44 px, foco visível, `aria-*` nos painéis,
    `prefers-reduced-motion` respeitado nas animações de voo/transição, sem
    scroll horizontal.

## Qualidade

- Toda a configuração nova (limiares, tolerâncias, cores, nome do projeto,
  destaques) centralizada em `scripts/config.py` e `js/config.js`.
- Código comentado em português, como o existente.
- README atualizado (novas dependências, se houver; como mudar nome/cores/
  destaques; nota sobre capas do Notion).
- No fim, lista de limitações e de coisas que não conseguiste verificar.

Antes de escrever código, apresenta brevemente o plano (ficheiros a mudar e
decisões, incluindo os 3 nomes propostos); depois entrega os ficheiros.
