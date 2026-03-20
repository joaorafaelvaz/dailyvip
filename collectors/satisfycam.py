"""Coleta dados do SatisfyCAM (sensevip SQLite)."""

import logging
import sqlite3
from datetime import date, timedelta
from typing import Any

import config

logger = logging.getLogger(__name__)


def _query(sql: str, args=()) -> list[dict]:
    with sqlite3.connect(config.SATISFYCAM_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, args)
        return [dict(row) for row in cur.fetchall()]


def get_relatorio_ontem() -> dict[str, Any]:
    """Retorna o DailyReport do dia anterior."""
    ontem = date.today() - timedelta(days=1)
    rows = _query(
        """
        SELECT
            totalCustomers,
            satisfied,
            neutral,
            unsatisfied,
            avgConfidence,
            date
        FROM DailyReport
        WHERE date(date) = ?
        """,
        (str(ontem),),
    )

    if not rows:
        return {
            "data": str(ontem),
            "total_clientes": 0,
            "satisfied": 0,
            "neutral": 0,
            "unsatisfied": 0,
            "pct_satisfied": 0,
            "pct_unsatisfied": 0,
            "avg_confidence": 0,
            "alertas": [],
        }

    r = rows[0]
    total = r["totalCustomers"] or 0
    unsat = r["unsatisfied"] or 0
    sat = r["satisfied"] or 0

    pct_unsat = round(unsat / total * 100, 1) if total else 0
    pct_sat = round(sat / total * 100, 1) if total else 0

    # Alertas: detecções negativas por storeId nas últimas 24h
    alertas = _query(
        """
        SELECT
            storeId,
            COUNT(*) AS total_negativas,
            ROUND(AVG(confidence), 3) AS conf_media
        FROM Detection
        WHERE satisfactionTag = 'UNSATISFIED'
          AND datetime(timestamp) >= datetime('now', '-1 day')
          AND storeId IS NOT NULL
        GROUP BY storeId
        ORDER BY total_negativas DESC
        """,
    )

    return {
        "data": str(ontem),
        "total_clientes": total,
        "satisfied": sat,
        "neutral": r["neutral"] or 0,
        "unsatisfied": unsat,
        "pct_satisfied": pct_sat,
        "pct_unsatisfied": pct_unsat,
        "avg_confidence": round(r["avgConfidence"] or 0, 3),
        "alertas": alertas,
    }


def collect_all() -> dict[str, Any]:
    result = {}
    try:
        result["relatorio"] = get_relatorio_ontem()
    except Exception as exc:
        logger.error("SatisfyCAM collector falhou: %s", exc, exc_info=True)
        result["relatorio"] = None
    return result
