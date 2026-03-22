"""Gera o dashboard HTML periódico (semanal ou mensal) a partir dos dados coletados."""

import logging
import os
from datetime import date
from typing import Any

from jinja2 import Environment, FileSystemLoader

import config

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

_MESES = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def generate(data: dict[str, Any], data_inicio: date, data_fim: date, tipo: str = "semanal") -> str:
    """
    Renderiza o template HTML do dashboard periódico e salva em output/.

    Args:
        data: dict consolidado de todos os collectors.
        data_inicio: data de início do período.
        data_fim: data de fim do período.
        tipo: 'semanal' ou 'mensal'.

    Returns:
        Caminho completo do arquivo gerado.
    """
    env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), autoescape=True)
    env.filters["brl"] = _fmt_brl
    env.filters["pct"] = _fmt_pct

    if tipo == "mensal":
        mes_nome = _MESES.get(data_inicio.month, str(data_inicio.month))
        periodo_label = f"Mês {mes_nome}/{data_inicio.year}"
        filename = f"briefing-mensal-{data_inicio.strftime('%m-%Y')}.html"
    else:
        periodo_label = (
            f"Semana {data_inicio.strftime('%d/%m')} - {data_fim.strftime('%d/%m')}"
        )
        filename = f"briefing-semanal-{data_fim.strftime('%d-%m-%Y')}.html"

    template = env.get_template("dashboard.html.j2")
    html = template.render(
        data=data,
        hoje=date.today(),
        periodo_tipo=tipo,
        periodo_label=periodo_label,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    filepath = os.path.join(config.OUTPUT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Dashboard HTML %s gerado: %s", tipo, filepath)
    return filepath


def _fmt_brl(value) -> str:
    try:
        v = float(value or 0)
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ --"


def _fmt_pct(value) -> str:
    if value is None:
        return "--"
    return f"{float(value):.1f}%"
