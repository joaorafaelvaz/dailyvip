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
from datetime import date
from logging.handlers import RotatingFileHandler

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from collectors import erp_mysql, perfex_crm, satisfycam, google_reviews
from composers import whatsapp_message, html_dashboard, whatsapp_unit_message
from senders import waha

# ── Logging ─────────────────────────────────────────────────────────────────
_LOG_FILE = os.path.join(os.path.dirname(__file__), "daily.log")

_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _handlers.insert(0, RotatingFileHandler(_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=7))
except PermissionError:
    print(f"[WARN] Sem permissão para {_LOG_FILE} — log apenas no stdout", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=_handlers,
)
logger = logging.getLogger("briefing")


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
    args = parser.parse_args()

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

    logger.info(
        "Scheduler iniciado. Próximo briefing: %02d:%02d (%s)",
        config.BRIEFING_HOUR, config.BRIEFING_MINUTE, config.TIMEZONE,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler encerrado.")


if __name__ == "__main__":
    main()
