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

  silver.TQB_Monitoramento → monitoramento de SLA por ordem (join por
      ordem/ordemSTJ com STJ_Manutencao). Colunas usadas: Xesper (cliente
      esperando: 'S'/'N'/vazio — validado contra dado real em 20/07/2026),
      Xreser (veículo reserva dado: 'S'/'N' — substitui xBemRes, que vem
      sempre vazio na STJ_Manutencao), SLAVencimentoOS/SLAVencimentoCC.

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
║ · "Clientes esp." agora vem de TQB_Monitoramento.Xesper='S' —        ║
║   validado 1:1 contra a operação real em 20/07/2026 (bateu 3).       ║
║ · "S.S. aguardando", "Reservas no limite", "Controle de qualidade"   ║
║   e o efetivo de mecânicos (trabalhando/disponível/pausa) NÃO têm    ║
║   fonte automática confirmada — varri as ~50 views do dataset        ║
║   `silver` e nenhuma bate com segurança. Seguem por env              ║
║   (KPI_*_MANUAL / MECANICOS_*) até alguém do time de oficina indicar ║
║   a tabela certa. Veja config.py.                                    ║
║ · "Cláusula contratual" = fora do prazo E sem veículo reserva dado   ║
║   (Xreser='N', de TQB_Monitoramento — substituiu xBemRes, que vem    ║
║   sempre vazio na STJ_Manutencao). O critério de "fora do prazo" em  ║
║   si (dtMpFim/horaMpFim) NÃO foi validado contra a operação real:    ║
║   em 20/07/2026 a tela real mostrava 0 e esta regra calculou ~96 —   ║
║   dtMpFim parece ser a janela de mão de obra, não o prazo do        ║
║   cliente. TQB_Monitoramento.SLAVencimentoOS/CC também não bateram   ║
║   ao recalcular ao vivo (~108). PRECISA de confirmação do time antes ║
║   de confiar neste número no painel.                                 ║
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

# Serviços SEM obrigação de prazo (definido pela operação em 22/07/2026): não
# entram no KPI "O.S. fora do prazo" nem são classificados como tal — aparecem
# como "Sem prazo". Sinistro depende de terceiros/seguradora e Implementação é
# preparação de veículo novo, então o SLA da O.S. não se aplica.
# (A regra de Cláusula contratual já ignorava Implementação por motivo análogo.)
SERVICOS_SEM_SLA = {"Sinistro", "Implementação"}

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
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


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


def _monitoramento_por_ordem(mon_rows: list[dict]) -> dict[str, dict]:
    """Indexa TQB_Monitoramento por número de ordem para juntar com STJ_Manutencao."""
    return {str(r["ordemSTJ"]).strip(): r for r in mon_rows if not _vazio(r.get("ordemSTJ"))}


def _sem_reserva(row: dict, mon: dict | None) -> bool:
    """Sem veículo reserva dado = Xreser='N' (TQB_Monitoramento).
    Sem cruzamento, cai para xBemRes (STJ_Manutencao) — que na prática
    vem sempre vazio, então isso é só um fallback defensivo."""
    if mon is not None and not _vazio(mon.get("Xreser")):
        return _norm(mon.get("Xreser")) == "N"
    return _vazio(row.get("xBemRes"))


def _cliente_esperando(mon: dict | None) -> bool:
    """Xesper='S' (TQB_Monitoramento) — validado contra a operação real."""
    return mon is not None and _norm(mon.get("Xesper")) == "S"


# --------- CLÁUSULA CONTRATUAL (regra decifrada com o time em 21/07/2026) ------
# O card "Cláusula Contratual" do Power BI = medida Claus_Contrato_Fora_prazo.
# Reproduzido cruzando o export do card com a base:
#   1) SLAUltrapassadoCC = 'Fora do Prazo'   (SLA da cláusula estourado)
#   2) serviço ≠ Implementação               (implementação não conta cláusula)
#   3) o contrato da OS TEM cláusula de SLA   (SZT_Contratos.Sla preenchido)
# Obs.: o card do Power BI é uma medida AO VIVO e a coluna SLAUltrapassadoCC
# é um snapshot da ingestão, então o total fica próximo (não idêntico) ao card.

def _nome_servico_mon(mon: dict) -> str:
    """Serviço a partir do nmServ da TQB_Monitoramento (sem acento na fonte)."""
    nome = _norm(mon.get("nmServ"))
    return NOME_SERVICO_MAP.get(nome, nome.title() or "Não informado")


def _mobilizado_mon(mon: dict) -> bool:
    s = _norm(mon.get("StatusMobilizacao"))
    return "NÃO" not in s and "NAO" not in s


def _num(v: Any) -> int | None:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def _qtd_zero(row: dict) -> bool:
    """Filtro-mestre de 'O.S. aberta' do painel = qtdRep = 0 (validado com o
    manutest.vpax; substitui a heurística situacao/termino)."""
    return _num(row.get("qtdRep")) == 0


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _sla_fora(mon: dict, campo: str, agora: datetime) -> bool:
    """Fora do prazo calculado AO VIVO: agora > data de vencimento do SLA.
    Usa SLAVencimentoOS / SLAVencimentoCC (recalculado a cada ciclo) em vez do
    flag SLAUltrapassado* — que é um snapshot congelado no momento da ingestão.
    Vencimento nulo => nunca está fora do prazo."""
    dt = _dt_iso(mon.get(campo))
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BR)
    return agora > dt


def _preventivas_status(prev_rows: list[dict]) -> dict:
    """Preventivas = BENS DISTINTOS por statusManutencao (STF_Status_Manutencao).
    Regra do manutest: DISTINCTCOUNT(codBem) por status."""
    buckets = {"Atrasado": set(), "Período Final": set(), "Período Inicial": set()}
    for r in prev_rows or []:
        st, bem = _s(r.get("statusManutencao")), _s(r.get("codBem"))
        if st in buckets and bem:
            buckets[st].add(bem)
    return {"atrasadas": len(buckets["Atrasado"]),
            "final":     len(buckets["Período Final"]),
            "inicial":   len(buckets["Período Inicial"])}


def _mecanicos_efetivo(mec_rows: list[dict] | None) -> dict | None:
    """Efetivo por StatusFinal (SRA_SRJ_Funcionarios), matrículas distintas.
    None se não houver dados (o chamador cai para o .env)."""
    if not mec_rows:
        return None
    def cnt(status: str) -> int:
        alvo = _norm(status)
        return len({_s(r.get("RA_MAT")) for r in mec_rows
                    if _norm(r.get("StatusFinal")) == alvo and _s(r.get("RA_MAT"))})
    return {"trabalhando": cnt("Trabalhando"),
            "disponivel":  cnt("Disponível"),
            "pausa":       cnt("Intervalo")}


def _reservas_limite(tti_rows: list[dict] | None,
                     bem_rows: list[dict] | None) -> list[dict] | None:
    """Reservas no Limite = medida DAX Qtd_Res_Limite (validado =2).

    Devolve os GRUPOS no limite (contrato/ordem/tecnologia + veículos); a medida
    é o len() da lista. Devolver os grupos — e não só a contagem — é o que
    alimenta o drill-down do card.

    Agrupa TTI_Portaria por (numeroContrato, reserva, statusBem, ordem,
    tecnologia) e conta os grupos que são uma reserva EM USO
    (numeroContrato<>'', reserva='S', statusBem='02', tecnologia<>'', ordem<>'')
    e que NÃO têm nenhuma reserva DISPONÍVEL do mesmo contrato+tecnologia+status
    — Qtd_Res_Disp=0 (bem distinto com ordem='', dtSai='', reserva='S' e
    ST9_CadastroBem.statusBem='02'). None se não houver dados (cai para .env)."""
    if not tti_rows:
        return None
    st9_status = {_s(b.get("bem")): _s(b.get("statusBem")) for b in (bem_rows or [])}

    def qtd_res_disp(contrato: str, tec: str, tti_status: str) -> int:
        bems = set()
        for r in tti_rows:
            if _s(r.get("dtSai")) != "" or _s(r.get("ordem")) != "":
                continue
            if _s(r.get("reserva")) != "S":
                continue
            if _s(r.get("numeroContrato")) != contrato or _s(r.get("tecnologia")) != tec:
                continue
            if _s(r.get("statusBem")) != tti_status:
                continue
            bem = _s(r.get("codVei"))
            if st9_status.get(bem) == "02":
                bems.add(bem)
        return len(bems)

    grupos = {(_s(r.get("numeroContrato")), _s(r.get("reserva")), _s(r.get("statusBem")),
               _s(r.get("ordem")), _s(r.get("tecnologia"))) for r in tti_rows}
    no_limite = []
    for contrato, reserva, status, ordem, tec in sorted(grupos):
        if not (contrato and reserva == "S" and status == "02" and tec and ordem):
            continue
        if qtd_res_disp(contrato, tec, status) != 0:
            continue
        veiculos = {_s(r.get("codVei")) for r in tti_rows
                    if _s(r.get("numeroContrato")) == contrato
                    and _s(r.get("reserva")) == "S"
                    and _s(r.get("statusBem")) == status
                    and _s(r.get("ordem")) == ordem
                    and _s(r.get("tecnologia")) == tec
                    and _s(r.get("codVei"))}
        no_limite.append({"contrato": contrato, "ordem": ordem,
                          "tecnologia": tec, "veiculos": sorted(veiculos)})
    return no_limite


# Categoria "Pesada" no catálogo TQR (TQR_CATBEM). MAPEAMENTO INFERIDO
# (o rótulo Pesada/Leve não existe no modelo; '4' bateu com o painel).
# Ajuste aqui se a equipe confirmar outro código.
CATBEM_PESADA = {"4"}


def _tipo_veiculo(abertas: list[dict], bem_por_cod: dict, tqr_rows: list[dict] | None) -> dict | None:
    """Pesada/Leve dos veículos abertos (bens distintos). Categoria vem de
    TQR.TQR_CATBEM via ST9_CadastroBem.tecnologia = TQR.TQR_TIPMOD.
    None se não houver o catálogo TQR."""
    if not tqr_rows:
        return None
    cat_por_tec = {_s(r.get("TQR_TIPMOD")): _s(r.get("TQR_CATBEM")) for r in tqr_rows}
    pesada, leve = set(), set()
    for r in abertas:
        bem = _s(r.get("codBem"))
        if not bem:
            continue
        b = bem_por_cod.get(bem)
        cat = cat_por_tec.get(_s(b.get("tecnologia")) if b else "", "")
        (pesada if cat in CATBEM_PESADA else leve).add(bem)
    return {"pesada": len(pesada), "leve": len(leve)}


def _placa_nome(bem: str, bem_idx: dict | None) -> tuple[str, str]:
    """Placa e nome do veículo a partir do ST9_CadastroBem (indexado por bem).
    Sem placa cadastrada, cai para 'Bem N'."""
    info = (bem_idx or {}).get(bem) or {}
    placa = _s(info.get("placa"))
    nome = _s(info.get("nome"))
    if not placa:
        placa = ("Bem " + bem) if bem else "—"
    return placa, nome


def _contrato_do_bem(bem: str, bem_idx: dict | None) -> str:
    """Contrato a que o veículo pertence (ST9_CadastroBem.numeroContrato).
    Confere com o TQB.Xcontr em 100% das ordens abertas; usamos o cadastro do
    bem por ser o dado do veículo, não da O.S."""
    return _s(((bem_idx or {}).get(bem) or {}).get("contrato"))


def _servico_da_ordem(mon: dict | None, man_por_ordem: dict | None) -> str:
    """Serviço da ordem, preferindo o STJ à TQB.

    Em 3 ordens abertas as duas fontes divergem (ex.: O.S. 037941 tem
    servico='000002' e NomeServico='SINISTRO' no STJ, mas nmServ='Preventiva'
    na TQB). O STJ manda: é ele que carrega o CÓDIGO do serviço. Usar a mesma
    fonte aqui e na coluna "Tipo" evita a linha dizer um serviço e a situação
    ser calculada por outro."""
    row = (man_por_ordem or {}).get(_s((mon or {}).get("ordemSTJ")))
    if row is not None:
        return _nome_servico(row)
    return _nome_servico_mon(mon) if mon else ""


def _situacao_real(mon: dict | None, agora: datetime, servico: str = "") -> str:
    """Situação da linha vinda das COLUNAS da fonte, não de um rótulo fixo por
    drill-down (o que fazia toda linha de "O.S. abertas" aparecer como 'Aberta').

    Nenhuma coluna de status distingue as ordens abertas entre si — `situacao`
    do STJ é 'L' em todas e `StatusOS` é 'Aberta' em todas. O que de fato varia
    é o SLA. Então:
      - `StatusOS` quando ele diz algo além de "Aberta" (ex.: 'Aguardando
        Abertura', nas S.S. que ainda não viraram O.S.);
      - senão, o SLA da O.S. recalculado AO VIVO (agora > SLAVencimentoOS) —
        a MESMA regra do KPI "O.S. fora do prazo", para o detalhamento bater
        com o número do card em vez do flag-snapshot SLAUltrapassadoOS;
      - sem monitoramento, 'Sem SLA'.
    """
    if not mon:
        return "Sem SLA"
    status = _s(mon.get("StatusOS"))
    if status and "ABERTA" not in _norm(status):
        return status
    if (servico or _nome_servico_mon(mon)) in SERVICOS_SEM_SLA:
        return "Sem prazo"
    if _dt_iso(mon.get("SLAVencimentoOS")) is None:
        return "Sem SLA"
    return "Fora do Prazo" if _sla_fora(mon, "SLAVencimentoOS", agora) else "No prazo"


def _previsao_entrega(row: dict | None, agora: datetime) -> tuple[str, bool]:
    """Previsão de entrega da O.S. — STJ `dtMpFim` + `horaMpFim` (fim previsto
    da manutenção). É o único par de datas previstas preenchido na base: os
    dtPp*/dtPr* vêm vazios, e os dtMr* só são gravados no fechamento.

    `dtMpFim` chega como 'AAAAMMDD' e `horaMpFim` como 'HH:MM'. Devolve
    (texto formatado, já_venceu) — venceu = previsão no passado com a O.S.
    ainda aberta."""
    if not row:
        return "", False
    d = _s(row.get("dtMpFim"))
    if len(d) != 8 or not d.isdigit():
        return "", False
    h = _s(row.get("horaMpFim")) or "00:00"
    try:
        prev = datetime.strptime(f"{d} {h[:5]}", "%Y%m%d %H:%M").replace(tzinfo=TZ_BR)
    except ValueError:
        return "", False
    return prev.strftime("%d/%m/%Y %H:%M"), prev < agora


def _descricao_servico(row: dict) -> str:
    """Descrição do serviço (STJ `observa`, o TJ_OBSERVA do ERP).

    Texto livre digitado na abertura da O.S.: vem com quebras de linha e corridas
    de espaço/traço usadas como separador visual no ERP. Aqui só o espaçamento é
    normalizado — o conteúdo não é editado, e o corte visual fica no frontend."""
    txt = " ".join(str(row.get("observa") or "").split())
    return txt.strip(" -")


def _reserva_de_mon(mon: dict | None, bem_idx: dict | None) -> tuple[str, str, str]:
    """Veículo reserva que substitui o que está parado, a partir da TQB:
    `Xbemre` é o bem da reserva e `Xreser` o pedido de reserva.

    Devolve (placa, nome, situação), com situação em:
      'designada'  — reserva com veículo definido (Xbemre preenchido)
      'aguardando' — reserva pedida (Xreser='S') mas ainda sem veículo
      ''           — nenhuma reserva pedida
    A distinção importa: 'aguardando' é uma lacuna operacional, não um vazio."""
    if not mon:
        return "", "", ""
    bem = _s(mon.get("Xbemre"))
    if bem:
        placa, nome = _placa_nome(bem, bem_idx)
        return placa, nome, "designada"
    if _norm(mon.get("Xreser")) == "S":
        return "", "", "aguardando"
    return "", "", ""


def _detalhe_de_mon(mon: dict, bem_idx: dict | None = None,
                    man_por_ordem: dict | None = None,
                    agora: datetime | None = None) -> dict:
    """Linha de drill-down a partir da TQB_Monitoramento (mesmo contrato do
    frontend que _linha_detalhe, mas com os campos do monitoramento).

    A previsão de entrega mora no STJ, por isso `man_por_ordem`: sem a ordem
    correspondente (caso das S.S. que ainda não viraram O.S.) ela sai vazia."""
    ab = _dt_iso(mon.get("DataHoraAbertura"))
    if ab and ab.tzinfo:
        ab = ab.astimezone(TZ_BR)
    placa, nome = _placa_nome(str(mon.get("Codbem") or "").strip(), bem_idx)
    resPlaca, resNome, resSt = _reserva_de_mon(mon, bem_idx)
    prevTxt, prevAtraso = _previsao_entrega(
        (man_por_ordem or {}).get(_s(mon.get("ordemSTJ"))), agora or datetime.now(TZ_BR))
    servico = _servico_da_ordem(mon, man_por_ordem)
    return {
        "abertura":    _fmt_curta(ab),
        "aberturaIso": ab.isoformat() if ab else None,
        "ss":          str(mon.get("Solici") or "—"),
        "os":          str(mon.get("ordemSTJ") or "—"),
        "placa":       placa,
        "nome":        nome,
        "contrato":    _contrato_do_bem(str(mon.get("Codbem") or "").strip(), bem_idx),
        "reserva":     resPlaca,
        "reservaNome": resNome,
        "reservaSt":   resSt,
        "desc":        "",   # a descrição mora no STJ; estas linhas vêm da TQB
        "previsao":    prevTxt,
        "previsaoAtrasada": prevAtraso,
        "mobil":       "Mobilizado" if _mobilizado_mon(mon) else "Não mobilizado",
        "serv":        servico,
        "st":          _situacao_real(mon, agora or datetime.now(TZ_BR), servico),
    }


def _linha_detalhe(row: dict, bem_idx: dict | None = None,
                   mon_por_ordem: dict | None = None,
                   agora: datetime | None = None) -> dict:
    """Uma linha da tabela de drill-down (contrato do frontend).

    A reserva mora na TQB, não no STJ — por isso `mon_por_ordem`, para achar o
    monitoramento da mesma ordem. Sem ele, a coluna de reserva sai vazia."""
    ab = _dt_iso(row.get("dtOrigem"))
    placa, nome = _placa_nome(str(row.get("codBem") or "").strip(), bem_idx)
    mon = (mon_por_ordem or {}).get(_s(row.get("ordem")))
    resPlaca, resNome, resSt = _reserva_de_mon(mon, bem_idx)
    prevTxt, prevAtraso = _previsao_entrega(row, agora or datetime.now(TZ_BR))
    return {
        "abertura":    _fmt_curta(ab),
        "aberturaIso": ab.isoformat() if ab else None,
        "ss":          str(row.get("solici") or "—"),
        "os":          str(row.get("ordem") or "—"),
        "placa":       placa,
        "nome":        nome,
        "contrato":    _contrato_do_bem(str(row.get("codBem") or "").strip(), bem_idx),
        "reserva":     resPlaca,
        "reservaNome": resNome,
        "reservaSt":   resSt,
        "desc":        _descricao_servico(row),
        "previsao":    prevTxt,
        "previsaoAtrasada": prevAtraso,
        "mobil":       "Mobilizado" if _mobilizado(row) else "Não mobilizado",
        "serv":        _nome_servico(row),
        "st":          _situacao_real(mon, agora or datetime.now(TZ_BR), _nome_servico(row)),
    }


def _detalhes_reserva(grupos: list[dict], man_por_ordem: dict,
                      bem_idx: dict | None = None,
                      mon_por_ordem: dict | None = None,
                      agora: datetime | None = None) -> list[dict]:
    """Linhas do drill-down de "Reservas no limite". A TTI_Portaria não guarda
    data de entrada, então a abertura vem da O.S. do grupo (TTI.ordem =
    STJ_Manutencao.ordem). Sem O.S. correspondente, monta a linha só com o que
    a portaria sabe — e ela cai no fim da ordenação, por não ter data."""
    linhas = []
    for g in grupos:
        row = man_por_ordem.get(g["ordem"])
        if row is not None:
            linhas.append(_linha_detalhe(row, bem_idx, mon_por_ordem, agora))
            continue
        bem = g["veiculos"][0] if g["veiculos"] else ""
        placa, nome = _placa_nome(bem, bem_idx)
        linhas.append({
            "abertura": "—", "aberturaIso": None,
            "ss": "—", "os": g["ordem"] or "—",
            "placa": placa, "nome": nome, "contrato": _contrato_do_bem(bem, bem_idx),
            "reserva": "", "reservaNome": "", "reservaSt": "", "desc": "",
            "previsao": "", "previsaoAtrasada": False,
            "mobil": "Mobilizado", "serv": "—", "st": "Sem SLA",
        })
    return linhas


def _ordenar_por_abertura(linhas: list[dict], desc: bool = False) -> list[dict]:
    """Ordena o drill-down pela data de abertura. desc=True põe a mais recente
    primeiro. Linhas sem data ficam sempre no fim, nos dois sentidos."""
    com = [r for r in linhas if r["aberturaIso"]]
    sem = [r for r in linhas if not r["aberturaIso"]]
    com.sort(key=lambda r: r["aberturaIso"], reverse=desc)
    return com + sem


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

def build_payload(man_rows: list[dict],
                  stj_rows: list[dict] | None = None,
                  mon_rows: list[dict] | None = None,
                  bem_rows: list[dict] | None = None,
                  mecanicos_rows: list[dict] | None = None,
                  prev_rows: list[dict] | None = None,
                  tti_rows: list[dict] | None = None,
                  tqr_rows: list[dict] | None = None,
                  ss_rows: list[dict] | None = None,
                  agora: datetime | None = None) -> dict:
    """
    Devolve o JSON que o painel consome. As REGRAS seguem as medidas DAX do
    painel de referência (manutest.vpax): o filtro-mestre de 'O.S. aberta' é
    qtdRep=0. Este é o CONTRATO com o frontend — mudou uma chave aqui, mude
    também no Resumo_Oficina.dc.html.

    Junções (chaves do modelo Power BI):
      STJ_Manutencao.ordem   = TQB_Monitoramento.ordemSTJ
      TQB_Monitoramento.Codbem = ST9_CadastroBem.bem
    """
    agora = agora or datetime.now(TZ_BR)
    mon_rows = mon_rows or []
    bem_rows = bem_rows or []

    mon_por_ordem = {_s(m.get("ordemSTJ")): m for m in mon_rows if _s(m.get("ordemSTJ"))}
    man_por_ordem = {_s(r.get("ordem")): r for r in man_rows if _s(r.get("ordem"))}
    bem_por_cod   = {_s(b.get("bem")): b for b in bem_rows if _s(b.get("bem"))}
    # placa + nome do veículo por bem (para os drill-downs)
    bem_idx = {_s(b.get("bem")): {"placa": _s(b.get("placa")), "nome": _s(b.get("nome")),
                                  "contrato": _s(b.get("numeroContrato"))}
               for b in bem_rows if _s(b.get("bem"))}

    abertas = [r for r in man_rows if _qtd_zero(r)]                 # qtdRep = 0
    abertas_ordens = {_s(r.get("ordem")) for r in abertas if _s(r.get("ordem"))}

    # --- OS Fora do Prazo (SLA da OS estourado AO VIVO, sobre as abertas) ----
    # Sinistro e Implementação não têm obrigação de prazo — ficam fora da conta
    # (ver SERVICOS_SEM_SLA). Isso desvia de propósito do DAX do manutest, que
    # contava todos os serviços.
    os_fora = [m for m in mon_rows
               if _s(m.get("ordemSTJ")) in abertas_ordens
               and _servico_da_ordem(m, man_por_ordem) not in SERVICOS_SEM_SLA
               and _sla_fora(m, "SLAVencimentoOS", agora)]

    # --- S.O.S (serviço 000005) ---------------------------------------------
    sos = [r for r in abertas if _s(r.get("servico")) == "000005"]

    # --- Clientes esperando (bens distintos, Xesper='S') --------------------
    clientes_bem, clientes_rows = set(), []
    for r in abertas:
        m = mon_por_ordem.get(_s(r.get("ordem")))
        if m and _norm(m.get("Xesper")) == "S" and _s(r.get("ordem")):
            if _s(r.get("codBem")) not in clientes_bem:
                clientes_rows.append(m)
            clientes_bem.add(_s(r.get("codBem")))

    # --- S.S. aguardando (TQB: StatusOS não contém "Aberta") ----------------
    # Vem de uma consulta própria (fetch_ss_aguardando): essas linhas têm
    # termino NULL — a S.S. ainda não virou O.S. — e o mon_rows, filtrado por
    # termino='N', nunca as traria. Sem a fonte, cai para o filtro sobre mon_rows.
    if ss_rows is not None:
        ss_aguardando = list(ss_rows)
    else:
        ss_aguardando = [m for m in mon_rows if "ABERTA" not in _norm(m.get("StatusOS"))]

    # --- Controle de qualidade (tipoRet = 'A') ------------------------------
    qualidade = [r for r in man_rows if _norm(r.get("tipoRet")) == "A"]

    # --- Retorno (qtdRep=0 e xRetorn = '1') ---------------------------------
    retorno = [r for r in abertas if _s(r.get("xRetorn")) == "1"]

    # --- Cláusula contratual (bens distintos — DAX Claus_Contrato_Fora_prazo)
    # SLAUltrapassadoCC fora + bem com contrato no cadastro + xss vazio +
    # serviço ≠ implementação + statusBem do bem ∉ {08,02} + qtdRep=0.
    clausula_bem, clausula_rows = set(), []
    for r in abertas:
        m = mon_por_ordem.get(_s(r.get("ordem")))
        if not m or not _sla_fora(m, "SLAVencimentoCC", agora):
            continue
        if _s(m.get("xss")) != "" or _norm(m.get("nmServ")) == "IMPLEMENTACAO":
            continue
        b = bem_por_cod.get(_s(r.get("codBem")))
        if not b or _s(b.get("numeroContrato")) == "" or _s(b.get("statusBem")) in ("08", "02"):
            continue
        cod = _s(r.get("codBem"))
        if cod not in clausula_bem:
            clausula_rows.append(m)
        clausula_bem.add(cod)

    # --- Veículos mobilizados / não (bens distintos) ------------------------
    veic_mob = set()
    for r in abertas:
        m = mon_por_ordem.get(_s(r.get("ordem")))
        if m and _s(m.get("Xcontr")) != "":
            veic_mob.add(_s(r.get("codBem")))
    veic_nmob = set()
    for m in mon_rows:
        r = man_por_ordem.get(_s(m.get("ordemSTJ")))
        if r and _qtd_zero(r) and _s(m.get("Xcontr")) == "":
            veic_nmob.add(_s(m.get("Codbem")))

    # --- Localização dos veículos (bens distintos, sobre as abertas) --------
    loc_int, loc_ext = set(), set()
    for r in abertas:
        lv, bem = _norm(r.get("localizacao_veiculo")), _s(r.get("codBem"))
        if not bem:
            continue
        if "EXTERNA" in lv:
            loc_ext.add(bem)
        elif "INTERNA" in lv:
            loc_int.add(bem)

    # --- Tipo de veículo (Pesada/Leve) sobre os abertos --------------------
    tipo_veic = _tipo_veiculo(abertas, bem_por_cod, tqr_rows) or {"pesada": 0, "leve": 0}

    # --- Tipo de serviço (nas O.S. abertas) ---------------------------------
    contagem: dict[str, int] = {}
    for r in abertas:
        k = _nome_servico(r)
        contagem[k] = contagem.get(k, 0) + 1
    tipos = [{"k": k, "n": contagem.pop(k)} for k in TIPO_ORDEM if k in contagem]
    tipos += [{"k": k, "n": n} for k, n in sorted(contagem.items(), key=lambda x: -x[1])]

    # --- Idade das O.S. abertas (aging por dtOrigem) ------------------------
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

    # --- Preventivas (bens distintos por status) e efetivo de mecânicos -----
    prev = _preventivas_status(prev_rows) if prev_rows else _preventivas(stj_rows or [], agora)
    mec = _mecanicos_efetivo(mecanicos_rows) or {
        "trabalhando": config.MECANICOS_TRABALHANDO,
        "disponivel":  config.MECANICOS_DISPONIVEL,
        "pausa":       config.MECANICOS_PAUSA,
    }
    # None = sem TTI_Portaria; cai para o valor manual do .env e o drill-down
    # fica vazio (não há como listar o que não veio da fonte).
    reserva_grupos = _reservas_limite(tti_rows, bem_rows)
    if reserva_grupos is None:
        reserva_limite, reserva_grupos = config.KPI_RESERVA_LIMITE_MANUAL, []
    else:
        reserva_limite = len(reserva_grupos)

    # --- Drill-downs ---------------------------------------------------------
    # Bloco 01 (S.S./O.S.): mais recente primeiro, exceto "fora do prazo", onde
    # a mais antiga é a que precisa de atenção. Bloco 02 (clientes): mais antigo
    # primeiro — quem espera há mais tempo no topo. Veículos: mais recente.
    detalhes = {
        "osForaPrazo": _ordenar_por_abertura([_detalhe_de_mon(m, bem_idx, man_por_ordem, agora) for m in os_fora]),
        "osAbertas":   _ordenar_por_abertura([_linha_detalhe(r, bem_idx, mon_por_ordem, agora) for r in abertas], desc=True),
        "sos":         _ordenar_por_abertura([_linha_detalhe(r, bem_idx, mon_por_ordem, agora) for r in sos]),
        "clausula":    _ordenar_por_abertura([_detalhe_de_mon(m, bem_idx, man_por_ordem, agora) for m in clausula_rows]),
        "clientesEsp": _ordenar_por_abertura([_detalhe_de_mon(m, bem_idx, man_por_ordem, agora) for m in clientes_rows]),
        "ssAguardando":_ordenar_por_abertura([_detalhe_de_mon(m, bem_idx, man_por_ordem, agora) for m in ss_aguardando], desc=True),
        "qualidade":   _ordenar_por_abertura([_linha_detalhe(r, bem_idx, mon_por_ordem, agora) for r in qualidade], desc=True),
        "retorno":     _ordenar_por_abertura([_linha_detalhe(r, bem_idx, mon_por_ordem, agora) for r in retorno], desc=True),
        "veiculos":    _ordenar_por_abertura([
            _linha_detalhe(r, bem_idx, mon_por_ordem, agora)
            for r in abertas], desc=True),
        "reservaLimite": _ordenar_por_abertura(
            _detalhes_reserva(reserva_grupos, man_por_ordem, bem_idx, mon_por_ordem, agora)),
    }

    return {
        "geradoEm": agora.isoformat(),
        "kpis": {
            "ssAguardando":  len(ss_aguardando),
            "osAbertas":     len(abertas),
            "osForaPrazo":   len(os_fora),
            "qualidade":     len(qualidade),
            "retorno":       len(retorno),
            "clientesEsp":   len(clientes_bem),
            "clausula":      len(clausula_bem),
            "reservaLimite": reserva_limite,
            "sos":           len(sos),
            "prevAtrasadas": prev["atrasadas"],
            "prevFinal":     prev["final"],
            "prevInicial":   prev["inicial"],
        },
        "mecanicos": mec,
        "tipoServico": tipos,
        "aging": aging,
        "detalhes": detalhes,
        "veiculos": {"mobilizados": len(veic_mob), "naoMobilizados": len(veic_nmob)},
        "localizacao": {"interna": len(loc_int), "externa": len(loc_ext)},
        "tipoVeiculo": tipo_veic,
    }
