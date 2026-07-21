"""
Acesso ao BigQuery — o equivalente ao passo "Fonte" do seu Power Query,
agora com TRÊS views do modelo:

    STJ_Manutencao   → completa (é pequena: a oficina agora)
    STJ              → só as colunas e linhas que a modelagem usa
                       (abertas: SITUACA='L' e TERMINO='N'), para não
                       trafegar as ~37 mil linhas do histórico inteiro.
    TQB_Monitoramento → monitoramento de SLA por ordem (Xesper, Xreser,
                       SLAVencimentoOS/CC) — existia no dataset `silver`
                       mas não era consultada; ver kpis.py para o porquê.

A autenticação usa Application Default Credentials do Google — a mesma
camada que o conector do Power BI usa por baixo. Nada hardcoded.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from . import config

log = logging.getLogger("oficina.bq")

_client = None


def _get_client():
    global _client
    if _client is None:
        from google.cloud import bigquery  # import tardio (modo mock/csv não precisa)
        _client = bigquery.Client(project=config.BQ_PROJECT)
        log.info("Cliente BigQuery criado para o projeto %s", config.BQ_PROJECT)
    return _client


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
        return float(v)
    return v


def _rows(sql: str) -> list[dict]:
    job = _get_client().query(sql)
    return [{k: _jsonable(v) for k, v in dict(r).items()} for r in job.result()]


def fetch_manutencao() -> list[dict]:
    """Ordens em manutenção (a oficina agora) — a view já vem filtrada."""
    sql = f"""
        SELECT ordem, solici, dtOrigem, servico, NomeServico, codBem,
               situacao, termino, dtMpFim, horaMpFim,
               descricaoMobilizacao, xBemRes, localizacao_veiculo
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.{config.BQ_VIEW_MANUTENCAO}`
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("%s: %d linhas", config.BQ_VIEW_MANUTENCAO, len(rows))
    return rows


def fetch_stj() -> list[dict]:
    """Histórico STJ — só abertas e só as colunas de preventivas/retorno."""
    sql = f"""
        SELECT ORDEM, SOLICI, CODBEM, SERVICO, SITUACA, TERMINO,
               DTORIGI, DTMPINI, DTMPFIM, XRETORN
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.{config.BQ_VIEW_STJ}`
        WHERE SITUACA = 'L' AND TERMINO = 'N'
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("%s (abertas): %d linhas", config.BQ_VIEW_STJ, len(rows))
    return rows


def fetch_monitoramento() -> list[dict]:
    """Monitoramento de SLA por ordem — só as ordens ainda abertas.
    ordemSTJ casa com o `ordem` de STJ_Manutencao (join feito em kpis.py)."""
    sql = f"""
        SELECT ordemSTJ, Xesper, Xreser, SLAVencimentoOS, SLAVencimentoCC
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.TQB_Monitoramento`
        WHERE termino = 'N'
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("TQB_Monitoramento (abertas): %d linhas", len(rows))
    return rows
