# Central de Inteligência — Resumo Oficina (vReal-time)

Evolução do protótipo vBeta: mesmo visual "control room" em petróleo MAAS, agora
alimentado por dados reais do BigQuery, atualizados a cada 5 minutos, sem reload
de página.

## Como funciona (a arquitetura em uma imagem)

```
                      1 consulta por ciclo                   push (WebSocket)
┌──────────────┐   ┌─────────────────────────┐   ┌───────────────────────────────┐
│   BigQuery   │──►│  Backend Python (FastAPI)│──►│  N telas abertas do painel    │
│  silver.STJ  │   │  · polling a cada 5 min  │   │  · recebem só o JSON novo     │
└──────────────┘   │  · calcula KPIs (kpis.py)│   │  · re-renderizam o que mudou  │
                   │  · guarda o último dado  │   └───────────────────────────────┘
                   └─────────────────────────┘
```

Pontos importantes do desenho, pensando em quem vem do Power BI:

O navegador nunca fala com o BigQuery. Só o backend tem credencial, e ela nunca
aparece no frontend nem no código — é o mesmo mecanismo de autenticação que o
conector do Power BI usa por baixo (Application Default Credentials do Google).

Uma consulta por ciclo, independente de quantas TVs/telas estejam abertas. Dez
painéis ligados continuam custando uma única query a cada 5 minutos.

Se o BigQuery ficar fora do ar em um ciclo, o painel segue mostrando o último
dado bom e o servidor tenta de novo no ciclo seguinte — nada quebra.

O pareamento com o Power Query: `bq.py` é o passo "Fonte"; `kpis.py` são as suas
medidas DAX (cada KPI é uma função pequena e comentada); o payload JSON é a sua
"tabela final" que o visual consome.

## Estrutura de pastas

```
oficina-realtime/
├── backend/
│   ├── requirements.txt
│   ├── .env.example              ← copie para .env e ajuste
│   └── app/
│       ├── config.py             ← "parâmetros" (env vars)
│       ├── bq.py                 ← consultas às 2 views no BigQuery (passo Fonte)
│       ├── csv_source.py         ← mesma leitura, a partir dos CSVs (offline)
│       ├── kpis.py               ← ★ modelagem / regras de negócio (as "medidas")
│       ├── mock.py               ← dados de demonstração (DATA_SOURCE=mock)
│       └── main.py               ← servidor: polling + WebSocket + estáticos
│   └── dados/                    ← exports das views p/ DATA_SOURCE=csv
└── frontend/
    ├── Resumo_Oficina.dc.html    ← seu protótipo + camada WebSocket
    ├── support.js                ← runtime (inalterado)
    └── _ds-fallback/tokens.css   ← fallback do design system (veja abaixo)
```

## Antes de rodar: 2 ajustes obrigatórios

**1. Pasta do design system.** O protótipo referencia `_ds/maas-design-system-…/`,
que não veio no upload. Copie essa pasta do protótipo original para dentro de
`frontend/`. Enquanto ela não existir, o painel usa `_ds-fallback/tokens.css`
(cores aproximadas da paleta, derivadas do próprio protótipo) — funciona, mas o
oficial é melhor.

**2. Schema já mapeado.** A modelagem (`kpis.py`) foi adaptada ao schema real
das views a partir dos exports enviados (amostra de 10/07/2026):
`STJ_Manutencao` alimenta a oficina "agora" (abertas, fora do prazo por
`dtMpFim`+`horaMpFim`, tipos por `NomeServico`, mobilização, S.O.S, aging por
`dtOrigem`) e `STJ` alimenta preventivas e retorno (aberta = `SITUACA='L'` +
`TERMINO='N'`; serviço `000003` = preventiva). Regras validadas contra os CSVs.

## Rodar localmente

Pré-requisito: Python 3.11+ instalado.

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate      |  Linux/Mac:  source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                  # (Linux/Mac: cp .env.example .env)
```

**Passo 1 — validar com os dados reais, offline.** O projeto já vem com os
exports das views em `backend/dados/`. Deixe `DATA_SOURCE=csv` no `.env` e:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abra http://localhost:8000 — o painel aparece com o indicador verde "ao vivo"
e os números calculados dos CSVs reais (46 abertas na amostra de 10/07). Para
uma demonstração animada sem dados reais, use `DATA_SOURCE=mock`.

**Passo 2 — plugar o BigQuery.** Autentique uma vez na máquina:

```bash
gcloud auth application-default login
```

(ou baixe o JSON de uma service account com papel *BigQuery Data Viewer* e
aponte `GOOGLE_APPLICATION_CREDENTIALS` no `.env`). Depois mude no `.env`:

```
DATA_SOURCE=bigquery
POLL_SECONDS=300
```

Reinicie o servidor. Confira o JSON cru em http://localhost:8000/api/resumo e
compare com os números do seu relatório Power BI, que é a fonte da verdade das
regras — cada regra está numa função pequena e comentada em `kpis.py`.

Dica de depuração: `GET /healthz` mostra se há dados e quantas telas estão
conectadas; o terminal do servidor loga cada ciclo.

## Hospedagem

**Servidor interno da MAAS (recomendado para painel de TV de oficina).** Uma VM
Windows ou Linux na rede interna resolve: instale Python, copie a pasta, rode o
uvicorn como serviço (no Linux, um unit do systemd com `Restart=always`; no
Windows, o Agendador de Tarefas com "executar ao iniciar" ou o NSSM). As TVs
apontam para `http://ip-do-servidor:8000`. Vantagem: o dado nunca sai da rede e
a autenticação por service account fica em um único lugar.

Exemplo de unit systemd (`/etc/systemd/system/oficina.service`):

```ini
[Unit]
Description=Central de Inteligencia - Resumo Oficina
After=network.target

[Service]
WorkingDirectory=/opt/oficina-realtime/backend
ExecStart=/opt/oficina-realtime/backend/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
EnvironmentFile=/opt/oficina-realtime/backend/.env

[User pode adicionar: User=oficina]
```

**Google Cloud Run (já que os dados moram no GCP).** Empacote com um Dockerfile
simples e publique; a service account do próprio Cloud Run acessa o BigQuery sem
arquivo de credencial nenhum. Atenção: habilite HTTP/2 ou use a opção de
WebSockets do Cloud Run (suportado) e configure `min-instances=1` para o polling
não dormir.

**VPS externa.** Funciona igual ao servidor interno, mas coloque um Nginx/Caddy
na frente com HTTPS (o WebSocket vira `wss://` automaticamente — o frontend já
detecta o protocolo) e alguma proteção de acesso (VPN, IP allowlist ou basic
auth), porque o painel expõe placas e ordens de serviço.

## O que mudou no frontend (e o que não mudou)

Não mudou: layout, cards, paleta, tipografia, ícones, drill-down — todos os
componentes do vBeta estão intactos.

Mudou: o `renderVals()` deixou de ter números fixos e passou a ler
`this.state.data`, que chega pelo WebSocket; o rótulo "recálculo a cada 5 min"
virou um indicador vivo de conexão (verde pulsando = ao vivo, laranja =
conectando, vermelho = reconectando, com reconexão automática a cada 5 s); e há
uma tela de "Conectando à Central de Inteligência…" até o primeiro ciclo chegar.
A manchete-síntese e o trilho de alertas agora são calculados dinamicamente a
partir dos dados (se tudo zerar, o painel mostra "Operação sem alertas ativos"
sozinho).

## Contrato do payload (backend → frontend)

Se um dia precisar mexer, este é o JSON que trafega no WebSocket e em
`/api/resumo`:

```json
{
  "geradoEm": "2026-07-17T14:18:49-03:00",
  "kpis": { "ssAguardando": 0, "osAbertas": 133, "osForaPrazo": 10,
            "qualidade": 1, "retorno": 0, "clientesEsp": 0, "clausula": 10,
            "reservaLimite": 0, "sos": 3,
            "prevAtrasadas": 17, "prevFinal": 8, "prevInicial": 8 },
  "mecanicos": { "trabalhando": 11, "disponivel": 6, "pausa": 0 },
  "tipoServico": [ { "k": "Implementação", "n": 97 } ],
  "aging": { "d0_2": 34, "d3_7": 52, "d8_30": 39, "d30p": 8 },
  "detalhes": { "osForaPrazo": [ { "abertura": "24/03 17:57",
      "aberturaIso": "2026-03-24T17:57:00-03:00", "ss": "024068",
      "os": "029166", "placa": "—", "mobil": "Mobilizado",
      "serv": "Implementação", "st": "Fora do Prazo" } ] }
}
```

Mudou uma chave aqui? Mude também no `Resumo_Oficina.dc.html`.

## Pendências conhecidas (decorrentes do schema real)

**Placa não existe nas views** — o identificador é o `codBem`; o painel mostra
"Bem 50076". Se houver uma tabela de-para bem→placa no seu modelo Power BI,
me diga o nome que eu adiciono o join.

**Preventivas:** a base tem 1.081 preventivas de planos antigos vencidas em
2024 e nunca encerradas. Para o KPI não virar ruído, "atrasadas" só conta
janelas vencidas nos últimos `PREV_RETRO_DIAS` (padrão 90 — com a amostra isso
zera o KPI; ajuste até bater com a regra do seu relatório, ou me passe a medida
DAX de preventivas que eu replico exatamente).

**Sem coluna nas views atuais** (entram por `.env` até existir fonte):
"S.S. aguardando" (precisaria da view de solicitações), "Controle de
qualidade", "Clientes esp./serv. rápido" e "Reservas no limite". "Cláusula
contratual" foi derivada como *fora do prazo e sem bem reserva apontado*
(`xBemRes` vazio) — na amostra isso marca todas as 46; ajuste a regra em
`kpis.py` se a definição real for outra. "Retorno" agora é automático
(`XRETORN` preenchido), com override manual no `.env`. O efetivo de mecânicos
segue por configuração (`MECANICOS_*`).

**Atenção ao testar com os CSVs:** o export é uma foto de 10/07 — rodando dias
depois, praticamente tudo aparece "fora do prazo" (os prazos de manutenção são
de poucas horas). Com o BigQuery ao vivo os números normalizam.
