# CLAUDE.md — contexto para o Claude Code

## O que é este projeto

Painel "Central de Inteligência — Resumo Oficina" da MAAS. Dashboard de TV
(1920×1080, estética control room em petróleo #183B48) que mostra a operação
da oficina em tempo quase real: o backend consulta o BigQuery a cada 5 min,
calcula os KPIs e empurra o JSON por WebSocket para as telas abertas.

## Arquitetura

```
BigQuery (silver.STJ_Manutencao + silver.STJ)
   → backend/app/bq.py        (consultas — passo "Fonte")
   → backend/app/kpis.py      (modelagem/regras — as "medidas DAX")
   → backend/app/main.py      (FastAPI: polling + WebSocket /ws + estáticos)
   → frontend/Resumo_Oficina.dc.html  (recebe via WS e re-renderiza)
```

Fontes alternáveis por `DATA_SOURCE` no `backend/.env`:
`mock` (demo) · `csv` (lê `backend/dados/*.csv`, validação offline) ·
`bigquery` (produção).

## Regras que NÃO devem ser quebradas

- **Nenhuma credencial em código ou no repositório.** Autenticação só via
  `GOOGLE_APPLICATION_CREDENTIALS` no `.env` (git-ignorado) ou ADC do gcloud.
  O frontend nunca fala com o BigQuery.
- **Contrato do payload**: as chaves do JSON (`kpis`, `tipoServico`, `aging`,
  `detalhes`, `mecanicos`, `geradoEm`) são compartilhadas entre `kpis.py`,
  `mock.py` e o `renderVals()` do frontend. Mudou de um lado, mude dos três.
- **Identidade visual intocada**: paleta petróleo/verde MAAS, tipografia e
  componentes do protótipo vBeta. Novos elementos usam as variáveis CSS
  existentes (`--maas-*`, `--surface-*`), nunca cores hardcoded novas.
- O frontend usa um runtime próprio (`support.js`, não editar — é gerado):
  template com `{{ … }}`, `sc-if`, `sc-for`, e um `class Component extends
  DCLogic` com `renderVals()` dentro do próprio HTML.

## Fatos do schema (validados com exports reais de 10/07/2026)

- Ordem ABERTA = `situacao/SITUACA ≠ 'C'` e `termino/TERMINO = 'N'`.
- FORA DO PRAZO = agora > `dtMpFim`+`horaMpFim` (o "P.FIM MAN").
- Serviço: 000001 Corretiva · 000002 Sinistro · 000003 Preventiva ·
  000004 Implementação · 000005 Socorro.
- Não existe coluna de placa — o veículo é o `codBem` (painel mostra "Bem N").
- `STJ` tem ~1.081 preventivas de planos antigos vencidas em 2024; o corte
  `PREV_RETRO_DIAS` (padrão 90) existe para esse ruído não poluir o KPI.

## Como rodar e testar

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # DATA_SOURCE=csv para validar offline
python -m uvicorn app.main:app --reload --port 8000
```

Smoke test: `GET /healthz` responde `{"ok":true,…}`; `GET /api/resumo` traz o
payload; abrir http://localhost:8000 mostra o painel com o indicador verde
"ao vivo". Não há suíte de testes formal ainda — se criar, use `pytest` em
`backend/tests/` com casos sobre `kpis.build_payload` (linhas sintéticas).

## Pendências conhecidas (contexto para futuras tarefas)

KPIs sem coluna nas views (entram por `.env`): S.S. aguardando, Controle de
qualidade, Clientes esp., Reservas no limite. "Cláusula contratual" está
derivada como fora-do-prazo sem `xBemRes` — regra a confirmar. Efetivo de
mecânicos vem do `.env`. Join bem→placa depende de tabela ainda não mapeada.
