"""Coleta dados do Perfex CRM via REST API."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

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


def get_novos_leads() -> dict[str, Any]:
    """
    Retorna leads criados nas últimas 24h e o funil completo de franqueados.
    Pagina de forma segura com limite e tratamento de rate-limit (429).
    """
    import time

    ontem = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d")

    page = 1
    max_pages = 5  # Segurança: máx 500 leads (reduzido para evitar 429)
    todos_leads: list[dict] = []

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
                logger.warning("Perfex rate limit (429) na página %d — usando dados coletados até aqui.", page)
                break
            raise

        if not data:
            break
        items = data if isinstance(data, list) else data.get("data", [])
        if not items:
            break
        todos_leads.extend(items)

        # Se o lead mais antigo desta página já é anterior a 7 dias, podemos parar
        # (precisamos de um buffer para montar o funil parcial)
        ultimo_date = items[-1].get("dateadded") or items[-1].get("date_added") or ""
        cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        if ultimo_date < cutoff_7d:
            break

        if len(items) < 100:
            break
        page += 1
        time.sleep(1)  # Respeita rate limit (aumentado para evitar 429)

    # Novos leads das últimas 24h
    novos = [
        lead for lead in todos_leads
        if (lead.get("dateadded") or lead.get("date_added") or "") >= ontem
    ]

    # Funil: agrupa todos por status
    funil: dict[str, int] = {}
    for lead in todos_leads:
        status = str(lead.get("status") or lead.get("status_id") or "0")
        funil[status] = funil.get(status, 0) + 1

    # Rótulos padrão do Perfex CRM (confirmar com a instalação real)
    _STATUS_LABELS = {
        "0": "Novo",
        "1": "Contatado",
        "2": "Interessado",
        "3": "Proposta Enviada",
        "4": "Convertido",
        "5": "Perdido",
    }
    funil_label = {_STATUS_LABELS.get(k, f"Status {k}"): v for k, v in funil.items()}

    return {
        "novos_24h": len(novos),
        "novos": novos,
        "total_leads": len(todos_leads),
        "funil": funil_label,
    }


def collect_all() -> dict[str, Any]:
    result = {}
    try:
        result["leads"] = get_novos_leads()
    except Exception as exc:
        logger.error("Perfex CRM collector falhou: %s", exc, exc_info=True)
        result["leads"] = None
    return result
