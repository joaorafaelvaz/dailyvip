"""Configurações centralizadas carregadas do .env."""

import json
import os
from dotenv import load_dotenv

load_dotenv()


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

# Agendamento
BRIEFING_HOUR = int(_optional("BRIEFING_HOUR", "8"))
BRIEFING_MINUTE = int(_optional("BRIEFING_MINUTE", "0"))
TIMEZONE = _optional("TIMEZONE", "America/Sao_Paulo")

# Dashboard
DASHBOARD_BASE_URL = _optional("DASHBOARD_BASE_URL", "http://localhost/daily/output")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Mapeamento unidade → grupo WhatsApp do franqueado
_UNIT_GROUPS_PATH = os.path.join(os.path.dirname(__file__), "config", "unit_groups.json")


def load_unit_groups() -> dict[str, dict]:
    """
    Carrega mapeamento de unidades para grupos WhatsApp.
    Retorna dict {unidade_id_str: {"nome": "...", "chat_id": "..."}}.
    """
    if not os.path.exists(_UNIT_GROUPS_PATH):
        return {}
    try:
        with open(_UNIT_GROUPS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("units", {})
    except (json.JSONDecodeError, IOError):
        return {}


UNIT_GROUPS = load_unit_groups()
