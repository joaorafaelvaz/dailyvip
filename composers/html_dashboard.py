"""Gera o dashboard HTML completo a partir dos dados coletados."""

import logging
import os
from datetime import date
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader

import config

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")


def generate(data: dict[str, Any], hoje: Optional[date] = None) -> str:
    """
    Renderiza o template HTML e salva o arquivo em output/.

    `hoje` é a data de referência (arquivo briefing-<hoje>.html, conteúdo =
    dia anterior); padrão: hoje no fuso do projeto. `gerado_em` é a hora real
    de geração, usada pelo template no "Gerado às HH:MM".

    Returns:
        Caminho completo do arquivo gerado.
    """
    hoje = hoje or config.hoje_local()
    env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), autoescape=True)
    env.filters["brl"] = _fmt_brl
    env.filters["pct"] = _fmt_pct

    template = env.get_template("dashboard.html.j2")
    html = template.render(
        data=data,
        hoje=hoje,
        gerado_em=config.agora_local(),
        show_satisfycam=config.SHOW_SATISFYCAM,
        show_inadimplencia=config.SHOW_INADIMPLENCIA,
    )

    filename = f"briefing-{hoje.strftime('%d-%m-%Y')}.html"
    filepath = os.path.join(config.OUTPUT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Dashboard HTML gerado: %s", filepath)
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
