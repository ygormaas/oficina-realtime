"""
MODELAGEM — transforma as linhas das views em KPIs do painel.
É o equivalente às suas medidas DAX: cada KPI é uma função pequena
com a regra comentada.

Fontes (schema REAL, validado com os CSVs de amostra de 10/07/2026):

  silver.STJ_Manutencao  →  a oficina AGORA (ordens em manutenção).
      Colunas usadas: ordem, solici, dtOrigem, NomeServico, codBem,
      situacao, termino, dtMpFim + horaMpFim (= "P.FIM MAN"),
      descricaoMobilizacao, xBemRes, localizacao_veiculo.

  silver.STJ             →  histórico completo de ordens.
      Usada só para PREVENTIVAS e RETORNO.
      Colunas usadas: ORDEM, SOLICI, CODBEM, SERVICO, SITUACA,
      TERMINO, DTORIGI, DTMPINI, DTMPFIM, XRETORN.

Regras de status validadas nos dados:
  · ordem ABERTA  = SITUACA/situacao ≠ 'C' (cancelada) e TERMINO/termino = 'N'
  · FORA DO PRAZO = aberta e agora > dtMpFim+horaMpFim  (o P.FIM MAN do protótipo)
  · tipo de serviço (código → nome): 000001 Corretiva · 000002 Sinistro ·
    000003 Preventiva · 000004 Implementação · 000005 Socorro

╔══════════════════════════════════════════════════════════════════════╗
║ LIMITES CONHECIDOS (documentados também no README):                  ║
║ · Não há coluna de PLACA nas views — o veículo é o codBem.           ║
║   O painel mostra "Bem NNNNN"; se existir um de-para bem→placa em    ║
║   outra tabela, dá para juntar aqui depois.                          ║
║ · "S.S. aguardando", "Clientes esp.", "Reservas no limite" e         ║
║   "Controle de qualidade" não têm coluna nas views — entram por      ║
║   env (KPI_*_MANUAL) até existir fonte. Veja config.py.              ║
║ · "Cláusula contratual" foi derivada como: fora do prazo E sem bem   ║
║   reserva apontado (xBemRes vazio). AJUSTE se a regra real diferir.  ║
╚══════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from . import config

# Fuso de Brasília — todas as comparações "agora × prazo" usam este fuso.
TZ_BR = timezone(timedelta(hours=-3))

# Código de serviço → nome exibido no painel
SERVICO_NOME = {
    "000001": "Corretiva",
    "000002": "Sinistro",
    "000003": "Preventiva",
    "000004": "Implementação",
    "000005": "Socorro",
}
# Ordem fixa das barras do bloco "Tipo de serviço"
TIPO_ORDEM = ["Implementação", "Corretiva", "Sinistro", "Preventiva", "Socorro"]

# Normalização de nomes vindos da coluna NomeServico (sem acento na fonte)
NOME_SERVICO_MAP = {
    "CORRETIVA": "Corretiva", "SINISTRO": "Sinistro", "PREVENTIVA": "Preventiva",
    "IMPLEMENTACAO": "Implementação", "IMPLEMENTAÇÃO": "Implementação",
    "SOCORRO": "Socorro",
}


# ============================ utilitários =================================

def _norm(v: Any) -> str:
    return str(v).strip().upper() if v is not None else ""


def _vazio(v: Any) -> bool:
    return v is None or str(v).strip() in ("", "0", "nan", "None", "NaN")


def _dt_iso(v: Any) -> datetime | None:
    """dtOrigem vem como '2026-07-10 00:00:00,000' ou ISO; DBs mandam datetime."""
    if _vazio(v):
        return None
    if isinstance(v, datetime):
        d = v
    else:
        s = str(v).strip().replace(",", ".")
        try:
            d = datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=TZ_BR)


def _dt_compacta(data: Any, hora: Any = None) -> datetime | None:
    """Datas no formato do ERP: '20260710' + hora 'HH:MM' opcional."""
    s = str(data).strip() if data is not None else ""
    if len(s) != 8 or not s.isdigit():
        return _dt_iso(data)  # algumas colunas podem vir já em ISO
    h = str(hora).strip() if hora and str(hora).strip() else "00:00"
    try:
        return datetime.strptime(s + " " + h[:5], "%Y%m%d %H:%M").replace(tzinfo=TZ_BR)
    except ValueError:
        return datetime.strptime(s, "%Y%m%d").replace(tzinfo=TZ_BR)


def _fmt_curta(d: datetime | None) -> str:
    return d.strftime("%d/%m %H:%M") if d else "—"


def _nome_servico(row: dict) -> str:
    nome = _norm(row.get("NomeServico"))
    if nome in NOME_SERVICO_MAP:
        return NOME_SERVICO_MAP[nome]
    return SERVICO_NOME.get(str(row.get("servico") or row.get("SERVICO") or "").strip(),
                            nome.title() or "Não informado")


# ==================== regras sobre STJ_Manutencao =========================

def _aberta_man(row: dict) -> bool:
    """Aberta = não cancelada e sem término (validado: 46/46 na amostra)."""
    return _norm(row.get("situacao")) != "C" and _norm(row.get("termino")) == "N"


def _prazo_fim(row: dict) -> datetime | None:
    """P.FIM MAN = dtMpFim + horaMpFim (100% preenchido na amostra)."""
    return _dt_compacta(row.get("dtMpFim"), row.get("horaMpFim"))


def _mobilizado(row: dict) -> bool:
    """descricaoMobilizacao: 'Veículo Mobilizado' / 'Veículo Não Mobilizado'."""
    return "NÃO" not in _norm(row.get("descricaoMobilizacao")) and \
           "NAO" not in _norm(row.get("descricaoMobilizacao"))


def _sem_reserva(row: dict) -> bool:
    """xBemRes vazio = nenhum bem reserva apontado para o veículo."""
    return _vazio(row.get("xBemRes"))


def _linha_detalhe(row: dict, situacao: str) -> dict:
    """Uma linha da tabela de drill-down (contrato do frontend)."""
    ab = _dt_iso(row.get("dtOrigem"))
    bem = str(row.get("codBem") or "").strip()
    return {
        "abertura":    _fmt_curta(ab),
        "aberturaIso": ab.isoformat() if ab else None,
        "ss":          str(row.get("solici") or "—"),
        "os":          str(row.get("ordem") or "—"),
        "placa":       ("Bem " + bem) if bem else "—",   # sem coluna de placa na view
        "mobil":       "Mobilizado" if _mobilizado(row) else "Não mobilizado",
        "serv":        _nome_servico(row),
        "st":          situacao,
    }


def _ordenar_por_abertura(linhas: list[dict]) -> list[dict]:
    return sorted(linhas, key=lambda r: r["aberturaIso"] or "9999")


# ======================== regras sobre STJ (histórico) =====================

def _aberta_stj(row: dict) -> bool:
    return _norm(row.get("SITUACA")) == "L" and _norm(row.get("TERMINO")) == "N"


def _preventivas(stj_rows: list[dict], agora: datetime) -> dict:
    """
    Preventivas = ordens de plano (SERVICO 000003) abertas, classificadas
    pela janela dtMpIni → dtMpFim:
      · Atrasada        → a janela já fechou (fim < hoje)
      · Período final   → hoje está na 2ª metade da janela
      · Período inicial → hoje está na 1ª metade da janela

    IMPORTANTE: a amostra tem 1.081 preventivas com janela vencida em 2024
    (resíduo de plano antigo nunca encerrado). Para o KPI não virar ruído,
    "atrasadas" só conta janelas vencidas há no máximo PREV_RETRO_DIAS
    (config, padrão 90). Suba esse valor se quiser ver o backlog inteiro.
    """
    corte = agora - timedelta(days=config.PREV_RETRO_DIAS)
    atrasadas = final = inicial = 0
    for r in stj_rows:
        if str(r.get("SERVICO") or "").strip() != "000003" or not _aberta_stj(r):
            continue
        ini = _dt_compacta(r.get("DTMPINI"))
        fim = _dt_compacta(r.get("DTMPFIM"))
        if not fim:
            continue
        if fim < agora:
            if fim >= corte:
                atrasadas += 1
        elif ini and ini <= agora:
            meio = ini + (fim - ini) / 2
            if agora >= meio:
                final += 1
            else:
                inicial += 1
    return {"atrasadas": atrasadas, "final": final, "inicial": inicial}


def _retorno(stj_rows: list[dict]) -> int:
    """Retorno = ordens abertas com XRETORN preenchido (retrabalho).
    Se KPI_RETORNO_MANUAL > 0 no .env, o valor manual prevalece."""
    auto = sum(1 for r in stj_rows if _aberta_stj(r) and not _vazio(r.get("XRETORN")))
    return config.KPI_RETORNO_MANUAL if config.KPI_RETORNO_MANUAL > 0 else auto


# ============================ payload final ================================

def build_payload(man_rows: list[dict], stj_rows: list[dict],
                  agora: datetime | None = None) -> dict:
    """
    Recebe as linhas das DUAS views e devolve o JSON que o painel consome.
    Este é o CONTRATO com o frontend — mudou uma chave aqui, mude também
    no Resumo_Oficina.dc.html.
    """
    agora = agora or datetime.now(TZ_BR)

    abertas    = [r for r in man_rows if _aberta_man(r)]
    fora_prazo = [r for r in abertas
                  if (_prazo_fim(r) is not None and agora > _prazo_fim(r))]
    sos        = [r for r in abertas if _nome_servico(r) == "Socorro"]
    clausula   = [r for r in fora_prazo if _sem_reserva(r)]  # AJUSTE se a regra real diferir

    # --- Tipo de serviço (contagem nas ordens da oficina) -------------------
    contagem: dict[str, int] = {}
    for r in abertas:
        k = _nome_servico(r)
        contagem[k] = contagem.get(k, 0) + 1
    tipos = [{"k": k, "n": contagem.pop(k)} for k in TIPO_ORDEM if k in contagem]
    tipos += [{"k": k, "n": n} for k, n in sorted(contagem.items(), key=lambda x: -x[1])]

    # --- Idade das O.S. abertas (aging por dtOrigem) -------------------------
    aging = {"d0_2": 0, "d3_7": 0, "d8_30": 0, "d30p": 0}
    for r in abertas:
        ab = _dt_iso(r.get("dtOrigem"))
        if not ab:
            continue
        dias = (agora - ab).days
        if dias <= 2:    aging["d0_2"] += 1
        elif dias <= 7:  aging["d3_7"] += 1
        elif dias <= 30: aging["d8_30"] += 1
        else:            aging["d30p"] += 1

    prev = _preventivas(stj_rows, agora)

    # --- Drill-downs ----------------------------------------------------------
    def _st(r):
        p = _prazo_fim(r)
        return "Fora do Prazo" if (p and agora > p) else ("No prazo" if p else "Sem SLA")

    detalhes = {
        "osForaPrazo": _ordenar_por_abertura([_linha_detalhe(r, "Fora do Prazo") for r in fora_prazo]),
        "osAbertas":   _ordenar_por_abertura([_linha_detalhe(r, _st(r)) for r in abertas]),
        "sos":         [_linha_detalhe(r, "Crítico") for r in sos],
        "clausula":    [_linha_detalhe(r, "Crítico") for r in clausula],
        # Sem fonte automática nas views atuais (valores via .env):
        "ssAguardando": [], "clientesEsp": [], "reservaLimite": [],
        "qualidade": [], "retorno": [],
    }

    return {
        "geradoEm": agora.isoformat(),
        "kpis": {
            "ssAguardando":  config.KPI_SS_AGUARDANDO_MANUAL,
            "osAbertas":     len(abertas),
            "osForaPrazo":   len(fora_prazo),
            "qualidade":     config.KPI_QUALIDADE_MANUAL,
            "retorno":       _retorno(stj_rows),
            "clientesEsp":   config.KPI_CLIENTES_ESP_MANUAL,
            "clausula":      len(clausula),
            "reservaLimite": config.KPI_RESERVA_LIMITE_MANUAL,
            "sos":           len(sos),
            "prevAtrasadas": prev["atrasadas"],
            "prevFinal":     prev["final"],
            "prevInicial":   prev["inicial"],
        },
        "mecanicos": {
            "trabalhando": config.MECANICOS_TRABALHANDO,
            "disponivel":  config.MECANICOS_DISPONIVEL,
            "pausa":       config.MECANICOS_PAUSA,
        },
        "tipoServico": tipos,
        "aging": aging,
        "detalhes": detalhes,
    }
