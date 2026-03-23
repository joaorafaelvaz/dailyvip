"""Coleta dados do Perfex CRM via REST API."""

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import requests

import config

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"authtoken": config.PERFEX_API_KEY})
_TIMEOUT = 15


def _get(path: str, params: dict = None) -> Any:
    url = f"{config.PERFEX_URL}/api/{path.lstrip('/')}"
    resp = _SESSION.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ── Status mapping ────────────────────────────────────────────────────────────

_STATUS_CACHE: dict[str, str] = {}


def _fetch_status_map() -> dict[str, str]:
    """Busca mapeamento status_id → nome do Perfex CRM."""
    global _STATUS_CACHE
    if _STATUS_CACHE:
        return _STATUS_CACHE

    for endpoint in ("leads_statuses", "lead_statuses"):
        try:
            data = _get(endpoint)
            items = data if isinstance(data, list) else data.get("data", [])
            if items:
                _STATUS_CACHE = {
                    str(s.get("id", "")): s.get("name", f"Status {s.get('id')}")
                    for s in items
                }
                logger.info("Perfex status map: %s", _STATUS_CACHE)
                return _STATUS_CACHE
        except Exception as exc:
            logger.debug("Endpoint '%s' falhou: %s", endpoint, exc)
            continue

    logger.warning("Não foi possível buscar statuses do Perfex — usando IDs numéricos")
    return {}


def _status_name(lead: dict, status_map: dict[str, str]) -> str:
    """Retorna o nome do status de um lead."""
    if lead.get("status_name"):
        return lead["status_name"]
    sid = str(lead.get("status") or lead.get("status_id") or "0")
    return status_map.get(sid, f"Status {sid}")


# ── Lead fetching ─────────────────────────────────────────────────────────────

def _fetch_all_leads(max_pages: int = 20) -> list[dict]:
    """Busca todos os leads do pipeline com paginação e rate-limit."""
    page = 1
    all_leads: list[dict] = []

    while page <= max_pages:
        try:
            data = _get("leads", params={
                "page": page,
                "per_page": 100,
                "sort": "dateadded",
                "sort_type": "desc",
            })
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                logger.warning("Perfex rate limit (429) página %d — usando dados coletados.", page)
                break
            raise

        if not data:
            break
        items = data if isinstance(data, list) else data.get("data", [])
        if not items:
            break
        all_leads.extend(items)

        if len(items) < 100:
            break
        page += 1
        time.sleep(1)

    return all_leads


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
    status_map = _fetch_status_map()
    all_leads = _fetch_all_leads()

    logger.info("Perfex: %d leads buscados, %d statuses mapeados", len(all_leads), len(status_map))

    # Período
    if data_inicio and data_fim:
        inicio_str = str(data_inicio)
        fim_str = str(data_fim)
    else:
        inicio_str = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d")
        fim_str = str(date.today())

    # Enriquece leads com nome do status
    for lead in all_leads:
        lead["_status_nome"] = _status_name(lead, status_map)

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
        dt = _lead_date(l, "dateadded") or _lead_date(l, "date_added") or ""
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
                or _lead_date(lead, "date_added")
                or ""
            )
            cof_enviada.append({
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
                or _lead_date(lead, "date_added")
                or ""
            )
            if inicio_str <= data_ganho <= fim_str:
                ganhos.append({
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
