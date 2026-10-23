"""Coleta consolidada do briefing diário, parametrizada por data de referência.

Sem logging.basicConfig nem handlers: importável tanto pelo serviço (main.py)
quanto pelo app administrativo, cada um com seu próprio log.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Optional

import config
from collectors import erp_mysql, google_reviews, perfex_crm, satisfycam

logger = logging.getLogger("briefing")


def collect_all_data(hoje: Optional[date] = None) -> dict:
    """Executa todos os collectors em paralelo para a data de referência `hoje`
    (padrão: hoje no fuso do projeto). 'Ontem' nos relatórios é `hoje - 1`.

    Google Reviews não tem histórico: em data retroativa é pulado.
    """
    hoje = hoje or config.hoje_local()
    retroativo = hoje != config.hoje_local()

    tasks = {
        "erp": lambda: erp_mysql.collect_all(hoje),
        # Sem data (None) o Perfex mantem a janela atual "ultimas 24h"; so em
        # relatorio retroativo filtra pelo dia hoje-1 (spec §3).
        "perfex": lambda: perfex_crm.collect_all(hoje if retroativo else None),
    }
    if not retroativo:
        tasks["satisfycam"] = lambda: satisfycam.collect_all(hoje)
        tasks["google"] = google_reviews.collect_all

    results: dict = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                logger.error("Collector '%s' lançou exceção: %s", name, exc, exc_info=True)
                results[name] = {}

    if retroativo:
        results["google"] = {"reviews": None, "retroativo": True}
        results["satisfycam"] = {"relatorio": None, "retroativo": True}

    erp = results.pop("erp", {}) or {}
    data = {**erp, **results}
    data["retroativo"] = retroativo      # o template usa para rotular "situacao atual"/"indisponivel"
    return data
