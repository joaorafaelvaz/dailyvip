"""Configurações centralizadas carregadas do .env."""

import json
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Variável de ambiente obrigatória não definida: {key}")
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ERP MySQL
ERP_HOST = _optional("ERP_HOST", "localhost")
ERP_PORT = int(_optional("ERP_PORT", "3306"))
ERP_DB = _optional("ERP_DB", "franquia_producao")
ERP_USER = _optional("ERP_USER")
ERP_PASSWORD = _optional("ERP_PASSWORD")

# Perfex CRM
PERFEX_URL = _optional("PERFEX_URL", "").rstrip("/")
PERFEX_API_KEY = _optional("PERFEX_API_KEY")

# SatisfyCAM
SATISFYCAM_DB_PATH = _optional(
    "SATISFYCAM_DB_PATH",
    "D:/Dev/Barbearia VIP/sensevip/prisma/dev.db",
)

# Google Business Profile
GOOGLE_SERVICE_ACCOUNT_JSON = _optional("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/google_service_account.json")
GOOGLE_ACCOUNT_ID = _optional("GOOGLE_ACCOUNT_ID")

# WAHA
WAHA_URL = _optional("WAHA_URL", "http://localhost:3000").rstrip("/")
WAHA_API_KEY = _optional("WAHA_API_KEY")
WAHA_SESSION = _optional("WAHA_SESSION", "default")
WAHA_RECIPIENTS: list[str] = [
    r.strip() for r in _optional("WAHA_RECIPIENTS", "").split(",") if r.strip()
]

# Agendamento — Diário
BRIEFING_HOUR = int(_optional("BRIEFING_HOUR", "8"))
BRIEFING_MINUTE = int(_optional("BRIEFING_MINUTE", "0"))
TIMEZONE = _optional("TIMEZONE", "America/Sao_Paulo")

# Agendamento — Semanal (segunda-feira 7h)
WEEKLY_BRIEFING_HOUR = int(_optional("WEEKLY_BRIEFING_HOUR", "7"))
WEEKLY_BRIEFING_MINUTE = int(_optional("WEEKLY_BRIEFING_MINUTE", "0"))

# Agendamento — Mensal (dia 1, 9h)
MONTHLY_BRIEFING_HOUR = int(_optional("MONTHLY_BRIEFING_HOUR", "9"))
MONTHLY_BRIEFING_MINUTE = int(_optional("MONTHLY_BRIEFING_MINUTE", "0"))

# Meta Ads (Graph API — Marketing Insights)
# Token de System User do Business Manager com permissão ads_read (não expira).
META_ACCESS_TOKEN = _optional("META_ACCESS_TOKEN")
META_API_VERSION = _optional("META_API_VERSION", "v26.0")

# Agendamento — Meta Ads (diário, 8h30)
META_BRIEFING_HOUR = int(_optional("META_BRIEFING_HOUR", "8"))
META_BRIEFING_MINUTE = int(_optional("META_BRIEFING_MINUTE", "30"))

# Meta Ads — dia sem veiculação (gasto e impressões zerados)
# Não envia o relatório ao cliente quando ontem foi vazio (padrão: ligado).
META_SKIP_EMPTY = _optional("META_SKIP_EMPTY", "true").lower() in ("1", "true", "yes")
# Avisa a franqueadora a partir de N dias vazios consecutivos (0 desativa).
META_EMPTY_ALERT_DAYS = int(_optional("META_EMPTY_ALERT_DAYS", "3"))

# Seções opcionais dos relatórios (ocultas por padrão — reative via .env)
SHOW_SATISFYCAM = _optional("SHOW_SATISFYCAM", "false").lower() in ("1", "true", "yes")
SHOW_INADIMPLENCIA = _optional("SHOW_INADIMPLENCIA", "false").lower() in ("1", "true", "yes")

# Dashboard
DASHBOARD_BASE_URL = _optional("DASHBOARD_BASE_URL", "http://localhost/daily/output")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Estado do relatório Meta Ads (dias vazios consecutivos por conta)
META_ADS_STATE_PATH = os.path.join(OUTPUT_DIR, "meta_ads_state.json")

# Mapeamento unidade → grupo WhatsApp do franqueado
_UNIT_GROUPS_PATH = os.path.join(os.path.dirname(__file__), "config", "unit_groups.json")


def load_unit_groups() -> dict[str, dict]:
    """
    Carrega mapeamento de unidades para destinatários WhatsApp.
    Retorna dict {unidade_id_str: {"nome": "...", "chat_id": "..."}} —
    cada unidade pode ter "chat_id" (string) e/ou "chat_ids" (lista).
    """
    if not os.path.exists(_UNIT_GROUPS_PATH):
        logger.warning("Arquivo %s não encontrado — briefings por unidade desativados.", _UNIT_GROUPS_PATH)
        return {}
    try:
        with open(_UNIT_GROUPS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("units", {})
    except (json.JSONDecodeError, IOError) as exc:
        logger.error(
            "ERRO ao ler %s (%s) — briefings por unidade DESATIVADOS até corrigir o arquivo!",
            _UNIT_GROUPS_PATH, exc,
        )
        return {}


UNIT_GROUPS = load_unit_groups()

# Contas de anúncio do Meta Ads → destinatários WhatsApp
_META_ADS_ACCOUNTS_PATH = os.path.join(os.path.dirname(__file__), "config", "meta_ads_accounts.json")


def load_meta_ads_accounts() -> list[dict]:
    """
    Carrega as contas de anúncio que recebem relatório diário do Meta Ads.
    Retorna lista de dicts com "ad_account_id", "nome" e, opcionalmente,
    "unidade_id", "chat_id" e/ou "chat_ids". Entradas sem ad_account_id são ignoradas.
    """
    if not os.path.exists(_META_ADS_ACCOUNTS_PATH):
        logger.info("Arquivo %s não encontrado — relatório Meta Ads desativado.", _META_ADS_ACCOUNTS_PATH)
        return []
    try:
        with open(_META_ADS_ACCOUNTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        logger.error(
            "ERRO ao ler %s (%s) — relatório Meta Ads DESATIVADO até corrigir o arquivo!",
            _META_ADS_ACCOUNTS_PATH, exc,
        )
        return []

    accounts = []
    for acc in data.get("accounts", []) or []:
        if not isinstance(acc, dict) or not str(acc.get("ad_account_id", "")).strip():
            logger.warning("Entrada inválida em meta_ads_accounts.json ignorada: %r", acc)
            continue
        accounts.append(acc)
    return accounts


META_ADS_ACCOUNTS = load_meta_ads_accounts()
