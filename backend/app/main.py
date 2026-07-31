"""
Servidor da Central de Inteligência — Resumo Oficina.

O que ele faz, em uma frase: a cada POLL_SECONDS consulta o BigQuery,
calcula os KPIs (kpis.py) e EMPURRA o resultado por WebSocket para
todos os painéis abertos — nenhum navegador fala com o BigQuery.

    BigQuery ──(polling, 1 consulta/ciclo)──► este servidor ──(WebSocket)──► N telas

Rotas:
    GET  /            painel (o HTML do protótipo)
    WS   /ws          canal de atualização em tempo real
    GET  /api/resumo  último payload em JSON (útil para depurar)
    GET  /healthz     verificação de saúde (para monitoramento)
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, kpis, mock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("oficina.server")

# ------------------------- estado compartilhado -----------------------------
ultimo_payload: dict | None = None      # último resultado calculado
clientes: set[WebSocket] = set()        # painéis conectados agora


# --------------------------- proteção de acesso -----------------------------
def _token_ok(token: str) -> bool:
    """True se o acesso é permitido. Sem ACCESS_TOKEN configurado, tudo é aberto
    (uso local/rede). Com token, exige o valor exato (comparação em tempo
    constante). Ver config.ACCESS_TOKEN."""
    if not config.ACCESS_TOKEN:
        return True
    return bool(token) and hmac.compare_digest(token, config.ACCESS_TOKEN)


_PAGINA_NEGADA = (
    "<!doctype html><meta charset='utf-8'>"
    "<title>Acesso restrito</title>"
    "<div style=\"font:600 18px system-ui;color:#183B48;display:flex;"
    "height:100vh;align-items:center;justify-content:center;text-align:center\">"
    "Acesso restrito.<br>Abra o painel pelo link autorizado (com token).</div>"
)


async def _calcular_payload() -> dict:
    """Um ciclo: busca as duas views e aplica a modelagem."""
    if config.DATA_SOURCE == "mock":
        return mock.build_mock_payload()
    if config.DATA_SOURCE == "csv":
        from . import csv_source as fonte
    else:
        from . import bq as fonte  # import tardio (só carrega a lib do Google quando precisa)
    # consultas fora do event loop (as regras seguem as medidas DAX do manutest)
    man  = await asyncio.to_thread(fonte.fetch_manutencao)
    mon  = await asyncio.to_thread(fonte.fetch_monitoramento)
    bem  = await asyncio.to_thread(fonte.fetch_cadastro_bem)
    mec  = await asyncio.to_thread(fonte.fetch_mecanicos)
    mecos = await asyncio.to_thread(fonte.fetch_mecanicos_os)
    prev = await asyncio.to_thread(fonte.fetch_preventivas)
    tqr  = await asyncio.to_thread(fonte.fetch_tqr)
    ss   = await asyncio.to_thread(fonte.fetch_ss_aguardando)
    ofi  = await asyncio.to_thread(fonte.fetch_oficina_externa)
    # "Reservas no Limite" sai de bem_rows (estoque 02 por contrato+lote) +
    # mon_rows (Xbemre em uso) — não há mais consulta de portaria. Ver kpis.py.
    return kpis.build_payload(man, mon_rows=mon, bem_rows=bem,
                              mecanicos_rows=mec, mecanicos_os_rows=mecos,
                              prev_rows=prev, tqr_rows=tqr, ss_rows=ss,
                              oficina_rows=ofi)


async def _broadcast(payload: dict) -> None:
    """Envia o payload para todos os painéis; remove conexões mortas."""
    mortos = []
    for ws in clientes:
        try:
            await ws.send_json(payload)
        except Exception:
            mortos.append(ws)
    for ws in mortos:
        clientes.discard(ws)


async def _loop_de_atualizacao() -> None:
    """Tarefa de fundo: consulta -> calcula -> transmite -> dorme -> repete."""
    global ultimo_payload
    while True:
        try:
            ultimo_payload = await _calcular_payload()
            await _broadcast(ultimo_payload)
            log.info("Ciclo ok — %d painel(is) conectado(s); próximo em %ss",
                     len(clientes), config.POLL_SECONDS)
        except Exception:
            # Um ciclo que falha (rede, BigQuery fora) NÃO derruba o servidor:
            # o painel continua mostrando o último dado bom e tentamos de novo.
            log.exception("Falha no ciclo de atualização — mantendo último dado")
        await asyncio.sleep(config.POLL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tarefa = asyncio.create_task(_loop_de_atualizacao())
    log.info("Servidor no ar — modo %s, ciclo de %ss",
             config.DATA_SOURCE.upper(), config.POLL_SECONDS)
    yield
    tarefa.cancel()


app = FastAPI(title="Central de Inteligência — Resumo Oficina", lifespan=lifespan)


# ------------------------------- rotas --------------------------------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # O middleware HTTP não cobre WebSocket — o gate é aqui. Token vem na query
    # (o frontend repassa o ?token=… da própria URL). 1008 = policy violation.
    if not _token_ok(ws.query_params.get("token", "")):
        await ws.close(code=1008)
        return
    await ws.accept()
    clientes.add(ws)
    log.info("Painel conectado (%d no total)", len(clientes))
    try:
        if ultimo_payload:                 # entrega imediata do último dado
            await ws.send_json(ultimo_payload)
        while True:                        # mantém a conexão viva
            await ws.receive_text()        # (ignoramos mensagens do cliente)
    except WebSocketDisconnect:
        pass
    finally:
        clientes.discard(ws)
        log.info("Painel desconectado (%d restam)", len(clientes))


@app.get("/api/resumo")
async def api_resumo(request: Request):
    if not _token_ok(request.query_params.get("token", "")):
        return JSONResponse({"detail": "acesso negado"}, status_code=401)
    if ultimo_payload is None:
        return JSONResponse({"detail": "Primeiro ciclo ainda em execução"}, status_code=503)
    return ultimo_payload


@app.get("/api/veiculo/{cod_bem}/historico")
async def api_historico_veiculo(cod_bem: str, request: Request):
    """Extrato completo de manutenção de UM veículo — buscado SOB DEMANDA (popup
    do painel), fora do ciclo de 5 min para não pesar o WebSocket. Ver
    kpis.historico_payload e bq.fetch_historico_veiculo."""
    if not _token_ok(request.query_params.get("token", "")):
        return JSONResponse({"detail": "acesso negado"}, status_code=401)
    if config.DATA_SOURCE == "mock":
        return {"codBem": cod_bem, "placa": "", "nome": "", "total": 0,
                "custoTotal": "R$ 0,00", "itens": []}
    if config.DATA_SOURCE == "csv":
        from . import csv_source as fonte
    else:
        from . import bq as fonte
    rows = await asyncio.to_thread(fonte.fetch_historico_veiculo, cod_bem)
    return kpis.historico_payload(rows, cod_bem)


@app.get("/api/os/{ordem}/extrato")
async def api_extrato_os(ordem: str, request: Request):
    """Extrato completo de UMA O.S. (descrição, veículo, valores, mão de obra) —
    SOB DEMANDA. Ver kpis.extrato_os_payload e bq.fetch_extrato_os."""
    if not _token_ok(request.query_params.get("token", "")):
        return JSONResponse({"detail": "acesso negado"}, status_code=401)
    if config.DATA_SOURCE == "mock":
        return {"os": ordem, "existe": False, "maoDeObra": [], "pecas": []}
    if config.DATA_SOURCE == "csv":
        from . import csv_source as fonte
    else:
        from . import bq as fonte
    data = await asyncio.to_thread(fonte.fetch_extrato_os, ordem)
    return kpis.extrato_os_payload(data, ordem)


@app.get("/api/ss/{ss}/extrato")
async def api_extrato_ss(ss: str, request: Request):
    """Extrato completo de UMA S.S. (O.S. da solicitação, veículo, valores
    totais e mão de obra) — SOB DEMANDA. Ver kpis.extrato_ss_payload e
    bq.fetch_extrato_ss."""
    if not _token_ok(request.query_params.get("token", "")):
        return JSONResponse({"detail": "acesso negado"}, status_code=401)
    if config.DATA_SOURCE == "mock":
        return {"ss": ss, "existe": False, "ordens": [], "maoDeObra": []}
    if config.DATA_SOURCE == "csv":
        from . import csv_source as fonte
    else:
        from . import bq as fonte
    data = await asyncio.to_thread(fonte.fetch_extrato_ss, ss)
    return kpis.extrato_ss_payload(data, ss)


@app.get("/api/oficinas/externas")
async def api_oficinas_externas(request: Request):
    """Lista AGREGADA de oficinas externas (histórico) com indicadores — SOB
    DEMANDA (clique no tile 'Oficina externa'). Ver kpis.oficinas_externas_payload
    e bq.fetch_oficinas_externas."""
    if not _token_ok(request.query_params.get("token", "")):
        return JSONResponse({"detail": "acesso negado"}, status_code=401)
    if config.DATA_SOURCE == "mock":
        return {"total": 0, "totalOS": 0, "totalVeic": 0, "custoTotal": "R$ 0,00", "oficinas": []}
    if config.DATA_SOURCE == "csv":
        from . import csv_source as fonte
    else:
        from . import bq as fonte
    rows = await asyncio.to_thread(fonte.fetch_oficinas_externas)
    return kpis.oficinas_externas_payload(rows)


@app.api_route("/healthz", methods=["GET", "HEAD"])
async def healthz():
    # SEMPRE aberto (sem token) — é o que o UptimeRobot pinga a cada 5 min para
    # manter o serviço acordado no plano free do Render. Aceita HEAD também: o
    # UptimeRobot usa HEAD por padrão e o FastAPI não o adiciona sozinho num
    # @app.get (sem isto, o HEAD vaza para o mount de estáticos e vira 404).
    return {"ok": True, "clientes": len(clientes), "temDados": ultimo_payload is not None}


@app.get("/")
async def index(request: Request):
    if not _token_ok(request.query_params.get("token", "")):
        return HTMLResponse(_PAGINA_NEGADA, status_code=401)
    return FileResponse(config.FRONTEND_DIR / "Resumo_Oficina.dc.html")


# Arquivos estáticos do frontend (support.js, _ds, fallback de tokens…)
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR), name="frontend")
