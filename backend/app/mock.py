"""
Dados de demonstração (MOCK_MODE=1) — reproduz os números do protótipo
vBeta com uma leve variação a cada ciclo, para você VER o painel se
atualizando sozinho antes de plugar o BigQuery.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from .kpis import TZ_BR


def _linha(ab: datetime, ss: str, os_: str, placa: str, mobil: bool, serv: str, st: str,
           reserva: str = "", reserva_st: str = "") -> dict:
    return {
        "abertura": ab.strftime("%d/%m %H:%M"),
        "aberturaIso": ab.isoformat(),
        # codBem: na base é o código do veículo; no mock não há bem real, então
        # usamos a placa como stand-in só para a coluna não ficar vazia na demo.
        "ss": ss, "os": os_, "codBem": placa, "placa": placa, "contrato": "",
        # Reserva que substitui o veículo parado — ver _reserva_de_mon em kpis.py.
        "reserva": reserva, "reservaNome": "", "reservaSt": reserva_st,
        "desc": "",   # descrição do serviço (STJ.observa)
        "previsao": "", "previsaoAtrasada": False,   # STJ.dtMpFim + horaMpFim
        "mobil": "Mobilizado" if mobil else "Não mobilizado",
        "serv": serv, "st": st,
    }


def build_mock_payload() -> dict:
    agora = datetime.now(TZ_BR)
    d = lambda dias, h=10: agora - timedelta(days=dias, hours=h % 5)

    fora = [
        _linha(d(114), "024068", "029166", "—",       True,  "Implementação", "Fora do Prazo"),
        _linha(d(114), "024070", "029168", "—",       True,  "Implementação", "Fora do Prazo"),
        _linha(d(51),  "028779", "034089", "TFD7C24", False, "Implementação", "Fora do Prazo"),
        _linha(d(51),  "028782", "034092", "TFI9I64", False, "Implementação", "Fora do Prazo"),
        _linha(d(51),  "028783", "034091", "TFU0C24", False, "Implementação", "Fora do Prazo"),
        _linha(d(44),  "029011", "034510", "TGH2K09", True,  "Corretiva",     "Fora do Prazo"),
        _linha(d(41),  "029240", "034788", "THK5M31", True,  "Corretiva",     "Fora do Prazo"),
        _linha(d(38),  "029503", "035102", "TJP7Q52", False, "Sinistro",      "Fora do Prazo"),
        _linha(d(35),  "029788", "035430", "TLR9V88", True,  "Corretiva",     "Fora do Prazo"),
        _linha(d(29),  "030122", "035901", "TMX1B04", True,  "Implementação", "Fora do Prazo"),
    ]
    abertas_amostra = [
        _linha(d(0, 1), "030880", "036712", "TPA4C77", True,  "Corretiva",     "No prazo"),
        _linha(d(0, 3), "030877", "036709", "TQB6D18", True,  "Preventiva",    "No prazo"),
        _linha(d(0, 4), "030871", "036702", "TRC8E29", False, "Implementação", "No prazo"),
        _linha(d(1),    "030850", "036680", "TSD0F60", True,  "Corretiva",     "No prazo"),
        _linha(d(1, 2), "030829", "036655", "TTE2G71", True,  "Sinistro",      "No prazo"),
    ] + fora[-2:]
    sos = [
        _linha(d(0, 2), "030858", "036688", "TVG4J93", True,  "Socorro", "Crítico"),
        _linha(d(0, 3), "030869", "036700", "TWH5K04", True,  "Socorro", "Crítico"),
        _linha(d(0, 4), "030879", "036711", "TXJ6L25", False, "Socorro", "Crítico"),
    ]
    qualidade = [_linha(d(1, 1), "030842", "036671", "TUF3H82", True, "Corretiva", "No prazo")]
    # Cláusula (demo): reaproveita as linhas fora do prazo e preenche os dois
    # prazos do drill-down (Previsto · SLA). No real, previsao=STJ dtMpFim e
    # sla=TQB.SLAVencimentoCC (abertura + SZT.Sla) — ver kpis._sla_cc_txt.
    clausula = [{**l, "st": "Crítico",
                 "previsao": l["abertura"],
                 "sla": l["abertura"]} for l in fora]

    # leve variação a cada ciclo para o "ao vivo" ficar visível na demo
    j = lambda n, amp=2: max(0, n + random.randint(-amp, amp))

    return {
        "geradoEm": agora.isoformat(),
        "kpis": {
            "ssAguardando": 0,
            "osAbertas": j(133, 3),
            "osForaPrazo": len(fora),
            "qualidade": len(qualidade),
            "retorno": 0,
            "clientesEsp": 0,
            "clausula": len(clausula),
            "reservaLimite": 0,
            "sos": len(sos),
            "prevAtrasadas": j(17, 1),
            "prevFinal": 8,
            "prevInicial": 8,
        },
        # Bate com as 6 linhas de detalhes.mecanicos abaixo (3 trabalhando + 3
        # disponível) — no BigQuery real card e detalhamento saem da mesma fonte.
        "mecanicos": {"trabalhando": 3, "disponivel": 3, "pausa": 0},
        "tipoServico": [
            {"k": "Implementação", "n": j(97, 3)},
            {"k": "Corretiva", "n": j(18)},
            {"k": "Sinistro", "n": 12},
            {"k": "Preventiva", "n": 3},
            {"k": "Socorro", "n": 3},
        ],
        "aging": {"d0_2": j(34), "d3_7": j(52), "d8_30": 39, "d30p": 8},
        "veiculos": {"mobilizados": j(56), "naoMobilizados": j(4, 1)},
        "localizacao": {"interna": j(55), "externa": j(14)},
        "tipoVeiculo": {"pesada": j(42), "leve": j(22)},
        "detalhes": {
            "osForaPrazo": fora,
            "osAbertas": abertas_amostra,
            "qualidade": qualidade,
            "ssAguardando": [],
            "clientesEsp": [],
            "clausula": clausula,
            "reservaLimite": [],
            "sos": sos,
            "retorno": [],
            # Mão de obra: efetivo em turno (sem O.S. — a base não liga mecânico
            # à ordem; ver _mecanicos_detalhe em kpis.py).
            "mecanicos": [
                {"matricula": "04480", "nome": "Abraão Carlos Barbosa",  "funcao": "Mecânico Nível II",  "cc": "104101002", "status": "Trabalhando", "turno": "06:00–11:00 · 12:00–15:48"},
                {"matricula": "09043", "nome": "Augusto Oliveira De Sousa","funcao": "Mecânico Nível II", "cc": "104101002", "status": "Trabalhando", "turno": "06:00–11:00 · 12:00–15:48"},
                {"matricula": "09044", "nome": "Jainara Da Silva Reis",    "funcao": "Eletricista Nível II","cc": "104101003","status": "Trabalhando", "turno": "06:00–12:00 · 13:10–14:30"},
                {"matricula": "20674", "nome": "Jefferson Batista Dos Santos","funcao": "Mecânico Nível II","cc": "104101002","status": "Disponível","turno": "07:00–11:00 · 12:00–15:20"},
                {"matricula": "08462", "nome": "Marcos Antonio Ribeiro",   "funcao": "Eletricista Nível II","cc": "104101001","status": "Disponível","turno": "06:00–11:00 · 12:00–14:20"},
                {"matricula": "08824", "nome": "Wadson De Souza Cardoso",   "funcao": "Mecânico Nível II",  "cc": "104101002","status": "Disponível","turno": "07:00–12:00 · 13:00–16:48"},
            ],
        },
    }
