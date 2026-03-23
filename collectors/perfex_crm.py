"""Coleta dados do Perfex CRM via REST API.

API Reference: https://perfexcrm.themesic.com/apiguide/
Endpoints usados:
  GET /api/leads/          → retorna TODOS os leads (sem paginação)
  GET /api/leads/:id       → retorna um lead com detalhes
  GET /api/leads/search/:q → busca leads por texto
"""

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import requests

import config

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"authtoken": config.PERFEX_API_KEY})
_TIMEOUT = 15

# Mapeamento de status_id → nome carregado de config/lead_statuses.json
# O Perfex não expõe os nomes dos status via API — precisam ser mapeados manualmente.
_STATUSES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "lead_statuses.json"
)


def _get(path: str, params: dict = None) -> Any:
    url = f"{config.PERFEX_URL}/api/{path.lstrip('/')}"
    resp = _SESSION.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ── Status mapping ────────────────────────────────────────────────────────────

def _load_status_map() -> dict[str, str]:
    """
    Carrega mapeamento status_id → nome de config/lead_statuses.json.

    Formato esperado:
    {
      "1": "Novo",
      "2": "Contatado",
      "5": "COF Enviada",
      "6": "Ganho",
      ...
    }
    """
    if not os.path.exists(_STATUSES_PATH):
        logger.warning(
            "Arquivo %s não encontrado — status de leads aparecerão como IDs numéricos. "
            "Crie o arquivo com o mapeamento {status_id: nome}.",
            _STATUSES_PATH,
        )
        return {}
    try:
        with open(_STATUSES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Lead statuses carregados: %s", data)
        return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, IOError) as exc:
        logger.error("Erro ao ler %s: %s", _STATUSES_PATH, exc)
        return {}


_STATUS_MAP: dict[str, str] = {}


def _get_status_map() -> dict[str, str]:
    global _STATUS_MAP
    if not _STATUS_MAP:
        _STATUS_MAP = _load_status_map()
    return _STATUS_MAP


def _status_name(lead: dict) -> str:
    """Retorna o nome do status de um lead."""
    status_map = _get_status_map()
    # Tenta campo status_name direto (se a API retornar)
    if lead.get("status_name"):
        return lead["status_name"]
    sid = str(lead.get("status") or lead.get("status_id") or "0")
    return status_map.get(sid, f"Status {sid}")


# ── Lead fetching ─────────────────────────────────────────────────────────────

def _fetch_all_leads() -> list[dict]:
    """
    Busca todos os leads via GET /api/leads/.

    A API Perfex retorna TODOS os leads em uma única chamada (sem paginação).
    Deduplicamos por ID como segurança.
    """
    data = _get("leads")

    if isinstance(data, list):
        leads = data
    elif isinstance(data, dict):
        leads = data.get("data", [])
    else:
        logger.warning("Resposta inesperada do Perfex /api/leads/: %s", type(data))
        return []

    # Deduplica por ID
    seen: set[str] = set()
    unique: list[dict] = []
    for lead in leads:
        lid = str(lead.get("id", ""))
        if lid and lid not in seen:
            seen.add(lid)
            unique.append(lead)

    logger.info("Perfex: %d leads retornados, %d únicos", len(leads), len(unique))
    return unique


def _lead_date(lead: dict, field: str) -> Optional[str]:
    """Extrai data YYYY-MM-DD de um campo do lead. Retorna None se vazio."""
    val = lead.get(field) or ""
    if not val or val.startswith("0000"):
        return None
    return val[:10]


def _fmt_date_br(iso_date: str) -> str:
    """Converte YYYY-MM-DD para DD/MM/YYYY."""
    try:
        y, m, d = iso_date.split("-")
        return f"{d}/{m}/{y}"
    except (ValueError, AttributeError):
        return iso_date or "--"


# ── Pipeline principal ────────────────────────────────────────────────────────

def get_leads_pipeline(data_inicio: Optional[date] = None,
                       data_fim: Optional[date] = None) -> dict[str, Any]:
    """
    Retorna dados completos do pipeline de leads.

    Args:
        data_inicio: início do período (inclusive). None = últimas 24h.
        data_fim: fim do período (inclusive). None = hoje.

    Returns dict com:
        - novos_periodo: int — leads criados no período
        - total_pipeline: int — leads ativos no pipeline
        - funil: dict[str, int] — contagem por estágio
        - cof_enviada: list[dict] — leads em COF Enviada com última atividade
        - ganhos_periodo: list[dict] — leads ganhos no período
    """
    all_leads = _fetch_all_leads()

    # Log dos status IDs únicos para ajudar no mapeamento inicial
    status_ids = set(str(l.get("status", "?")) for l in all_leads)
    logger.info("Status IDs encontrados nos leads: %s", status_ids)

    # Período
    if data_inicio and data_fim:
        inicio_str = str(data_inicio)
        fim_str = str(data_fim)
    else:
        inicio_str = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d")
        fim_str = str(date.today())

    # Enriquece leads com nome do status
    for lead in all_leads:
        lead["_status_nome"] = _status_name(lead)

    # Leads ativos (não perdidos/junk)
    ativos = [
        l for l in all_leads
        if not int(l.get("lost") or 0) and not int(l.get("junk") or 0)
    ]

    # Funil (snapshot atual — apenas ativos)
    funil: dict[str, int] = {}
    for lead in ativos:
        nome = lead["_status_nome"]
        funil[nome] = funil.get(nome, 0) + 1

    # Novos no período (por dateadded)
    novos = []
    for l in all_leads:
        dt = _lead_date(l, "dateadded") or ""
        if inicio_str <= dt <= fim_str:
            novos.append(l)

    # COF Enviada — leads atualmente nesse estágio
    cof_enviada = []
    for lead in ativos:
        if "cof" in lead["_status_nome"].lower():
            ultima = (
                _lead_date(lead, "lastcontact")
                or _lead_date(lead, "last_status_change")
                or _lead_date(lead, "dateadded")
                or ""
            )
            cof_enviada.append({
                "id": lead.get("id"),
                "nome": lead.get("name") or lead.get("company") or f"Lead #{lead.get('id')}",
                "ultima_atividade": ultima,
                "ultima_atividade_br": _fmt_date_br(ultima),
            })
    cof_enviada.sort(key=lambda x: x["ultima_atividade"], reverse=True)

    # Ganhos no período — leads com status contendo "ganho"/"convertido"/"won"
    # cujo last_status_change está dentro do período
    ganhos = []
    for lead in all_leads:
        sn = lead["_status_nome"].lower()
        if any(kw in sn for kw in ("ganho", "convertido", "won")):
            data_ganho = (
                _lead_date(lead, "last_status_change")
                or _lead_date(lead, "dateadded")
                or ""
            )
            if inicio_str <= data_ganho <= fim_str:
                ganhos.append({
                    "id": lead.get("id"),
                    "nome": lead.get("name") or lead.get("company") or f"Lead #{lead.get('id')}",
                    "data_ganho": data_ganho,
                    "data_ganho_br": _fmt_date_br(data_ganho),
                })
    ganhos.sort(key=lambda x: x["data_ganho"], reverse=True)

    return {
        "novos_periodo": len(novos),
        "total_pipeline": len(ativos),
        "funil": funil,
        "cof_enviada": cof_enviada,
        "ganhos_periodo": ganhos,
    }


def collect_all() -> dict[str, Any]:
    """Coleta diária — pipeline atual + novos nas últimas 24h."""
    result: dict[str, Any] = {}
    try:
        result["leads"] = get_leads_pipeline()
    except Exception as exc:
        logger.error("Perfex CRM collector falhou: %s", exc, exc_info=True)
        result["leads"] = None
    return result


def collect_periodo(data_inicio: date, data_fim: date) -> dict[str, Any]:
    """Coleta para período específico (semanal/mensal)."""
    result: dict[str, Any] = {}
    try:
        result["leads"] = get_leads_pipeline(data_inicio, data_fim)
    except Exception as exc:
        logger.error("Perfex CRM (período) falhou: %s", exc, exc_info=True)
        result["leads"] = None
    return result
