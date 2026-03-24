"""
Daily Briefing — Barbearia VIP
Coleta dados, gera HTML e envia WhatsApp às 8h.

Uso:
  python main.py            → modo produção (cron às 8h)
  python main.py --test     → executa imediatamente e envia WhatsApp
  python main.py --dry      → executa imediatamente, gera HTML, NÃO envia WhatsApp
"""

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from logging.handlers import RotatingFileHandler

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from collectors import erp_mysql, perfex_crm, satisfycam, google_reviews
from composers import (
    whatsapp_message, html_dashboard, whatsapp_unit_message,
    whatsapp_weekly_message, whatsapp_monthly_message,
    html_periodic_dashboard,
)
from senders import waha

# ── Logging ─────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(__file__)
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"

_LOG_FILE = os.path.join(_BASE_DIR, "daily.log")
_LOG_FILE_WEEKLY = os.path.join(_BASE_DIR, "weekly.log")
_LOG_FILE_MONTHLY = os.path.join(_BASE_DIR, "monthly.log")

_handlers = []
try:
    _handlers.append(RotatingFileHandler(_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=7))
except PermissionError:
    print(f"[WARN] Sem permissão para {_LOG_FILE} — log apenas no stdout", file=sys.stderr)

# Só adiciona StreamHandler se NÃO estiver rodando via systemd (evita duplicação)
if sys.stdout.isatty() or not _handlers:
    _handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format=_LOG_FORMAT,
    handlers=_handlers,
)
logger = logging.getLogger("briefing")


def _add_file_handler(log_path: str):
    """Adiciona handler de arquivo temporário ao root logger e retorna o handler."""
    try:
        fh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=7)
        fh.setFormatter(logging.Formatter(_LOG_FORMAT))
        logging.getLogger().addHandler(fh)
        return fh
    except PermissionError:
        logger.warning("Sem permissão para %s", log_path)
        return None


def _remove_file_handler(fh):
    """Remove handler de arquivo do root logger."""
    if fh:
        logging.getLogger().removeHandler(fh)
        fh.close()


# ── Coleta de dados ──────────────────────────────────────────────────────────

def _collect_erp() -> dict:
    logger.info("Coletando dados do ERP MySQL...")
    return erp_mysql.collect_all()


def _collect_perfex() -> dict:
    logger.info("Coletando dados do Perfex CRM...")
    return perfex_crm.collect_all()


def _collect_satisfycam() -> dict:
    logger.info("Coletando dados do SatisfyCAM...")
    return satisfycam.collect_all()


def _collect_google() -> dict:
    logger.info("Coletando dados do Google Reviews...")
    return google_reviews.collect_all()


def collect_all_data() -> dict:
    """Executa todos os collectors em paralelo e consolida o resultado."""
    tasks = {
        "erp": _collect_erp,
        "perfex": _collect_perfex,
        "satisfycam": _collect_satisfycam,
        "google": _collect_google,
    }

    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                logger.error("Collector '%s' lançou exceção: %s", name, exc, exc_info=True)
                results[name] = {}

    # Achata os dados do ERP no nível raiz para o composer
    erp = results.pop("erp", {})
    data = {**erp, **results}

    return data


# ── Execução principal ────────────────────────────────────────────────────────

def run_briefing(dry_run: bool = False) -> None:
    logger.info("=== Iniciando briefing diário %s ===", date.today())

    # 1. Coleta
    data = collect_all_data()

    # 2. Gera HTML
    try:
        filepath = html_dashboard.generate(data)
        filename = os.path.basename(filepath)
        dashboard_url = f"{config.DASHBOARD_BASE_URL}/{filename}"
        data["dashboard_url"] = dashboard_url
        logger.info("Dashboard HTML salvo: %s", filepath)
    except Exception as exc:
        logger.error("Falha ao gerar HTML: %s", exc, exc_info=True)
        data["dashboard_url"] = ""

    # 3. Compõe mensagem
    try:
        mensagem = whatsapp_message.compose(data)
    except Exception as exc:
        logger.error("Falha ao compor mensagem: %s", exc, exc_info=True)
        mensagem = f"⚠️ Erro ao gerar briefing VIP {date.today()}. Verifique daily.log."

    # 4. Compõe mensagens individuais por unidade
    unit_messages = {}
    unit_groups = config.UNIT_GROUPS
    if unit_groups:
        for uid_str, group_info in unit_groups.items():
            try:
                uid = int(uid_str)
                nome = group_info.get("nome", f"Unidade #{uid}")
                chat_id = group_info.get("chat_id", "")
                if not chat_id:
                    continue
                msg = whatsapp_unit_message.compose_for_unit(data, uid, nome)
                unit_messages[chat_id] = {"nome": nome, "mensagem": msg}
            except (ValueError, Exception) as exc:
                logger.warning("Erro ao compor briefing unidade %s: %s", uid_str, exc)

    # 5. Envia WhatsApp
    if dry_run:
        logger.info("DRY RUN — mensagem não enviada.")
        print("\n" + "=" * 60)
        print("📢 BRIEFING GERAL (Franqueadora)")
        print("=" * 60)
        print(mensagem)
        print("=" * 60 + "\n")

        if unit_messages:
            print(f"📍 BRIEFINGS INDIVIDUAIS — {len(unit_messages)} unidade(s)")
            print("=" * 60)
            for chat_id, info in list(unit_messages.items())[:3]:
                print(f"\n--- {info['nome']} ({chat_id}) ---")
                print(info["mensagem"])
            if len(unit_messages) > 3:
                print(f"\n... e mais {len(unit_messages) - 3} unidade(s)")
            print("=" * 60 + "\n")
        else:
            logger.info("Nenhum grupo de unidade configurado em config/unit_groups.json")
    else:
        # Envia briefing geral para franqueadora
        if not config.WAHA_RECIPIENTS:
            logger.warning("Nenhum destinatário configurado em WAHA_RECIPIENTS.")
        else:
            results = waha.broadcast(mensagem)
            ok = sum(v for v in results.values())
            logger.info("WhatsApp geral: %d/%d enviados.", ok, len(results))

        # Envia briefings individuais para cada franqueado
        if unit_messages:
            import time
            ok_units = 0
            for chat_id, info in unit_messages.items():
                success = waha.send_text(chat_id, info["mensagem"])
                if success:
                    ok_units += 1
                time.sleep(1.5)  # Intervalo entre envios para não sobrecarregar WAHA
            logger.info(
                "WhatsApp unidades: %d/%d enviados.", ok_units, len(unit_messages)
            )

    logger.info("=== Briefing concluído ===")


# ── Briefing Semanal (segunda-feira 7h, franqueadora) ─────────────────────────

def run_weekly_briefing(dry_run: bool = False) -> None:
    import calendar
    fh = _add_file_handler(_LOG_FILE_WEEKLY)
    logger.info("=== Iniciando briefing SEMANAL %s ===", date.today())

    today = date.today()
    # Semana anterior: segunda a domingo
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    data_fim_exclusive = last_sunday + timedelta(days=1)
    logger.info("Período: %s a %s", last_monday, last_sunday)

    # 1. Coleta com range
    data = erp_mysql.collect_range(last_monday, data_fim_exclusive, tipo="semanal")

    # Adiciona Perfex (pipeline + leads da semana)
    try:
        data["perfex"] = perfex_crm.collect_periodo(last_monday, last_sunday)
    except Exception as exc:
        logger.error("Perfex CRM falhou: %s", exc)

    # 2. Gera HTML
    try:
        filepath = html_periodic_dashboard.generate(data, last_monday, last_sunday, tipo="semanal")
        filename = os.path.basename(filepath)
        dashboard_url = f"{config.DASHBOARD_BASE_URL}/{filename}"
        data["dashboard_url"] = dashboard_url
        logger.info("Dashboard semanal: %s", filepath)
    except Exception as exc:
        logger.error("Falha ao gerar HTML semanal: %s", exc, exc_info=True)
        data["dashboard_url"] = ""

    # 3. Compõe mensagem
    try:
        mensagem = whatsapp_weekly_message.compose(data, last_monday, last_sunday)
    except Exception as exc:
        logger.error("Falha ao compor mensagem semanal: %s", exc, exc_info=True)
        mensagem = f"⚠️ Erro ao gerar resumo semanal VIP {date.today()}. Verifique weekly.log."

    # 4. Envia / Preview
    if dry_run:
        logger.info("DRY RUN — mensagem semanal não enviada.")
        print("\n" + "=" * 60)
        print("📢 RESUMO SEMANAL (Franqueadora)")
        print("=" * 60)
        print(mensagem)
        print("=" * 60 + "\n")
    else:
        if config.WAHA_RECIPIENTS:
            results = waha.broadcast(mensagem)
            ok = sum(v for v in results.values())
            logger.info("WhatsApp semanal: %d/%d enviados.", ok, len(results))
        else:
            logger.warning("Nenhum destinatário configurado em WAHA_RECIPIENTS.")

    logger.info("=== Briefing semanal concluído ===")
    _remove_file_handler(fh)


# ── Briefing Mensal (dia 1, 9h, franqueadora) ────────────────────────────────

def run_monthly_briefing(dry_run: bool = False) -> None:
    import calendar
    fh = _add_file_handler(_LOG_FILE_MONTHLY)
    logger.info("=== Iniciando briefing MENSAL %s ===", date.today())

    today = date.today()
    # Mês anterior
    if today.month == 1:
        prev_month, prev_year = 12, today.year - 1
    else:
        prev_month, prev_year = today.month - 1, today.year

    data_inicio = date(prev_year, prev_month, 1)
    last_day = calendar.monthrange(prev_year, prev_month)[1]
    data_fim_inclusive = date(prev_year, prev_month, last_day)
    data_fim_exclusive = data_fim_inclusive + timedelta(days=1)
    logger.info("Período: %s a %s", data_inicio, data_fim_inclusive)

    # 1. Coleta com range
    data = erp_mysql.collect_range(data_inicio, data_fim_exclusive, tipo="mensal")

    # Adiciona Perfex (pipeline + leads do mês)
    try:
        data["perfex"] = perfex_crm.collect_periodo(data_inicio, data_fim_inclusive)
    except Exception as exc:
        logger.error("Perfex CRM falhou: %s", exc)

    # 2. Gera HTML
    try:
        filepath = html_periodic_dashboard.generate(data, data_inicio, data_fim_inclusive, tipo="mensal")
        filename = os.path.basename(filepath)
        dashboard_url = f"{config.DASHBOARD_BASE_URL}/{filename}"
        data["dashboard_url"] = dashboard_url
        logger.info("Dashboard mensal: %s", filepath)
    except Exception as exc:
        logger.error("Falha ao gerar HTML mensal: %s", exc, exc_info=True)
        data["dashboard_url"] = ""

    # 3. Compõe mensagem
    try:
        mensagem = whatsapp_monthly_message.compose(data, data_inicio, data_fim_inclusive)
    except Exception as exc:
        logger.error("Falha ao compor mensagem mensal: %s", exc, exc_info=True)
        mensagem = f"⚠️ Erro ao gerar resumo mensal VIP {date.today()}. Verifique monthly.log."

    # 4. Envia / Preview
    if dry_run:
        logger.info("DRY RUN — mensagem mensal não enviada.")
        print("\n" + "=" * 60)
        print("📢 RESUMO MENSAL (Franqueadora)")
        print("=" * 60)
        print(mensagem)
        print("=" * 60 + "\n")
    else:
        if config.WAHA_RECIPIENTS:
            results = waha.broadcast(mensagem)
            ok = sum(v for v in results.values())
            logger.info("WhatsApp mensal: %d/%d enviados.", ok, len(results))
        else:
            logger.warning("Nenhum destinatário configurado em WAHA_RECIPIENTS.")

    logger.info("=== Briefing mensal concluído ===")
    _remove_file_handler(fh)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Daily Briefing — Barbearia VIP")
    parser.add_argument(
        "--test", action="store_true",
        help="Executa imediatamente e envia WhatsApp (sem aguardar o cron)"
    )
    parser.add_argument(
        "--dry", action="store_true",
        help="Executa imediatamente, gera HTML, mas NÃO envia WhatsApp"
    )
    parser.add_argument(
        "--test-weekly", action="store_true",
        help="Executa briefing semanal imediatamente e envia"
    )
    parser.add_argument(
        "--dry-weekly", action="store_true",
        help="Executa briefing semanal imediatamente, NÃO envia"
    )
    parser.add_argument(
        "--test-monthly", action="store_true",
        help="Executa briefing mensal imediatamente e envia"
    )
    parser.add_argument(
        "--dry-monthly", action="store_true",
        help="Executa briefing mensal imediatamente, NÃO envia"
    )
    args = parser.parse_args()

    if args.test_weekly or args.dry_weekly:
        run_weekly_briefing(dry_run=args.dry_weekly)
        return

    if args.test_monthly or args.dry_monthly:
        run_monthly_briefing(dry_run=args.dry_monthly)
        return

    if args.test or args.dry:
        run_briefing(dry_run=args.dry)
        return

    # Modo produção: scheduler bloqueante
    scheduler = BlockingScheduler(timezone=config.TIMEZONE)
    scheduler.add_job(
        run_briefing,
        trigger=CronTrigger(
            hour=config.BRIEFING_HOUR,
            minute=config.BRIEFING_MINUTE,
            timezone=config.TIMEZONE,
        ),
        id="daily_briefing",
        name="Daily Briefing VIP",
        replace_existing=True,
    )

    # Semanal: segunda-feira
    scheduler.add_job(
        run_weekly_briefing,
        trigger=CronTrigger(
            day_of_week="mon",
            hour=config.WEEKLY_BRIEFING_HOUR,
            minute=config.WEEKLY_BRIEFING_MINUTE,
            timezone=config.TIMEZONE,
        ),
        id="weekly_briefing",
        name="Weekly Briefing VIP",
        replace_existing=True,
    )

    # Mensal: dia 1
    scheduler.add_job(
        run_monthly_briefing,
        trigger=CronTrigger(
            day=1,
            hour=config.MONTHLY_BRIEFING_HOUR,
            minute=config.MONTHLY_BRIEFING_MINUTE,
            timezone=config.TIMEZONE,
        ),
        id="monthly_briefing",
        name="Monthly Briefing VIP",
        replace_existing=True,
    )

    logger.info(
        "Scheduler iniciado. Diário: %02d:%02d | Semanal: seg %02d:%02d | Mensal: dia 1 %02d:%02d (%s)",
        config.BRIEFING_HOUR, config.BRIEFING_MINUTE,
        config.WEEKLY_BRIEFING_HOUR, config.WEEKLY_BRIEFING_MINUTE,
        config.MONTHLY_BRIEFING_HOUR, config.MONTHLY_BRIEFING_MINUTE,
        config.TIMEZONE,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler encerrado.")


if __name__ == "__main__":
    main()
