"""Coleta dados do ERP MySQL (franquia_producao)."""

import logging
from datetime import date, timedelta
from typing import Any

import pymysql
import pymysql.cursors

import config

logger = logging.getLogger(__name__)


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


def get_faturamento_ontem() -> dict[str, Any]:
    """
    Retorna faturamento do dia anterior por unidade.
    Inclui top5, bottom5, totais da rede e ticket médio.
    """
    ontem = date.today() - timedelta(days=1)
    rows = _query(
        """
        SELECT
            u.id            AS unidade_id,
            u.nome          AS unidade_nome,
            u.cidade,
            u.estado,
            COALESCE(u.potencial_franquia, 0) AS meta_mensal,
            SUM(v.valor_total)               AS faturamento,
            COUNT(v.id)                      AS total_vendas,
            SUM(v.valor_total) / COUNT(v.id) AS ticket_medio
        FROM vendas v
        JOIN usuarios usr ON usr.id = v.usuario
        JOIN unidades u   ON u.id  = usr.unidade
        WHERE DATE(v.data_criacao) = %s
          AND v.status != 0
          AND v.comanda_temp = 0
        GROUP BY u.id, u.nome, u.cidade, u.estado, u.potencial_franquia
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

    # Calcula meta diária proporcional (meta_mensal / dias_no_mes)
    import calendar
    dias_mes = calendar.monthrange(ontem.year, ontem.month)[1]
    for r in rows:
        r["meta_diaria"] = r["meta_mensal"] / dias_mes if r["meta_mensal"] else 0
        r["pct_meta"] = (
            round(r["faturamento"] / r["meta_diaria"] * 100, 1)
            if r["meta_diaria"]
            else None
        )

    total_rede = sum(r["faturamento"] for r in rows)
    total_vendas_rede = sum(r["total_vendas"] for r in rows)
    ticket_medio_rede = total_rede / total_vendas_rede if total_vendas_rede else 0

    # Ordena por % de meta para top/bottom (apenas unidades com meta definida)
    com_meta = [r for r in rows if r["pct_meta"] is not None]
    com_meta_sorted = sorted(com_meta, key=lambda x: x["pct_meta"], reverse=True)

    return {
        "data": str(ontem),
        "total_rede": round(total_rede, 2),
        "total_vendas_rede": total_vendas_rede,
        "ticket_medio_rede": round(ticket_medio_rede, 2),
        "unidades": rows,
        "top5": com_meta_sorted[:5],
        "bottom5": com_meta_sorted[-5:][::-1],
    }


def get_meta_mensal() -> list[dict]:
    """Retorna acumulado do mês corrente vs meta por unidade."""
    hoje = date.today()
    rows = _query(
        """
        SELECT
            u.id            AS unidade_id,
            u.nome          AS unidade_nome,
            COALESCE(u.potencial_franquia, 0) AS meta_mensal,
            SUM(v.valor_total)               AS acumulado_mes,
            COUNT(v.id)                      AS total_vendas_mes
        FROM vendas v
        JOIN usuarios usr ON usr.id = v.usuario
        JOIN unidades u   ON u.id  = usr.unidade
        WHERE YEAR(v.data_criacao)  = %s
          AND MONTH(v.data_criacao) = %s
          AND v.status != 0
          AND v.comanda_temp = 0
        GROUP BY u.id, u.nome, u.potencial_franquia
        ORDER BY u.nome
        """,
        (hoje.year, hoje.month),
    )

    total_rede_mes = sum(r["acumulado_mes"] for r in rows)
    total_meta_rede = sum(r["meta_mensal"] for r in rows)

    for r in rows:
        r["pct_meta_mensal"] = (
            round(r["acumulado_mes"] / r["meta_mensal"] * 100, 1)
            if r["meta_mensal"]
            else None
        )

    return {
        "acumulado_rede": round(total_rede_mes, 2),
        "meta_rede": round(total_meta_rede, 2),
        "pct_rede": (
            round(total_rede_mes / total_meta_rede * 100, 1) if total_meta_rede else None
        ),
        "unidades": rows,
    }


def get_agenda_ontem() -> dict[str, Any]:
    """Retorna métricas de agenda do dia anterior por unidade."""
    ontem = date.today() - timedelta(days=1)
    rows = _query(
        """
        SELECT
            u.id   AS unidade_id,
            u.nome AS unidade_nome,
            COUNT(a.id)                              AS total,
            SUM(a.checkin = 1)                       AS realizados,
            SUM(a.status = 0)                        AS cancelados,
            SUM(a.status != 0 AND a.checkin = 0)     AS noshows,
            SUM(a.origem = 'APP')                    AS agend_app,
            SUM(a.origem != 'APP')                   AS agend_recepcao
        FROM agendas a
        JOIN usuarios usr ON usr.id = a.colaborador
        JOIN unidades u   ON u.id  = usr.unidade
        WHERE DATE(a.data) = %s
        GROUP BY u.id, u.nome
        ORDER BY u.nome
        """,
        (ontem,),
    )

    total_agendamentos = sum(r["total"] for r in rows)
    total_realizados = sum(r["realizados"] or 0 for r in rows)
    total_cancelados = sum(r["cancelados"] or 0 for r in rows)
    total_noshows = sum(r["noshows"] or 0 for r in rows)
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
        "total_cancelados": total_cancelados,
        "total_noshows": total_noshows,
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

    collectors = {
        "faturamento": get_faturamento_ontem,
        "meta_mensal": get_meta_mensal,
        "agenda": get_agenda_ontem,
        "barbeiros_ausentes": get_barbeiros_ausentes,
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
