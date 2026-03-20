"""Coleta novas avaliações do Google Business Profile API."""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import config

logger = logging.getLogger(__name__)


def _build_service():
    """Constrói o cliente autenticado da Google Business Profile API."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/business.manage"]
    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON, scopes=scopes
    )
    # A Google Business Profile API usa o endpoint mybusinessaccountmanagement / mybusiness
    service = build(
        "mybusiness",
        "v4",
        credentials=creds,
        discoveryServiceUrl=(
            "https://mybusiness.googleapis.com/$discovery/rest?version=v4"
        ),
        static_discovery=False,
    )
    return service


def get_new_reviews() -> dict[str, Any]:
    """
    Retorna avaliações novas nas últimas 24h em todas as locations da conta.
    Separa positivas (>=4 estrelas) de negativas (<=2 estrelas).
    """
    if not config.GOOGLE_ACCOUNT_ID or not os.path.exists(config.GOOGLE_SERVICE_ACCOUNT_JSON):
        logger.warning("Google Reviews: credenciais não configuradas, pulando.")
        return {"total": 0, "positivas": [], "negativas": [], "locations": []}

    service = _build_service()
    account_id = config.GOOGLE_ACCOUNT_ID  # ex: "accounts/123456"

    since = datetime.now(timezone.utc) - timedelta(hours=24)

    # Lista todas as locations
    locations_resp = service.accounts().locations().list(parent=account_id).execute()
    locations = locations_resp.get("locations", [])

    all_reviews: list[dict] = []
    for loc in locations:
        loc_name = loc.get("name")  # ex: accounts/123/locations/456
        loc_title = loc.get("locationName", loc_name)
        try:
            reviews_resp = (
                service.accounts()
                .locations()
                .reviews()
                .list(parent=loc_name, orderBy="updateTime desc", pageSize=20)
                .execute()
            )
            for rev in reviews_resp.get("reviews", []):
                update_time_str = rev.get("updateTime", "")
                # Formato: 2024-03-19T10:00:00Z
                try:
                    update_time = datetime.fromisoformat(
                        update_time_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                if update_time >= since:
                    rev["_location_title"] = loc_title
                    all_reviews.append(rev)
        except Exception as exc:
            logger.warning("Falha ao buscar reviews de %s: %s", loc_name, exc)

    def _stars(rating_str: str) -> int:
        mapping = {
            "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
        }
        return mapping.get(str(rating_str).upper(), 0)

    positivas = [r for r in all_reviews if _stars(r.get("starRating", "")) >= 4]
    negativas = [r for r in all_reviews if _stars(r.get("starRating", "")) <= 2]

    return {
        "total": len(all_reviews),
        "positivas": positivas,
        "negativas": negativas,
        "locations_count": len(locations),
    }


def collect_all() -> dict[str, Any]:
    result = {}
    try:
        result["reviews"] = get_new_reviews()
    except Exception as exc:
        logger.error("Google Reviews collector falhou: %s", exc, exc_info=True)
        result["reviews"] = None
    return result
