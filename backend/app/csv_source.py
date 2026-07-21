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
    caminho = config.CSV_DIR / "TQB_Monitoramento.csv"
    if not caminho.exists():
        log.info("TQB_Monitoramento.csv não encontrado — pulando cruzamento de SLA")
        return []
    return _read("TQB_Monitoramento.csv")
