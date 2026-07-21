"""
Configuração central do backend — tudo via variáveis de ambiente (.env).

Pense neste arquivo como os "Parâmetros" do Power Query: nada de valor
fixo espalhado pelo código; muda aqui (ou no .env) e o resto obedece.
"""
import os
from pathlib import Path

# Carrega o arquivo .env (se existir) para dentro das variáveis de ambiente.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass  # python-dotenv é opcional; em produção as vars podem vir do sistema


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# --- Fonte de dados -----------------------------------------------------------
# DATA_SOURCE = mock      -> dados de demonstração (sem BigQuery, sem arquivos)
#               csv       -> lê STJ.csv / STJ_Manutencao.csv de CSV_DIR
#                            (ótimo para validar a modelagem com dados reais offline)
#               bigquery  -> produção
DATA_SOURCE = os.getenv("DATA_SOURCE", os.getenv("MOCK_MODE", "0") == "1" and "mock" or "bigquery")
MOCK_MODE = DATA_SOURCE == "mock"   # compatibilidade
CSV_DIR = Path(os.getenv("CSV_DIR", Path(__file__).resolve().parents[1] / "dados"))

# --- BigQuery ----------------------------------------------------------------
BQ_PROJECT = os.getenv("BQ_PROJECT", "gcp-maas-proj-manutencao")
BQ_DATASET = os.getenv("BQ_DATASET", "silver")
BQ_VIEW_MANUTENCAO = os.getenv("BQ_VIEW_MANUTENCAO", "STJ_Manutencao")  # oficina agora
BQ_VIEW_STJ        = os.getenv("BQ_VIEW_STJ", "STJ")                    # histórico (preventivas/retorno)
# Limite de segurança para não estourar memória se o WHERE vier largo demais.
BQ_MAX_ROWS = _int("BQ_MAX_ROWS", 20000)

# Autenticação: o cliente google-cloud-bigquery usa automaticamente
#   1) a variável GOOGLE_APPLICATION_CREDENTIALS apontando para o JSON
#      de uma service account, OU
#   2) o login feito com `gcloud auth application-default login`.
# Nenhuma credencial fica no código nem no frontend.

# --- Ciclo de atualização ----------------------------------------------------
POLL_SECONDS = _int("POLL_SECONDS", 300)   # 300s = 5 min (igual ao rótulo do painel)

# --- Regras ajustáveis ---------------------------------------------------------
# "Preventivas atrasadas": ignora janelas vencidas há mais de N dias
# (a base tem 1.081 preventivas de plano antigo vencidas em 2024 — ruído).
PREV_RETRO_DIAS = _int("PREV_RETRO_DIAS", 90)

# --- Valores manuais / sem fonte automática confirmada -------------------------
# Estes KPIs existem no painel mas não têm coluna/tabela confirmada ainda
# (ver "LIMITES CONHECIDOS" em kpis.py e README, seção "Pendências").
# "Clientes esp." SAIU daqui — agora vem de TQB_Monitoramento.Xesper (kpis.py).
KPI_RETORNO_MANUAL       = _int("KPI_RETORNO_MANUAL", 0)   # 0 = usa regra automática (XRETORN)
KPI_SS_AGUARDANDO_MANUAL = _int("KPI_SS_AGUARDANDO_MANUAL", 0)
KPI_QUALIDADE_MANUAL     = _int("KPI_QUALIDADE_MANUAL", 0)
KPI_RESERVA_LIMITE_MANUAL= _int("KPI_RESERVA_LIMITE_MANUAL", 0)

# Efetivo de mecânicos (Capacidade × demanda). Se um dia isso vier de uma
# tabela de escala, troque em kpis.py; por ora é configuração.
MECANICOS_TRABALHANDO = _int("MECANICOS_TRABALHANDO", 11)
MECANICOS_DISPONIVEL  = _int("MECANICOS_DISPONIVEL", 6)
MECANICOS_PAUSA       = _int("MECANICOS_PAUSA", 0)

# --- Servidor ----------------------------------------------------------------
HOST = os.getenv("HOST", "0.0.0.0")
PORT = _int("PORT", 8000)

# Caminho do frontend servido pelo próprio backend (um servidor só).
FRONTEND_DIR = Path(
    os.getenv("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend")
)
