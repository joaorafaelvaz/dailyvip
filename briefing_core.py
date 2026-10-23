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


# ── Coleta de dados ──────────────────────────────────────────────────────────

def _collect_erp(hoje: date) -> dict:
    logger.info("Coletando dados do ERP MySQL...")
    return erp_mysql.collect_all(hoje)


def _collect_perfex(hoje: Optional[date]) -> dict:
    logger.info("Coletando dados do Perfex CRM...")
    return perfex_crm.collect_all(hoje)


def _collect_satisfycam(hoje: date) -> dict:
    logger.info("Coletando dados do SatisfyCAM...")
    return satisfycam.collect_all(hoje)


def _collect_google() -> dict:
    logger.info("Coletando dados do Google Reviews...")
    return google_reviews.collect_all()


def collect_all_data(hoje: Optional[date] = None) -> dict:
    """Executa todos os collectors em paralelo para a data de referência `hoje`
    (padrão: hoje no fuso do projeto). 'Ontem' nos relatórios é `hoje - 1`.

    Google Reviews e SatisfyCAM não têm histórico: em data retroativa são pulados.
    """
    atual = config.hoje_local()
    hoje = hoje or atual
    retroativo = hoje != atual

    tasks = {
        "erp": lambda: _collect_erp(hoje),
        # Sem data (None) o Perfex mantém a janela atual "últimas 24h"; só em
        # relatório retroativo filtra pelo dia hoje-1 (spec §3).
        "perfex": lambda: _collect_perfex(hoje if retroativo else None),
    }
    if not retroativo:
        tasks["satisfycam"] = lambda: _collect_satisfycam(hoje)
        tasks["google"] = _collect_google

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

    # Achata os dados do ERP no nível raiz para o composer
    erp = results.pop("erp", {}) or {}
    data = {**erp, **results}
    data["retroativo"] = retroativo      # o template usa para rotular "situação atual"/"indisponível"
    return data
