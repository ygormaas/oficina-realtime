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
        import os
        from google.cloud import bigquery  # import tardio (modo mock/csv não precisa)

        # Autenticação, em ordem de preferência:
        #   1) GOOGLE_APPLICATION_CREDENTIALS_JSON = conteúdo do JSON da service
        #      account colado direto numa variável de ambiente. É o modo usado
        #      em hospedagem sem disco (ex.: Render), onde não há arquivo de chave.
        #   2) GOOGLE_APPLICATION_CREDENTIALS = caminho para o arquivo JSON
        #      (usado na máquina da TV, apontado pelo iniciar-painel-tv.bat), ou
        #      o login `gcloud auth application-default login`. Comportamento
        #      padrão do cliente — nada a fazer aqui.
        cred_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        if cred_json:
            import json
            from google.oauth2 import service_account
            info = json.loads(cred_json)
            creds = service_account.Credentials.from_service_account_info(info)
            _client = bigquery.Client(project=config.BQ_PROJECT, credentials=creds)
            log.info("Cliente BigQuery criado via GOOGLE_APPLICATION_CREDENTIALS_JSON (projeto %s)", config.BQ_PROJECT)
        else:
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
    Disponível / Trabalhando / Intervalo (bloco Mão de Obra). Ver kpis.py.

    Além do StatusFinal (que alimenta a CONTAGEM do card), traz o NOME
    (RA_NOMECMP), a função (RJ_DESC), o centro de custo (RA_CC) e os horários
    de turno (HoraEntrada/Saida 1 e 2) para o DETALHAMENTO "quem são" —
    _mecanicos_detalhe em kpis.py. A O.S./S.S. em que o mecânico trabalha vem
    de fetch_mecanicos_os (STL_Custo), não daqui."""
    sql = f"""
        SELECT RA_MAT, RA_NOMECMP, RJ_DESC, RA_CC, StatusFinal,
               HoraEntrada1, HoraSaida1, HoraEntrada2, HoraSaida2
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.SRA_SRJ_Funcionarios`
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("SRA_SRJ_Funcionarios: %d linhas", len(rows))
    return rows


def fetch_mecanicos_os() -> list[dict]:
    """Apontamento de mão de obra ABERTO por matrícula (STL_Custo): a O.S. e a
    S.S. em que cada mecânico está trabalhando AGORA.

    É a MESMA fonte que a view SRA usa para decidir o status 'Trabalhando'
    (mecânico está "ocupado"): apontamento `tipoReg='M'`, `seqrela='0'`, com a
    `ordem` entre as O.S. ainda abertas (join `key_filial_ordem_plano` com
    STJ_Manutencao). `STL_Custo.ordem` é o número de O.S. do painel; a `solici`
    da STJ_Manutencao é a S.S. Ver _mecanicos_detalhe em kpis.py."""
    sql = f"""
        SELECT DISTINCT STL.Matricula AS matricula, STL.ordem AS os,
               STJ.solici AS ss
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.STL_Custo` STL
        JOIN `{config.BQ_PROJECT}.{config.BQ_DATASET}.{config.BQ_VIEW_MANUTENCAO}` STJ
          ON STL.key_filial_ordem_plano = STJ.key_filial_ordem_plano
        WHERE STL.tipoReg = 'M' AND STL.seqrela = '0' AND STL.Matricula <> '00001'
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("STL_Custo (apontamento aberto): %d linhas", len(rows))
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


def fetch_oficina_externa() -> list[dict]:
    """Oficina externa (fornecedor) MAIS RECENTE por O.S.

    Oficinas externas são cadastradas como fornecedor. Os lançamentos de
    terceiro no STL_Custo (`localizacao_manutencao='EXTERNO'`) trazem
    `key_fornecedor_loja`; o nome vem de `SA2_Localizacao_Fornecedor`. Uma O.S.
    externa pode ter VÁRIAS oficinas (várias notas de terceiro) — pegamos a de
    atividade mais recente (dtInicioCompleto desc). Ver _oficina_ext em kpis.py."""
    sql = f"""
        SELECT ordem, oficina, cidade, estado, logradouro, numero, bairro, cep FROM (
          SELECT stl.ordem AS ordem, sa.nomeFornecedor AS oficina,
                 sa.cidade AS cidade, sa.estado AS estado,
                 saf.`end` AS logradouro, saf.nrEnd AS numero,
                 saf.bairro AS bairro, saf.cep AS cep,
                 ROW_NUMBER() OVER (
                   PARTITION BY stl.ordem
                   ORDER BY stl.dtInicioCompleto DESC, stl.dtFimCompleto DESC
                 ) AS rn
          FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.STL_Custo` stl
          JOIN `{config.BQ_PROJECT}.{config.BQ_DATASET}.SA2_Localizacao_Fornecedor` sa
            ON stl.key_fornecedor_loja = sa.key_fornecedor_loja
          LEFT JOIN `{config.BQ_PROJECT}.{config.BQ_DATASET}.SA2_Fornecedor` saf
            ON CONCAT(saf.cod, '-', saf.loja) = stl.key_fornecedor_loja
          WHERE stl.key_fornecedor_loja IS NOT NULL AND stl.key_fornecedor_loja <> '-'
            AND UPPER(stl.localizacao_manutencao) LIKE '%EXTERN%'
        )
        WHERE rn = 1
        LIMIT {config.BQ_MAX_ROWS}
    """
    rows = _rows(sql)
    log.info("Oficina externa (STL_Custo→SA2 + endereço): %d O.S.", len(rows))
    return rows


def fetch_historico_veiculo(cod_bem: str) -> list[dict]:
    """Histórico de manutenção do veículo: TODAS as O.S. do `codBem` na STJ
    (mais recentes primeiro), com placa/nome (ST9) e o custo total da O.S.
    (mão de obra + material + terceiro + ...). Consulta PARAMETRIZADA porque
    `cod_bem` vem da URL do endpoint. Ver historico_payload em kpis.py."""
    from google.cloud import bigquery
    sql = f"""
        SELECT stj.ORDEM, stj.SOLICI, stj.DTORIGI, stj.SERVICO,
               stj.SITUACA, stj.TERMINO, stj.OBSERVA, stj.DTMRFIM,
               (IFNULL(stj.CUSTMDO,0)+IFNULL(stj.CUSTMAT,0)+IFNULL(stj.CUSTMAA,0)+
                IFNULL(stj.CUSTMAS,0)+IFNULL(stj.CUSTTER,0)+IFNULL(stj.CUSTFER,0)) AS custo,
               st9.placa AS placa, st9.nome AS nome
        FROM `{config.BQ_PROJECT}.{config.BQ_DATASET}.STJ` stj
        LEFT JOIN `{config.BQ_PROJECT}.{config.BQ_DATASET}.ST9_CadastroBem` st9
          ON st9.bem = stj.CODBEM
        WHERE stj.CODBEM = @cod
        ORDER BY stj.DTORIGI DESC
        LIMIT 300
    """
    job = _get_client().query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("cod", "STRING", cod_bem)]))
    rows = [{k: _jsonable(v) for k, v in dict(r).items()} for r in job.result()]
    log.info("Histórico veículo %s: %d O.S.", cod_bem, len(rows))
    return rows
