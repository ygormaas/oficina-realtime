"""
Fonte CSV (DATA_SOURCE=csv) — lê exports das views para validar a
modelagem com dados reais SEM tocar no BigQuery. Espera em CSV_DIR:

    STJ_Manutencao.csv   e   STJ.csv     (separador ';', como o export padrão)
"""
from __future__ import annotations

import csv
import logging
from . import config

log = logging.getLogger("oficina.csv")


def _read(nome: str) -> list[dict]:
    caminho = config.CSV_DIR / nome
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        rows = [dict(r) for r in csv.DictReader(f, delimiter=";")]
    log.info("%s: %d linhas", caminho, len(rows))
    return rows


def fetch_manutencao() -> list[dict]:
    return _read("STJ_Manutencao.csv")


def fetch_stj() -> list[dict]:
    return _read("STJ.csv")


def fetch_monitoramento() -> list[dict]:
    """Sem export local de TQB_Monitoramento ainda — modo csv segue sem
    esse cruzamento (clientesEsp/clausula caem para 0 até existir o CSV)."""
    return _opcional("TQB_Monitoramento.csv", "cruzamento de SLA")


def _opcional(nome: str, para_que: str) -> list[dict]:
    """Lê um CSV se existir; senão devolve [] (kpis.py degrada o KPI)."""
    if not (config.CSV_DIR / nome).exists():
        log.info("%s não encontrado — pulando %s", nome, para_que)
        return []
    return _read(nome)


def fetch_ss_aguardando() -> list[dict]:
    """S.S. aguardando: no CSV a tabela vem inteira, então o filtro do StatusOS
    (que no BigQuery está no WHERE) é aplicado aqui."""
    rows = _opcional("TQB_Monitoramento.csv", "S.S. aguardando")
    return [r for r in rows if "ABERTA" not in str(r.get("StatusOS") or "").upper()]


def fetch_cadastro_bem() -> list[dict]:
    return _opcional("ST9_CadastroBem.csv", "cláusula/veículos")


def fetch_mecanicos() -> list[dict]:
    return _opcional("SRA_SRJ_Funcionarios.csv", "efetivo de mecânicos")


def fetch_preventivas() -> list[dict]:
    return _opcional("STF_Status_Manutencao.csv", "preventivas")


def fetch_tqr() -> list[dict]:
    return _opcional("TQR.csv", "tipo de veículo (Pesada/Leve)")
