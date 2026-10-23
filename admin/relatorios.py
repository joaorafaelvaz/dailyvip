"""Catálogo dos dashboards em output/ e geração sob demanda por data."""
import calendar
import logging
import os
import re
from datetime import date, timedelta
from typing import Optional

import config
from admin.filelock import FileLock, LockBusy

logger = logging.getLogger("admin.relatorios")

TIPOS = ("diario", "semanal", "mensal")
DATA_MINIMA = date(2024, 1, 1)
_RE_DIARIO = re.compile(r"^briefing-(\d{2})-(\d{2})-(\d{4})\.html$")
_RE_SEMANAL = re.compile(r"^briefing-semanal-(\d{2})-(\d{2})-(\d{4})\.html$")
_RE_MENSAL = re.compile(r"^briefing-mensal-(\d{2})-(\d{4})\.html$")


class DataInvalida(ValueError):
    pass


class GeracaoEmAndamento(RuntimeError):
    pass


def _safe_date(y, m, d) -> Optional[date]:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def parse_nome(nome: str):
    """(tipo, data_chave) ou None. Diário: chave = dia dos dados (arquivo - 1);
    semanal = domingo final; mensal = dia 1 do mês."""
    m = _RE_DIARIO.match(nome)
    if m:
        dt = _safe_date(m[3], m[2], m[1])
        return ("diario", dt - timedelta(days=1)) if dt else None
    m = _RE_SEMANAL.match(nome)
    if m:
        dt = _safe_date(m[3], m[2], m[1])
        return ("semanal", dt) if dt else None
    m = _RE_MENSAL.match(nome)
    if m:
        dt = _safe_date(m[2], m[1], 1)
        return ("mensal", dt) if dt else None
    return None


def semana_de(d: date) -> tuple[date, date]:
    """Segunda e domingo da semana que contém `d`."""
    seg = d - timedelta(days=d.weekday())
    return seg, seg + timedelta(days=6)


def nome_para(tipo: str, d: date) -> str:
    if tipo == "diario":
        return f"briefing-{(d + timedelta(days=1)).strftime('%d-%m-%Y')}.html"
    if tipo == "semanal":
        return f"briefing-semanal-{semana_de(d)[1].strftime('%d-%m-%Y')}.html"
    if tipo == "mensal":
        return f"briefing-mensal-{d.strftime('%m-%Y')}.html"
    raise ValueError(tipo)


def existe(tipo: str, d: date) -> bool:
    return os.path.exists(os.path.join(config.OUTPUT_DIR, nome_para(tipo, d)))


def url_de(nome: str) -> str:
    return f"{config.DASHBOARD_BASE_URL}/{nome}"


def listar() -> dict[str, list[dict]]:
    out = {t: [] for t in TIPOS}
    for nome in os.listdir(config.OUTPUT_DIR):
        p = parse_nome(nome)
        if p:
            tipo, d = p
            out[tipo].append({"arquivo": nome, "data": d, "url": url_de(nome)})
    for t in TIPOS:
        out[t].sort(key=lambda x: x["data"], reverse=True)
    return out


def validar_data(tipo: str, d: date) -> None:
    hoje = config.hoje_local()
    if tipo not in TIPOS:
        raise DataInvalida("tipo inválido")
    if d < DATA_MINIMA:
        raise DataInvalida(f"data anterior a {DATA_MINIMA:%d/%m/%Y}")
    if tipo == "diario" and d >= hoje:
        raise DataInvalida("o relatório diário só existe para dias já encerrados (até ontem)")
    if tipo == "semanal" and semana_de(d)[1] >= hoje:
        raise DataInvalida("a semana ainda não terminou")
    if tipo == "mensal" and (d.year, d.month) >= (hoje.year, hoje.month):
        raise DataInvalida("o mês ainda não terminou")


def gerar(tipo: str, d: date) -> str:
    """Gera o dashboard e retorna o nome do arquivo. Não envia WhatsApp."""
    validar_data(tipo, d)
    from briefing_core import collect_all_data
    from collectors import erp_mysql, perfex_crm
    from composers import html_dashboard, html_periodic_dashboard

    try:
        with FileLock(os.path.join(config.DATA_DIR, "gerar.lock")):
            if tipo == "diario":
                hoje = d + timedelta(days=1)
                data = collect_all_data(hoje)
                path = html_dashboard.generate(data, hoje=hoje)
            elif tipo == "semanal":
                seg, dom = semana_de(d)
                ref = dom + timedelta(days=1)
                data = erp_mysql.collect_range(seg, ref, tipo="semanal", hoje=ref)
                data["perfex"] = perfex_crm.collect_periodo(seg, dom)
                data["retroativo"] = True
                path = html_periodic_dashboard.generate(data, seg, dom, tipo="semanal")
            else:
                ini = date(d.year, d.month, 1)
                fim = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
                ref = fim + timedelta(days=1)
                data = erp_mysql.collect_range(ini, ref, tipo="mensal", hoje=ref)
                data["perfex"] = perfex_crm.collect_periodo(ini, fim)
                data["retroativo"] = True
                path = html_periodic_dashboard.generate(data, ini, fim, tipo="mensal")
    except LockBusy:
        raise GeracaoEmAndamento("já há uma geração em andamento; tente em instantes")
    logger.info("Relatório %s gerado sob demanda: %s", tipo, path)
    return os.path.basename(path)
