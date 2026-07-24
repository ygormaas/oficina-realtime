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
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, kpis, mock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("oficina.server")

# ------------------------- estado compartilhado -----------------------------
ultimo_payload: dict | None = None      # último resultado calculado
clientes: set[WebSocket] = set()        # painéis conectados agora


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
    prev = await asyncio.to_thread(fonte.fetch_preventivas)
    tqr  = await asyncio.to_thread(fonte.fetch_tqr)
    ss   = await asyncio.to_thread(fonte.fetch_ss_aguardando)
    # "Reservas no Limite" sai de bem_rows (estoque 02 por contrato+lote) +
    # mon_rows (Xbemre em uso) — não há mais consulta de portaria. Ver kpis.py.
    return kpis.build_payload(man, mon_rows=mon, bem_rows=bem,
                              mecanicos_rows=mec, prev_rows=prev,
                              tqr_rows=tqr, ss_rows=ss)


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
async def api_resumo():
    if ultimo_payload is None:
        return JSONResponse({"detail": "Primeiro ciclo ainda em execução"}, status_code=503)
    return ultimo_payload


@app.get("/healthz")
async def healthz():
    return {"ok": True, "clientes": len(clientes), "temDados": ultimo_payload is not None}


@app.get("/")
async def index():
    return FileResponse(config.FRONTEND_DIR / "Resumo_Oficina.dc.html")


# Arquivos estáticos do frontend (support.js, _ds, fallback de tokens…)
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR), name="frontend")
