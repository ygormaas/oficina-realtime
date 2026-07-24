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
    """Ordens em manutenção (a oficina agora) — a view já vem filtrada.

    `qtdRep` é o filtro-mestre de "O.S. aberta" do painel (=0), e
    `tipoRet`/`xRetorn` alimentam Controle de Qualidade e Retorno (ver kpis.py)."""
    sql = f"""
        SELECT ordem, solici, dtOrigem, servico, NomeServico, codBem,
               situacao, termino, dtMpFim, horaMpFim, qtdRep, tipoRet, xRetorn,
               descricaoMobilizacao, xBemRes, localizacao_veiculo, observa
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
    ordemSTJ casa com o `ordem` de STJ_Manutencao (join feito em kpis.py).

    Traz os campos das regras de SLA/cláusula/aguardando (SLAUltrapassadoOS/CC,
    StatusOS, nmServ, Xcontr, xss, key_filial_solici) — ver kpis.py."""
    sql = f"""
        SELECT ordemSTJ, Ordem, Solici, Codbem, DataHoraAbertura, DtAbertura, Hoaber,
               key_filial_solici, Xesper, Xreser, Xbemre, SLAVencimentoOS, SLAVencimentoCC,
               SLAUltrapassadoCC, SLAUltrapassadoOS, StatusOS, StatusMobilizacao,
               nmServ, Xcontr, xss
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.TQB_Monitoramento`
        WHERE termino = 'N'
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("TQB_Monitoramento (abertas): %d linhas", len(rows))
    return rows


def fetch_ss_aguardando() -> list[dict]:
    """S.S. aguardando abertura de O.S. — medida DAX Quantidade_OS_Aguardando
    (StatusOS NÃO contém "Aberta").

    Consulta separada de propósito: `fetch_monitoramento` filtra `termino='N'`
    e essas linhas têm `termino` NULL (a S.S. ainda não virou O.S.), então
    ficariam de fora. Aqui a tabela é lida sem esse filtro."""
    sql = f"""
        SELECT Solici, ordemSTJ, Codbem, DataHoraAbertura, DtAbertura, Hoaber,
               StatusOS, nmServ, Xcontr, Xesper, Xreser, Xbemre, xss
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.TQB_Monitoramento`
        WHERE StatusOS IS NULL OR NOT CONTAINS_SUBSTR(StatusOS, 'Aberta')
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("TQB_Monitoramento (S.S. aguardando): %d linhas", len(rows))
    return rows


def fetch_cadastro_bem() -> list[dict]:
    """Cadastro de bens (ST9_CadastroBem) — dá o contrato, o lote e o status do
    bem de cada veículo. A CLÁUSULA CONTRATUAL usa numeroContrato/statusBem daqui
    (join TQB_Monitoramento.Codbem = ST9_CadastroBem.bem); RESERVAS NO LIMITE usa
    statusBem='02' (Reserva) + numeroContrato + numeroLote para o estoque de
    reserva por lote. Ver kpis.py."""
    sql = f"""
        SELECT bem, numeroContrato, numeroLote, statusBem, tecnologia, placa, nome
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.ST9_CadastroBem`
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("ST9_CadastroBem: %d linhas", len(rows))
    return rows


def fetch_mecanicos() -> list[dict]:
    """Efetivo de mecânicos (SRA_SRJ_Funcionarios) — StatusFinal em
    Disponível / Trabalhando / Intervalo (bloco Mão de Obra). Ver kpis.py."""
    sql = f"""
        SELECT RA_MAT, StatusFinal
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.SRA_SRJ_Funcionarios`
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("SRA_SRJ_Funcionarios: %d linhas", len(rows))
    return rows


def fetch_preventivas() -> list[dict]:
    """Status das preventivas por bem (STF_Status_Manutencao) — o bloco
    Preventivas conta bens distintos por statusManutencao (Atrasado /
    Período Final / Período Inicial). Ver kpis.py."""
    sql = f"""
        SELECT codBem, statusManutencao
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.STF_Status_Manutencao`
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("STF_Status_Manutencao: %d linhas", len(rows))
    return rows


# NOTA: "Reservas no Limite" NÃO usa mais a TTI_Portaria (portaria). O feed da
# raw.TTI parou em 07/04/2026 e o veículo reserva agora vem do Xbemre nativo da
# TQB_Monitoramento; o estoque de reserva vem do ST9_CadastroBem (statusBem='02'
# por contrato+lote). Por isso não há mais fetch_reservas_portaria — o KPI é
# calculado em kpis._reservas_limite(mon_rows, bem_rows). Ver kpis.py.


def fetch_tqr() -> list[dict]:
    """Catálogo de modelos (TQR) — dá a categoria do veículo (Pesada/Leve)
    por tecnologia. Join ST9_CadastroBem.tecnologia = TQR.TQR_TIPMOD.
    Ver kpis.py (_tipo_veiculo)."""
    sql = f"""
        SELECT TQR_TIPMOD, TQR_CATBEM, TQR_DESMOD
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.TQR`
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("TQR: %d linhas", len(rows))
    return rows
