"""Coleta métricas de contas de anúncio do Meta Ads (Graph API — Marketing Insights)."""

import json
import logging
import os
from datetime import date, timedelta
from typing import Any, Optional

import requests

import config

logger = logging.getLogger(__name__)

_TIMEOUT = 30

# Campos pedidos ao endpoint /insights (nível conta e nível campanha)
_INSIGHT_FIELDS = (
    "spend,impressions,reach,clicks,inline_link_clicks,cpc,cpm,ctr,"
    "actions,cost_per_action_type"
)

# Ações que contam como "resultado" para o negócio, com rótulo em PT-BR.
# A ordem define a prioridade de exibição.
RESULT_ACTIONS: list[tuple[str, str]] = [
    ("onsite_conversion.messaging_conversation_started_7d", "Conversas no WhatsApp"),
    ("lead", "Leads"),
    ("onsite_conversion.lead_grouped", "Leads (formulário)"),
    ("omni_purchase", "Compras"),
    ("purchase", "Compras (site)"),
    ("onsite_conversion.post_save", "Salvamentos"),
    ("post_engagement", "Engajamentos"),
    ("link_click", "Cliques no link"),
]


class MetaAdsError(RuntimeError):
    """Erro retornado pela Graph API ou falha de rede."""


def _base_url() -> str:
    return f"https://graph.facebook.com/{config.META_API_VERSION}"


def resolve_token(acc: Optional[dict[str, Any]] = None) -> str:
    """
    Token a usar para uma conta: a variável de ambiente indicada em "token_env"
    (uma por Business Manager) ou, na ausência dela, META_ACCESS_TOKEN.
    """
    token_env = (acc or {}).get("token_env")
    if token_env:
        token = os.getenv(str(token_env).strip(), "")
        if not token:
            raise MetaAdsError(f"Variável {token_env} (token_env) não definida no .env")
        return token
    if not config.META_ACCESS_TOKEN:
        raise MetaAdsError("META_ACCESS_TOKEN não configurado no .env")
    return config.META_ACCESS_TOKEN


def _get(path: str, params: dict[str, Any], token: Optional[str] = None) -> dict[str, Any]:
    """GET autenticado na Graph API; converte erros da API em MetaAdsError."""
    token = token or resolve_token()

    url = f"{_base_url()}/{path.lstrip('/')}"
    params = {**params, "access_token": token}
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise MetaAdsError(f"Falha de rede ao chamar {path}: {exc}") from exc

    try:
        body = resp.json()
    except ValueError:
        body = {}

    if resp.status_code >= 400 or "error" in body:
        err = body.get("error", {})
        raise MetaAdsError(
            f"Graph API {resp.status_code} em {path}: "
            f"{err.get('message', resp.text[:200])} "
            f"(code={err.get('code')}, subcode={err.get('error_subcode')})"
        )
    return body


def normalize_account_id(ad_account_id: str) -> str:
    ad_account_id = str(ad_account_id).strip()
    return ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"


def _to_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _parse_actions(row: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extrai da linha de insights as ações relevantes (RESULT_ACTIONS) com
    quantidade e custo unitário. Retorna lista ordenada pela prioridade.
    """
    actions = {a.get("action_type"): _to_int(a.get("value")) for a in row.get("actions") or []}
    costs = {
        a.get("action_type"): _to_float(a.get("value"))
        for a in row.get("cost_per_action_type") or []
    }
    out = []
    for action_type, label in RESULT_ACTIONS:
        qty = actions.get(action_type, 0)
        if qty > 0:
            out.append({
                "tipo": action_type,
                "label": label,
                "quantidade": qty,
                "custo_unitario": costs.get(action_type),
            })
    return out


def _parse_row(row: dict[str, Any]) -> dict[str, Any]:
    spend = _to_float(row.get("spend"))
    clicks = _to_int(row.get("clicks"))
    link_clicks = _to_int(row.get("inline_link_clicks"))
    impressions = _to_int(row.get("impressions"))
    return {
        "gasto": spend,
        "impressoes": impressions,
        "alcance": _to_int(row.get("reach")),
        "cliques": clicks,
        "cliques_link": link_clicks,
        "cpc": _to_float(row.get("cpc")) if clicks else None,
        "cpm": _to_float(row.get("cpm")) if impressions else None,
        "ctr": _to_float(row.get("ctr")) if impressions else None,
        "resultados": _parse_actions(row),
    }


def _empty_metrics() -> dict[str, Any]:
    return _parse_row({})


def _insights(
    account: str,
    since: date,
    until: date,
    level: str = "account",
    extra_fields: str = "",
    limit: int = 50,
    token: Optional[str] = None,
) -> list[dict[str, Any]]:
    fields = _INSIGHT_FIELDS + (f",{extra_fields}" if extra_fields else "")
    params = {
        "fields": fields,
        "level": level,
        "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        "limit": limit,
    }
    body = _get(f"{account}/insights", params, token=token)
    return body.get("data", [])


def get_account_info(ad_account_id: str, token: Optional[str] = None) -> dict[str, Any]:
    """Nome, moeda e status da conta de anúncios."""
    account = normalize_account_id(ad_account_id)
    body = _get(account, {"fields": "name,currency,account_status,timezone_name"}, token=token)
    return {
        "id": account,
        "nome": body.get("name", account),
        "moeda": body.get("currency", "BRL"),
        "status": body.get("account_status"),
        "timezone": body.get("timezone_name"),
    }


def collect_account(
    ad_account_id: str,
    dia: Optional[date] = None,
    top_campanhas: int = 5,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Coleta o resumo de UM dia (padrão: ontem) de uma conta de anúncios,
    mais o acumulado do mês daquele dia e as campanhas com maior gasto.

    Args:
        token: token de acesso da BM dona da conta (padrão: META_ACCESS_TOKEN).

    Returns:
        {
          "conta": {id, nome, moeda, status, timezone},
          "dia": date,
          "ontem": {gasto, impressoes, alcance, cliques, cliques_link, cpc, cpm, ctr, resultados[]},
          "mes": {... mesmos campos ..., "inicio": date},
          "campanhas": [{nome, gasto, cliques, resultados[], ...}, ...],
        }
    """
    dia = dia or (date.today() - timedelta(days=1))
    account = normalize_account_id(ad_account_id)
    inicio_mes = dia.replace(day=1)

    token = token or resolve_token()
    info = get_account_info(account, token=token)

    rows = _insights(account, dia, dia, token=token)
    ontem = _parse_row(rows[0]) if rows else _empty_metrics()

    rows_mes = _insights(account, inicio_mes, dia, token=token)
    mes = _parse_row(rows_mes[0]) if rows_mes else _empty_metrics()
    mes["inicio"] = inicio_mes

    campanhas: list[dict[str, Any]] = []
    try:
        rows_camp = _insights(
            account, dia, dia, level="campaign", extra_fields="campaign_name", token=token
        )
        for r in rows_camp:
            parsed = _parse_row(r)
            parsed["nome"] = r.get("campaign_name", "(sem nome)")
            campanhas.append(parsed)
        campanhas.sort(key=lambda c: c["gasto"], reverse=True)
        campanhas = campanhas[:top_campanhas]
    except MetaAdsError as exc:
        # Campanhas são complemento; não derrubam o relatório
        logger.warning("Meta Ads %s: falha ao listar campanhas: %s", account, exc)

    logger.info(
        "Meta Ads %s (%s) %s: gasto=%.2f alcance=%d cliques=%d resultados=%d",
        account, info["nome"], dia, ontem["gasto"], ontem["alcance"], ontem["cliques"],
        sum(r["quantidade"] for r in ontem["resultados"]),
    )

    return {
        "conta": info,
        "dia": dia,
        "ontem": ontem,
        "mes": mes,
        "campanhas": campanhas,
    }


def collect_all(
    accounts: list[dict[str, Any]],
    dia: Optional[date] = None,
) -> dict[str, dict[str, Any]]:
    """
    Coleta todas as contas configuradas. Falha em uma conta não afeta as demais.
    Cada conta usa o token de sua própria BM quando "token_env" está definido.

    Returns:
        {ad_account_id: dados | {"erro": "...", "dia": date}}
    """
    dia = dia or (date.today() - timedelta(days=1))
    results: dict[str, dict[str, Any]] = {}
    for acc in accounts:
        acc_id = normalize_account_id(acc["ad_account_id"])
        try:
            results[acc_id] = collect_account(acc_id, dia, token=resolve_token(acc))
        except Exception as exc:  # noqa: BLE001 — isola falha por conta
            logger.error("Meta Ads %s falhou: %s", acc_id, exc, exc_info=True)
            results[acc_id] = {"erro": str(exc), "dia": dia}
    return results
