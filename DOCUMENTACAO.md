# Documentação — Central de Inteligência · Resumo Oficina

> Documento de referência do projeto: **o que é, onde está cada coisa e como foi
> construído** (lógica, ferramentas e técnicas). É editável — atualize sempre que
> mudar uma regra, uma fonte ou o layout.
>
> Documentos irmãos: [`README.md`](README.md) (instalação/hospedagem, guia de
> primeiros passos) e [`CLAUDE.md`](CLAUDE.md) (contexto técnico denso, usado pelo
> assistente de código — bom para os detalhes finos de schema e regras DAX).

---

## Índice

1. [Visão geral](#1-visão-geral)
2. [Arquitetura e fluxo dos dados](#2-arquitetura-e-fluxo-dos-dados)
3. [Stack e ferramentas](#3-stack-e-ferramentas)
4. [Mapa de arquivos — onde está cada coisa](#4-mapa-de-arquivos--onde-está-cada-coisa)
5. [Backend em detalhe](#5-backend-em-detalhe)
6. [Fontes de dados (tabelas BigQuery)](#6-fontes-de-dados-tabelas-bigquery)
7. [Contrato do payload (backend → frontend)](#7-contrato-do-payload-backend--frontend)
8. [Frontend em detalhe](#8-frontend-em-detalhe)
9. [Dicionário de KPIs](#9-dicionário-de-kpis)
10. [Como rodar e testar](#10-como-rodar-e-testar)
11. [Autenticação e segredos](#11-autenticação-e-segredos)
12. [Decisões técnicas e limitações conhecidas](#12-decisões-técnicas-e-limitações-conhecidas)
13. [Glossário](#13-glossário)

---

## 1. Visão geral

**O que é:** um painel de TV (control room) para a oficina da MAAS. Mostra, em
tempo quase real, o estado da operação — ordens de serviço abertas, fora do prazo,
cláusulas contratuais estouradas, veículos, preventivas, mão de obra etc.

**Formato:** tela fixa de **1920×1080** (estética petróleo `#183B48`, identidade
MAAS), pensada para rodar numa TV, mas que escala para caber em qualquer janela.

**Como o dado chega:** o backend consulta o **BigQuery a cada 5 minutos**, calcula
os indicadores e **empurra o resultado por WebSocket** para todas as telas abertas.
O navegador nunca fala com o BigQuery.

**Analogia com Power BI** (a origem das regras): pense em `bq.py` como o passo
*"Fonte"* do Power Query, em `kpis.py` como as *"medidas DAX"* (cada KPI é uma
função pequena e comentada) e no JSON do payload como a *"tabela final"* que o
visual consome.

> As regras de KPI replicam as medidas do painel de referência **`manutest.vpax`**
> (analisado no VertiPaq Analyzer). Existe um painel antigo (`Painel Maas_Atualizado…`)
> com valores **incorretos** — não usar como gabarito.

---

## 2. Arquitetura e fluxo dos dados

```
                1 consulta por ciclo (5 min)              push por WebSocket (/ws)
┌──────────────┐   ┌──────────────────────────────┐   ┌──────────────────────────────┐
│   BigQuery   │──►│   Backend Python (FastAPI)     │──►│   N telas do painel (browser)│
│ dataset      │   │   • bq.py  → consulta as views │   │   • recebem só o JSON novo   │
│ silver.*     │   │   • kpis.py → calcula os KPIs  │   │   • re-renderizam o que mudou│
└──────────────┘   │   • main.py → guarda o último  │   └──────────────────────────────┘
                   │     payload e faz o broadcast  │
                   └──────────────────────────────┘
```

**Princípios do desenho:**

- **Uma consulta por ciclo, independente do número de telas.** Dez TVs ligadas
  custam uma única query a cada 5 minutos (o backend calcula uma vez e faz
  *broadcast*).
- **Tolerância a falha.** Se um ciclo falhar (rede, BigQuery fora), o servidor
  **mantém o último dado bom** na tela e tenta de novo no ciclo seguinte — nada
  quebra (ver `_loop_de_atualizacao` em `main.py`).
- **Credencial só no backend.** O frontend não tem e não precisa de credencial.
- **Cálculo ao vivo.** Vários KPIs comparam `agora > vencimento` a cada ciclo, em
  vez de confiar num flag congelado na ingestão (ver §12).

---

## 3. Stack e ferramentas

| Camada | Ferramenta | Papel |
|---|---|---|
| Backend | **Python 3.11+** | linguagem |
| Backend | **FastAPI** | servidor web + rota WebSocket |
| Backend | **Uvicorn** | ASGI server que roda o FastAPI |
| Backend | **google-cloud-bigquery** | cliente de consulta ao BigQuery |
| Backend | **python-dotenv** | carrega o `.env` para variáveis de ambiente |
| Dados | **BigQuery** (`gcp-maas-proj-manutencao.silver`) | fonte de produção |
| Frontend | **HTML único** (`.dc.html`) + `support.js` | runtime próprio (micro-framework) |
| Frontend | **WebSocket nativo** do browser | recebe os payloads |
| Auth | **ADC do gcloud** ou **service account JSON** | acesso ao BigQuery |

Dependências exatas em [`backend/requirements.txt`](backend/requirements.txt):
`fastapi`, `uvicorn[standard]`, `python-dotenv`, `google-cloud-bigquery`.

---

## 4. Mapa de arquivos — onde está cada coisa

```
oficina-realtime/
├── DOCUMENTACAO.md          ← este documento
├── README.md                ← instalação e hospedagem
├── CLAUDE.md                ← contexto técnico denso (schema/regras DAX)
│
├── backend/
│   ├── requirements.txt     ← dependências Python
│   ├── .env.example         ← modelo de configuração (copiar p/ .env)
│   ├── .env                 ← configuração real (NÃO versionado)
│   ├── dados/               ← CSVs das views p/ modo offline (NÃO versionado)
│   │   ├── STJ.csv
│   │   └── STJ_Manutencao.csv
│   └── app/
│       ├── config.py        ← "parâmetros": lê tudo do .env
│       ├── bq.py            ← consultas ao BigQuery (passo "Fonte")
│       ├── kpis.py          ← ★ modelagem/regras de negócio (as "medidas")
│       ├── mock.py          ← dados de demonstração (DATA_SOURCE=mock)
│       ├── csv_source.py    ← mesma interface do bq.py, lendo CSVs (offline)
│       └── main.py          ← servidor: polling + WebSocket + estáticos
│
├── frontend/
│   ├── Resumo_Oficina.dc.html  ← ★ o painel (UI + lógica + camada WebSocket)
│   ├── support.js              ← runtime do template (GERADO — não editar)
│   ├── _ds-fallback/tokens.css ← fallback das variáveis de cor (design system)
│   └── logo-maas.png
│
├── credenciais/             ← service-account-key.json (NÃO versionado)
├── runtime/                 ← Python portátil p/ empacotar (NÃO versionado)
├── iniciar-painel-tv.bat    ← atalho: sobe o servidor e abre o painel (Windows)
└── criar-atalho.bat         ← cria atalho na área de trabalho
```

**Os dois arquivos que concentram a lógica:** `backend/app/kpis.py` (regras) e
`frontend/Resumo_Oficina.dc.html` (visual + interação). Se você for editar algo,
90% das vezes é num desses dois.

**O que NÃO editar:** `frontend/support.js` é o runtime gerado do template — mexer
nele quebra o `{{ … }}`/`sc-if`/`sc-for`.

---

## 5. Backend em detalhe

O backend tem 6 módulos pequenos em `backend/app/`. A regra de ouro é: **cada KPI
é uma função pequena e comentada** — para ler a regra, procure a função pelo nome.

### 5.1 `config.py` — os parâmetros

Centraliza tudo o que vem do ambiente (o `.env`). Nada de valor fixo espalhado
pelo código. Principais chaves:

- `DATA_SOURCE` — `mock` | `csv` | `bigquery` (escolhe a fonte).
- `BQ_PROJECT` / `BQ_DATASET` — projeto e dataset (`gcp-maas-proj-manutencao` /
  `silver`).
- `POLL_SECONDS` — intervalo do ciclo (300 = 5 min).
- `PREV_RETRO_DIAS` — janela para "preventivas atrasadas" não virar ruído.
- `KPI_*_MANUAL` / `MECANICOS_*` — **fallbacks** usados só quando a tabela-fonte
  não vem (ex.: modo `csv` sem o CSV). Em produção, os KPIs têm fonte automática.

### 5.2 `bq.py` — as consultas (passo "Fonte")

Uma função `fetch_*` por tabela. Cada uma monta um `SELECT` só com as colunas
usadas e devolve `list[dict]`. Import "tardio" do cliente Google (só carrega a lib
quando `DATA_SOURCE=bigquery`).

| Função | Tabela | Para quê |
|---|---|---|
| `fetch_manutencao()` | `STJ_Manutencao` | a oficina "agora" (ordens abertas) |
| `fetch_monitoramento()` | `TQB_Monitoramento` (`termino='N'`) | SLA por ordem, reserva, status |
| `fetch_ss_aguardando()` | `TQB_Monitoramento` (sem filtro de término) | S.S. que ainda não viraram O.S. |
| `fetch_cadastro_bem()` | `ST9_CadastroBem` | contrato, lote, status e placa do veículo |
| `fetch_mecanicos()` | `SRA_SRJ_Funcionarios` | efetivo (nome, função, status, turno) |
| `fetch_preventivas()` | `STF_Status_Manutencao` | status das preventivas por bem |
| `fetch_tqr()` | `TQR` | categoria do veículo (Pesada/Leve) |

> **Técnica:** o `WHERE termino='N'` de `fetch_monitoramento` é o que mantém a
> consulta pequena. A `fetch_ss_aguardando` é uma consulta separada de propósito,
> porque as S.S. que ainda não viraram O.S. têm `termino` nulo e seriam perdidas
> pelo filtro.

### 5.3 `kpis.py` — a modelagem (o coração do projeto)

Transforma as linhas cruas em KPIs. Estrutura:

- **Utilitários de parsing:** `_norm`, `_s`, `_vazio`, `_dt_iso`, `_dt_compacta`
  (datas do ERP no formato `AAAAMMDD` + `HH:MM`), `_num`.
- **Fuso:** `TZ_BR = -03:00`. Todas as comparações "agora × prazo" usam este fuso.
- **Regras por linha:** funções como `_aberta_man`, `_abertura_ss`, `_sla_fora`,
  `_servico_da_ordem`, `_situacao_real`, `_reservas_limite`, `_mecanicos_detalhe`.
- **Montagem final:** `build_payload(...)` chama tudo e devolve o JSON do §7.

Pontos de lógica importantes (o "como foi construído"):

- **Abertura da O.S. = entrada da S.S.** (`_abertura_ss`): usa `DtAbertura`+`Hoaber`
  da TQB (data+hora **local**), não o `dtOrigem` da O.S. (que muda em reprovação e
  vem sem hora). O campo `DataHoraAbertura` guarda hora local rotulada como UTC —
  por isso **não se converte fuso** (converter atrasava 3h).
- **SLA ao vivo** (`_sla_fora`): `agora > SLAVencimento*`, recalculado a cada ciclo,
  em vez do flag-snapshot `SLAUltrapassado*` (exceção documentada: a Cláusula segue
  o flag — ver §9).
- **Serviço vem do STJ, não da TQB** (`_servico_da_ordem`): em ~3 ordens as fontes
  divergem; usar a mesma fonte na coluna "Tipo" e na regra de SLA evita a linha
  exibir um serviço e ser classificada por outro.
- **Ordenação dos drill-downs** (`_ordenar_por_abertura`): sempre do mais recente
  para o mais antigo; linhas sem data no fim.

### 5.4 `mock.py` — demonstração

Monta um payload sintético (com pequena variação aleatória a cada ciclo para o
"ao vivo" ficar visível) sem tocar em BigQuery. Útil para demo e para testar o
frontend. **Precisa manter o mesmo contrato do §7** — mudou uma chave no `kpis.py`,
espelhe aqui.

### 5.5 `csv_source.py` — validação offline

Mesma interface do `bq.py`, lendo `backend/dados/*.csv` (separador `;`). CSVs que
não existem viram `[]` e o KPI correspondente "degrada" graciosamente. Serve para
validar a modelagem sem rede. Hoje só há `STJ.csv` e `STJ_Manutencao.csv`, então
KPIs que dependem de TQB/ST9 ficam zerados nesse modo.

### 5.6 `main.py` — o servidor

- **`_calcular_payload()`** — escolhe a fonte pelo `DATA_SOURCE`, dispara os
  `fetch_*` (em `asyncio.to_thread`, fora do event loop) e chama `build_payload`.
- **`_loop_de_atualizacao()`** — o ciclo: consulta → calcula → `_broadcast` →
  dorme `POLL_SECONDS` → repete. Envolto em `try/except` para não derrubar o
  servidor num ciclo ruim.
- **Rotas:**
  - `GET /` — serve o `Resumo_Oficina.dc.html`.
  - `WS /ws` — canal de tempo real; ao conectar já recebe o último payload.
  - `GET /api/resumo` — último payload em JSON (depuração).
  - `GET /healthz` — saúde (tem dados? quantas telas conectadas?).
- **Estáticos** — `support.js`, `_ds-fallback`, `logo-maas.png` etc. montados na
  raiz.

---

## 6. Fontes de dados (tabelas BigQuery)

Dataset `gcp-maas-proj-manutencao.silver`. Junções principais:

- `STJ_Manutencao.ordem` = `TQB_Monitoramento.ordemSTJ`
- `TQB_Monitoramento.Codbem` = `ST9_CadastroBem.bem`
- `ST9_CadastroBem.numeroContrato` = `SZT_Contratos.Num`  *(SLA de cláusula)*
- `ST9_CadastroBem.tecnologia` = `TQR.TQR_TIPMOD`  *(tipo de veículo)*

| Tabela | O que dá |
|---|---|
| `STJ_Manutencao` | ordens em manutenção agora (situação, término, serviço, datas previstas, mobilização, localização, descrição) |
| `TQB_Monitoramento` | SLA por ordem (`SLAVencimentoOS/CC`, `SLAUltrapassado*`), abertura da S.S., reserva (`Xbemre`/`Xreser`), status, cliente esperando (`Xesper`) |
| `ST9_CadastroBem` | cadastro do veículo: contrato, lote, `statusBem`, placa, nome, tecnologia |
| `SZT_Contratos` | contrato: `Sla`/`SlaSos` (**duração** `HHHH:MM`), cliente, vigência. Liga por `Num` |
| `SRA_SRJ_Funcionarios` | efetivo (view derivada da escala): nome, função, `StatusFinal` calculado ao vivo, turno |
| `STF_Status_Manutencao` | status das preventivas por bem |
| `TQR` | catálogo de modelos → categoria (Pesada/Leve) |
| `SILVER_SIAN_SUPABASE_*` | sistema da oficina (tarefas/mecânicos) — **não usado** no vínculo mecânico→O.S. por estar defasado (ver §12) |

**Domínio de `ST9_CadastroBem.statusBem`:** 01 Locado · **02 Reserva** · 03 Serviços
· 04 Disponível · 05 Negociado · 06 Venda · 07 Vendido · 08 Em Adequação · 10
Aguardando Demanda · 12 Distratado.

**Código de serviço:** 000001 Corretiva · 000002 Sinistro · 000003 Preventiva ·
000004 Implementação · 000005 Socorro.

---

## 7. Contrato do payload (backend → frontend)

Este é o JSON que trafega no WebSocket e em `/api/resumo`. **As chaves são
compartilhadas entre `kpis.py`, `mock.py` e o `renderVals()` do frontend — mudou
de um lado, mude dos três.**

```jsonc
{
  "geradoEm": "2026-07-28T10:33:00-03:00",
  "kpis": {
    "ssAguardando": 1, "osAbertas": 67, "osForaPrazo": 38,
    "qualidade": 2, "retorno": 0, "clientesEsp": 3, "clausula": 14,
    "reservaLimite": 3, "sos": 1,
    "prevAtrasadas": 382, "prevFinal": 183, "prevInicial": 173
  },
  "mecanicos": { "trabalhando": 7, "disponivel": 2, "pausa": 3 },
  "tipoServico": [ { "k": "Corretiva", "n": 26 }, … ],
  "aging": { "d0_2": 35, "d3_7": 16, "d8_30": 21, "d30p": 2 },
  "veiculos": { "mobilizados": 62, "naoMobilizados": 2 },
  "localizacao": { "interna": 46, "externa": 19 },
  "tipoVeiculo": { "pesada": 44, "leve": 20 },
  "detalhes": {
    "osForaPrazo": [ … ], "osAbertas": [ … ], "sos": [ … ],
    "clausula": [ { "ss": "033041", "os": "038446", "placa": "TFV5A85",
                    "contrato": "30000115/26", "reserva": "", "serv": "Corretiva",
                    "st": "Fora do Prazo", "previsao": "27/07/2026 22:07",
                    "sla": "27/07/2026 23:06", "aberturaIso": "…" } ],
    "clientesEsp": [ … ], "ssAguardando": [ … ], "qualidade": [ … ],
    "retorno": [ … ], "veiculos": [ … ], "reservaLimite": [ … ],
    "mecanicos": [ { "matricula": "04480", "nome": "Abraão Carlos Barbosa",
                     "funcao": "Mecânico Nível II", "cc": "104101002",
                     "status": "Trabalhando", "turno": "06:00–11:00 · 12:00–15:48" } ]
  }
}
```

- `kpis` — os números dos cards.
- `detalhes.<kpi>` — a lista de linhas do drill-down daquele card.
- `detalhes.mecanicos` — o efetivo em turno (drill-down "Ver equipe").

---

## 8. Frontend em detalhe

Tudo vive em **`frontend/Resumo_Oficina.dc.html`**: HTML, CSS inline, e a lógica
num `<script type="text/x-dc">`. O runtime é o `support.js` (micro-framework
gerado).

### 8.1 O runtime (`support.js`) e o template

- Template com **`{{ expressão }}`** (interpolação), **`sc-if value="{{ … }}"`**
  (condicional) e **`sc-for list="{{ … }}" as="r"`** (repetição).
- A lógica é uma **`class Component extends DCLogic`** com um método
  **`renderVals()`** que devolve um objeto — todas as variáveis usadas no `{{ }}`.
- Estado em `this.state`; `this.setState({...})` re-renderiza.
- **Não editar `support.js`** (é gerado). Toda customização é no `.dc.html`.

### 8.2 Ciclo de vida e WebSocket

- `componentDidMount()` — inicia o relógio, o `fit()` (escala do palco) e o
  `connectWS()`.
- `connectWS()` — abre `ws(s)://host/ws`, detecta `https→wss` automaticamente,
  reconecta a cada 5s se cair. Cada payload recebido vira `setState({data})`.
- Indicador de conexão: verde pulsando = ao vivo · laranja = conectando ·
  vermelho = reconectando.
- Tela de "Conectando à Central de Inteligência…" até o primeiro ciclo chegar
  (`loading`).

### 8.3 Escala do palco (técnica)

O palco é fixo em 1920×1080 e usa `transform: scale(FIT_SCALE())` com
`transform-origin: center` para caber na janela. `FIT_SCALE` = menor razão entre
largura/altura da janela e 1920/1080. O `scale` já nasce calculado no `state`
inicial para evitar um "fantasma" na primeira pintura.

### 8.4 Os cards

`renderVals()` monta arrays de definição (`osDefs`, `clienteDefs`) e o helper
`mk()` gera cada card com: ícone, cor por severidade (crit/warn/neutral só quando
o valor dispara), e o `onOpen` que abre o drill-down (só clicável quando `valor>0`).

### 8.5 Os drill-downs (a parte com mais técnica)

Ao clicar num card, abre um **modal** com a tabela de detalhe. Dois modais:

1. **Modal genérico de O.S.** (`buildDetail()`), usado por quase todos os cards.
   Tem busca livre e filtros por faceta (serviço, situação, período, previsão,
   contrato).
2. **Modal de mão de obra** (`buildMecDetail()`), próprio, mais simples (nome,
   função, status, turno) — porque o efetivo tem colunas totalmente diferentes.

Técnicas empregadas no modal genérico:

- **Modos de coluna.** O mesmo template serve três layouts, escolhidos por
  `id`:
  - `ehPadrao` — Situação + Previsão (maioria dos cards).
  - `ehVeiculos` — Mobilização + Local (card Veículos).
  - `ehClausula` — duas datas de conclusão: **SLA contrato** + **Previsto**
    (sem coluna Situação).
- **Tabela responsiva.** As colunas usam `grid-template-columns` com
  **`minmax(0, …)`** (fixas) e **`fr`** (as de texto). Assim a tabela **cabe 100%
  do container em qualquer largura**, cortando textos longos com reticências em
  vez de gerar rolagem horizontal. A regra CSS `.dtl-grid > * { min-width:0;
  overflow:hidden; }` é o que habilita o encolhimento/corte. Cabeçalho e linhas
  usam o mesmo template e preenchem o mesmo contêiner → têm a mesma largura, então
  o fundo do cabeçalho fixo (`position:sticky`) cobre toda a faixa (sem valores
  "vazando" atrás dos títulos ao rolar).
- **Agrupamento por S.S.** Ordens da mesma solicitação ficam adjacentes e marcadas
  por uma barra colorida à esquerda.
- **Sinalização de atraso por linha** (drill-down da cláusula): a fonte das datas
  fica sempre em petróleo e o **sinal é a linha inferior**, na posição e espessura
  do separador cinza da tabela. SLA sempre vermelha (prazo de contrato estourado);
  Previsto vermelha só quando também ultrapassado, senão a mesma cinza do separador
  (funde). A linha "cheia" é feita com `align-self:stretch` + margem negativa para
  a borda inferior da célula coincidir com o separador da linha.

### 8.6 Identidade visual (tokens)

Cores, tipografia, raios e sombras vêm de **variáveis CSS** (`--maas-*`,
`--surface-*`, `--border-*`). O oficial é o design system em `_ds/…` (referenciado
no `<head>`); quando ele não está presente, entra o
[`frontend/_ds-fallback/tokens.css`](frontend/_ds-fallback/tokens.css) com valores
aproximados. **Regra:** elementos novos usam essas variáveis, nunca cores
hardcoded novas. Fontes: Space Grotesk (display), Inter (apoio), JetBrains Mono
(códigos), com fallbacks locais.

---

## 9. Dicionário de KPIs

Para cada indicador: a regra, a fonte e onde mexer (`kpis.py`, salvo indicação).

| KPI | Regra (resumo) | Fonte |
|---|---|---|
| **OS Abertas** | `termino='N'` e `situacao≠'C'`; cada O.S. conta (não deduplica por S.S.) | STJ_Manutencao |
| **OS Fora do Prazo** | aberta **e** `agora > SLAVencimentoOS` (ao vivo) **e** serviço ≠ Implementação. Sinistro entra | STJ + TQB |
| **Cláusula contratual** | DISTINCTCOUNT `codBem`: possui contrato + `SLAUltrapassadoCC='Fora do Prazo'` (flag) + **sem reserva apontada** (`Xbemre` vazio), exceto Implementação | STJ + TQB + ST9 |
| **Controle de Qualidade** | COUNT ordem com `tipoRet='A'` | STJ_Manutencao |
| **Retorno** | aberta e `xRetorn='1'` | STJ_Manutencao |
| **Clientes Esp.** | DISTINCTCOUNT `codBem` com `Xesper='S'` | TQB |
| **S.O.S** | aberta e `servico='000005'` | STJ_Manutencao |
| **S.S. Aguardando** | `StatusOS` NÃO contém "Aberta" (S.S. sem O.S. ainda) | TQB (consulta própria) |
| **Reservas no Limite** | por contrato+lote: em uso ≥ 1 e estoque − em uso ≤ 0 (estoque = `statusBem='02'`; em uso = `Xbemre` de O.S. aberta) | ST9 + TQB |
| **Veículos Mob/Não** | DISTINCTCOUNT `codBem` por `Xcontr` preenchido/vazio | STJ + TQB |
| **Tipo de veículo** | Pesada/Leve via `TQR.TQR_CATBEM` | TQR + ST9 |
| **Idade das O.S. (aging)** | faixas 0–2 / 3–7 / 8–30 / >30 dias pela abertura da S.S. | STJ + TQB |
| **Preventivas** | DISTINCTCOUNT `codBem` por `statusManutencao` (Atrasado/Período Final/Inicial) | STF_Status_Manutencao |
| **Mão de Obra** | DISTINCTCOUNT `RA_MAT` por `StatusFinal` (Trabalhando/Disponível/Intervalo). Drill-down lista o efetivo em turno (sem O.S. — a base não liga mecânico à ordem) | SRA_SRJ_Funcionarios |

**Notas de decisão sobre a Cláusula** (a regra mais discutida):
- O painel de referência define: *"veículos com contrato que entraram no status de
  fora do prazo, sem veículo reserva apontado"* → validado **=14** (28/07/2026).
- Usa o **flag** `SLAUltrapassadoCC` (snapshot), não o recálculo ao vivo, para
  acompanhar exatamente a referência. Hoje os dois dão o mesmo número.
- O flag `SLAUltrapassadoCC` já é, por baixo, `abertura + SZT_Contratos.Sla`. Por
  isso **não foi preciso conectar a `SZT_Contratos` no backend** — o vencimento já
  chega pronto como `SLAVencimentoCC` (usado no drill-down, coluna "SLA").

---

## 10. Como rodar e testar

Pré-requisito: Python 3.11+.

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate     |  Linux/Mac:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Os três modos (variável `DATA_SOURCE` no `.env`):

| Modo | Para quê | Precisa de |
|---|---|---|
| `mock` | demonstração animada | nada |
| `csv` | validar a modelagem offline | CSVs em `backend/dados/` |
| `bigquery` | produção | autenticação (§11) |

Subir o servidor:

```bash
python -m uvicorn app.main:app --reload --port 8000
```

- Painel: <http://localhost:8000>
- Payload cru: <http://localhost:8000/api/resumo>
- Saúde: <http://localhost:8000/healthz>

No Windows há atalhos: **`iniciar-painel-tv.bat`** sobe o servidor e abre o painel;
**`criar-atalho.bat`** cria o atalho na área de trabalho.

> **Atenção ao modo `csv`:** o export é uma foto de um dia; rodando dias depois,
> quase tudo aparece "fora do prazo" (os prazos são de poucas horas). Com o
> BigQuery ao vivo os números normalizam.

Ainda não há suíte de testes formal. Se criar, use `pytest` em `backend/tests/`
com casos sobre `kpis.build_payload` (linhas sintéticas).

---

## 11. Autenticação e segredos

- **Nenhuma credencial no código ou no repositório.** O `.gitignore` bloqueia
  `.env`, `*service-account*.json`, `credenciais/` e os CSVs de dados.
- Duas formas de autenticar o backend no BigQuery:
  1. **ADC do gcloud** — `gcloud auth application-default login` (uma vez na
     máquina). Simples, mas o token pode expirar por política de sessão da
     organização.
  2. **Service account** — aponte `GOOGLE_APPLICATION_CREDENTIALS` no `.env` para
     o JSON (papel *BigQuery Data Viewer*). Não sofre reautenticação — recomendado
     para o servidor que roda contínuo.
- O `bq` CLI usa o login de usuário do gcloud (separado do ADC) e precisa de
  `--project_id=gcp-maas-proj-manutencao`.

---

## 12. Decisões técnicas e limitações conhecidas

- **Cálculo ao vivo vs. snapshot.** "OS Fora do Prazo" recalcula `agora >
  SLAVencimentoOS` a cada ciclo (não usa o flag congelado). A "Cláusula" é a
  exceção: segue o flag `SLAUltrapassadoCC` para bater com o painel de referência.
- **Placa.** Vem de `ST9_CadastroBem.placa`; sem placa cadastrada, cai para
  "Bem N".
- **Mecânico → O.S. não existe de forma confiável.** O sistema SIAN
  (`SILVER_SIAN_SUPABASE_TAREFAS`) teria o vínculo, mas o registro é raro e
  defasado (poucas tarefas, resíduos de meses atrás). Por isso o drill-down de mão
  de obra mostra **quem está em turno**, sem a coluna de O.S.
- **`TTI_Portaria` aposentada.** O feed parou em 07/04/2026; "Reservas no Limite"
  passou a usar `Xbemre` da TQB + estoque `statusBem='02'` do ST9.
- **Preventivas atrasadas** filtram janelas vencidas há mais de `PREV_RETRO_DIAS`
  (padrão 90) para não contar backlog antigo de 2024.
- **Blocos do painel de TV original ainda sem UI no redesign:** "Veículos
  mobilizados/não", "Localização" e "Tipo de veículo" já são calculados no backend
  (`veiculos`, `localizacao`, `tipoVeiculo`) mas ainda não têm bloco próprio no
  frontend novo (o card Veículos cobre parte).

---

## 13. Glossário

| Termo | Significado |
|---|---|
| **S.S.** | Solicitação de Serviço — o pedido que entra antes de virar O.S. |
| **O.S.** | Ordem de Serviço — o trabalho de manutenção em si |
| **SLA da O.S.** | prazo de conclusão da manutenção (`SLAVencimentoOS`) |
| **SLA da cláusula** | prazo contratual com o cliente (`SLAVencimentoCC` = abertura + `SZT.Sla`) |
| **Previsto** | fim previsto da manutenção (`dtMpFim` + `horaMpFim`) |
| **Bem / codBem** | o veículo (a base não usa placa como chave) |
| **Reserva apontada** | veículo reserva designado para substituir o parado (`Xbemre`) |
| **Aging** | distribuição das O.S. abertas por faixa de idade |
| **Drill-down** | o modal de detalhe que abre ao clicar num card |
| **Payload** | o JSON com todos os KPIs, enviado por WebSocket |
| **ADC** | Application Default Credentials (autenticação Google) |
| **manutest.vpax** | painel Power BI de referência — gabarito das regras |

---

*Última atualização: 28/07/2026. Mantenha este documento junto das mudanças de
regra (`kpis.py`), de contrato (§7) ou de layout (`Resumo_Oficina.dc.html`).*
