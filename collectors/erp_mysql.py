"""Coleta dados do ERP MySQL (franquia_producao)."""

import calendar
import json
import logging
import os
from datetime import date, timedelta
from typing import Any, Optional

import pymysql
import pymysql.cursors

import config

logger = logging.getLogger(__name__)

# ── Metas manuais (carregadas de config/unit_metas.json) ────────────────────
_METAS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "unit_metas.json")


def _load_manual_metas() -> dict[int, float]:
    """Retorna {unidade_id: meta_mensal_reais} das metas definidas manualmente."""
    if not os.path.exists(_METAS_PATH):
        return {}
    try:
        with open(_METAS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        units = data.get("units", {})
        return {int(k): float(v["meta_mensal"]) for k, v in units.items() if v.get("meta_mensal")}
    except (json.JSONDecodeError, IOError, ValueError):
        return {}


MANUAL_METAS = _load_manual_metas()


# ── Conexão MySQL ────────────────────────────────────────────────────────────

def _get_connection():
    return pymysql.connect(
        host=config.ERP_HOST,
        port=config.ERP_PORT,
        db=config.ERP_DB,
        user=config.ERP_USER,
        password=config.ERP_PASSWORD,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


def _query(sql: str, args=None) -> list[dict]:
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()


# ── Meta automática: média dos últimos 3 meses ──────────────────────────────

def get_media_historica() -> dict[int, float]:
    """
    Calcula a média mensal de faturamento dos últimos 3 meses completos
    por unidade. Usado como meta quando não há meta manual definida.
    """
    hoje = date.today()
    # Últimos 3 meses completos (exclui o mês atual)
    meses = []
    for i in range(1, 4):
        ano = hoje.year
        mes = hoje.month - i
        while mes <= 0:
            mes += 12
            ano -= 1
        meses.append((ano, mes))

    if not meses:
        return {}

    # Constrói cláusula para os 3 meses
    where_parts = []
    params = []
    for ano, mes in meses:
        where_parts.append("(YEAR(v.data_criacao) = %s AND MONTH(v.data_criacao) = %s)")
        params.extend([ano, mes])

    where_clause = " OR ".join(where_parts)
    n_meses = len(meses)

    rows = _query(
        f"""
        SELECT
            u.id AS unidade_id,
            SUM(v.valor_total) / {n_meses} AS media_mensal
        FROM vendas v
        JOIN usuarios usr ON usr.id = v.usuario
        JOIN unidades u   ON u.id  = usr.unidade
        WHERE ({where_clause})
          AND v.status = 1
          AND v.comanda_temp = 0
        GROUP BY u.id
        """,
        params,
    )

    return {r["unidade_id"]: float(r["media_mensal"] or 0) for r in rows}


def _resolve_meta(unidade_id: int, media_hist: dict[int, float]) -> Optional[float]:
    """
    Retorna a meta mensal para uma unidade.
    Prioridade: 1) meta manual → 2) média histórica → 3) None
    """
    if unidade_id in MANUAL_METAS:
        return MANUAL_METAS[unidade_id]
    if unidade_id in media_hist:
        return media_hist[unidade_id]
    return None


# ── Collectors ───────────────────────────────────────────────────────────────

def get_faturamento_ontem(media_hist: dict[int, float] = None) -> dict[str, Any]:
    """
    Retorna faturamento do dia anterior por unidade.
    Meta = manual (se definida) ou média últimos 3 meses.
    """
    if media_hist is None:
        media_hist = {}

    ontem = date.today() - timedelta(days=1)
    rows = _query(
        """
        SELECT
            u.id            AS unidade_id,
            u.nome          AS unidade_nome,
            u.cidade,
            u.estado,
            SUM(v.valor_total)               AS faturamento,
            COUNT(v.id)                      AS total_vendas,
            SUM(v.valor_total) / COUNT(v.id) AS ticket_medio
        FROM vendas v
        JOIN usuarios usr ON usr.id = v.usuario
        JOIN unidades u   ON u.id  = usr.unidade
        WHERE DATE(v.data_criacao) = %s
          AND v.status = 1
          AND v.comanda_temp = 0
        GROUP BY u.id, u.nome, u.cidade, u.estado
        ORDER BY faturamento DESC
        """,
        (ontem,),
    )

    if not rows:
        return {
            "data": str(ontem),
            "total_rede": 0,
            "unidades": [],
            "top5": [],
            "bottom5": [],
            "ticket_medio_rede": 0,
        }

    dias_mes = calendar.monthrange(ontem.year, ontem.month)[1]

    for r in rows:
        uid = r["unidade_id"]
        meta_mensal = _resolve_meta(uid, media_hist)
        r["meta_mensal"] = round(meta_mensal, 2) if meta_mensal else None
        r["meta_origem"] = (
            "manual" if uid in MANUAL_METAS
            else "historica" if uid in media_hist
            else None
        )
        r["meta_diaria"] = meta_mensal / dias_mes if meta_mensal else None
        r["pct_meta"] = (
            round(float(r["faturamento"]) / r["meta_diaria"] * 100, 1)
            if r["meta_diaria"]
            else None
        )

    total_rede = sum(float(r["faturamento"]) for r in rows)
    total_vendas_rede = sum(r["total_vendas"] for r in rows)
    ticket_medio_rede = total_rede / total_vendas_rede if total_vendas_rede else 0

    # Meta total da rede
    meta_total_rede = sum(r["meta_mensal"] for r in rows if r["meta_mensal"])
    meta_diaria_rede = meta_total_rede / dias_mes if meta_total_rede else None

    # Ordena por % de meta para top/bottom
    com_meta = [r for r in rows if r["pct_meta"] is not None]
    com_meta_sorted = sorted(com_meta, key=lambda x: x["pct_meta"], reverse=True)

    return {
        "data": str(ontem),
        "total_rede": round(total_rede, 2),
        "total_vendas_rede": total_vendas_rede,
        "ticket_medio_rede": round(ticket_medio_rede, 2),
        "meta_diaria_rede": round(meta_diaria_rede, 2) if meta_diaria_rede else None,
        "pct_meta_rede": (
            round(total_rede / meta_diaria_rede * 100, 1) if meta_diaria_rede else None
        ),
        "unidades": rows,
        "top5": com_meta_sorted[:5],
        "bottom5": com_meta_sorted[-5:][::-1],
    }


def get_meta_mensal(media_hist: dict[int, float] = None) -> dict:
    """Retorna acumulado do mês corrente vs meta por unidade."""
    if media_hist is None:
        media_hist = {}

    hoje = date.today()
    rows = _query(
        """
        SELECT
            u.id            AS unidade_id,
            u.nome          AS unidade_nome,
            SUM(v.valor_total)               AS acumulado_mes,
            COUNT(v.id)                      AS total_vendas_mes
        FROM vendas v
        JOIN usuarios usr ON usr.id = v.usuario
        JOIN unidades u   ON u.id  = usr.unidade
        WHERE YEAR(v.data_criacao)  = %s
          AND MONTH(v.data_criacao) = %s
          AND v.status = 1
          AND v.comanda_temp = 0
        GROUP BY u.id, u.nome
        ORDER BY u.nome
        """,
        (hoje.year, hoje.month),
    )

    for r in rows:
        uid = r["unidade_id"]
        meta = _resolve_meta(uid, media_hist)
        r["meta_mensal"] = round(meta, 2) if meta else None
        r["meta_origem"] = (
            "manual" if uid in MANUAL_METAS
            else "historica" if uid in media_hist
            else None
        )
        r["pct_meta_mensal"] = (
            round(float(r["acumulado_mes"]) / meta * 100, 1)
            if meta
            else None
        )

    total_rede_mes = sum(float(r["acumulado_mes"]) for r in rows)
    total_meta_rede = sum(r["meta_mensal"] for r in rows if r["meta_mensal"])

    # Dias corridos / dias no mês (para calcular % esperado)
    dias_corridos = hoje.day
    dias_mes = calendar.monthrange(hoje.year, hoje.month)[1]
    pct_mes_corrido = round(dias_corridos / dias_mes * 100, 1)

    return {
        "acumulado_rede": round(total_rede_mes, 2),
        "meta_rede": round(total_meta_rede, 2),
        "pct_rede": (
            round(total_rede_mes / total_meta_rede * 100, 1) if total_meta_rede else None
        ),
        "pct_mes_corrido": pct_mes_corrido,
        "unidades": rows,
    }


def get_agenda_ontem() -> dict[str, Any]:
    """Retorna métricas de agenda do dia anterior por unidade.

    Lógica dos campos da tabela `agendas`:
    - fechamento IS NOT NULL → slot bloqueado (fechamento de agenda), NÃO é no-show
    - fechamento IS NULL     → agendamento real de cliente
    - checkin = 1            → cliente compareceu (realizado)
    - checkin = 0 AND fechamento IS NULL → no-show real
    """
    ontem = date.today() - timedelta(days=1)
    rows = _query(
        """
        SELECT
            u.id   AS unidade_id,
            u.nome AS unidade_nome,
            u.cidade,
            SUM(a.fechamento IS NULL)                                      AS total,
            SUM(a.checkin = 1)                                             AS realizados,
            SUM(a.checkin = 0 AND a.fechamento IS NULL)                    AS noshows,
            SUM(a.fechamento IS NOT NULL)                                  AS fechamentos,
            SUM(a.fechamento IS NULL AND LOWER(a.origem) = 'app')          AS agend_app,
            SUM(a.fechamento IS NULL AND LOWER(a.origem) != 'app')         AS agend_recepcao
        FROM agendas a
        JOIN usuarios usr ON usr.id = a.colaborador
        JOIN unidades u   ON u.id  = usr.unidade
        WHERE DATE(a.data) = %s
          AND a.status = 1
        GROUP BY u.id, u.nome, u.cidade
        ORDER BY u.nome
        """,
        (ontem,),
    )

    total_agendamentos = sum(r["total"] or 0 for r in rows)
    total_realizados = sum(r["realizados"] or 0 for r in rows)
    total_noshows = sum(r["noshows"] or 0 for r in rows)
    total_fechamentos = sum(r["fechamentos"] or 0 for r in rows)
    total_app = sum(r["agend_app"] or 0 for r in rows)
    total_recepcao = sum(r["agend_recepcao"] or 0 for r in rows)

    ocupacao_rede = (
        round(total_realizados / total_agendamentos * 100, 1)
        if total_agendamentos
        else 0
    )

    return {
        "data": str(ontem),
        "total_agendamentos": total_agendamentos,
        "total_realizados": total_realizados,
        "total_noshows": total_noshows,
        "total_fechamentos": total_fechamentos,
        "total_app": total_app,
        "total_recepcao": total_recepcao,
        "ocupacao_rede_pct": ocupacao_rede,
        "unidades": rows,
    }


def get_barbeiros_ausentes() -> list[dict]:
    """Retorna colaboradores que não abriram caixa hoje."""
    hoje = date.today()
    rows = _query(
        """
        SELECT
            u.nome AS unidade_nome,
            usr.nome AS barbeiro_nome,
            usr.telefone
        FROM usuarios usr
        JOIN grupos g   ON g.id  = usr.grupo
        JOIN unidades u ON u.id  = usr.unidade
        WHERE g.colaborador = 1
          AND usr.status = 1
          AND u.status = 1
          AND usr.id NOT IN (
              SELECT c.usuario
              FROM caixas c
              WHERE DATE(c.data_criacao) = %s
                AND c.status = 1
          )
        ORDER BY u.nome, usr.nome
        """,
        (hoje,),
    )
    return list(rows)


def get_royalties_inadimplentes() -> dict[str, list]:
    """
    Retorna faturas com asaas_status = 'OVERDUE'.
    Distingue royalties de fundo de publicidade pelo campo descricao.
    """
    rows = _query(
        """
        SELECT
            u.nome             AS unidade_nome,
            u.cidade,
            u.estado,
            rf.valor,
            rf.vencimento,
            rf.descricao,
            rf.asaas_status,
            rf.asaas_link_cobranca,
            DATEDIFF(CURDATE(), rf.vencimento) AS dias_atraso
        FROM royalties_faturas rf
        JOIN unidades u ON u.id = rf.unidade
        WHERE rf.asaas_status = 'OVERDUE'
        ORDER BY dias_atraso DESC
        """
    )

    royalties = []
    fundo = []
    for r in rows:
        desc = (r.get("descricao") or "").upper()
        if "FUNDO" in desc or "PUBLICIDADE" in desc or "PROPAGANDA" in desc:
            fundo.append(r)
        else:
            royalties.append(r)

    return {"royalties": royalties, "fundo_publicidade": fundo}


def get_aniversarios_hoje() -> list[dict]:
    """Retorna aniversários de sócios e inaugurações de unidades para hoje."""
    hoje = date.today()
    rows = _query(
        """
        SELECT
            us.nome          AS nome,
            u.nome           AS unidade_nome,
            u.cidade,
            'socio'          AS tipo,
            TIMESTAMPDIFF(YEAR, us.data_nascimento, CURDATE()) AS anos
        FROM unidades_socios us
        JOIN unidades u ON u.id = us.unidade
        WHERE DAY(us.data_nascimento)   = %s
          AND MONTH(us.data_nascimento) = %s
          AND us.status = 1

        UNION ALL

        SELECT
            u.nome           AS nome,
            u.nome           AS unidade_nome,
            u.cidade,
            'inauguracao'    AS tipo,
            TIMESTAMPDIFF(YEAR, u.data_inauguracao, CURDATE()) AS anos
        FROM unidades u
        WHERE u.data_inauguracao IS NOT NULL
          AND DAY(u.data_inauguracao)   = %s
          AND MONTH(u.data_inauguracao) = %s
          AND u.status = 1
        ORDER BY anos DESC
        """,
        (hoje.day, hoje.month, hoje.day, hoje.month),
    )
    return list(rows)


def collect_all() -> dict[str, Any]:
    """Executa todas as queries e retorna dict consolidado. Falhas parciais são logadas."""
    result = {}

    # Carrega médias históricas primeiro (usado como fallback de meta)
    media_hist = {}
    try:
        media_hist = get_media_historica()
        logger.info(
            "Médias históricas carregadas: %d unidades (metas manuais: %d)",
            len(media_hist), len(MANUAL_METAS),
        )
    except Exception as exc:
        logger.error("Falha ao carregar médias históricas: %s", exc, exc_info=True)

    collectors = {
        "faturamento": lambda: get_faturamento_ontem(media_hist),
        "meta_mensal": lambda: get_meta_mensal(media_hist),
        "agenda": get_agenda_ontem,
        "inadimplencia": get_royalties_inadimplentes,
        "aniversarios": get_aniversarios_hoje,
    }

    for name, fn in collectors.items():
        try:
            result[name] = fn()
        except Exception as exc:
            logger.error("ERP collector '%s' falhou: %s", name, exc, exc_info=True)
            result[name] = None

    return result
