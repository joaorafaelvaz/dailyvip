"""Rotina diária: avisa cada unidade (que optou por receber) dos clientes aniversariantes do dia.

Ativação por unidade: campo `"aniversarios": true` na entrada da unidade em
config/unit_groups.json. Sem o campo (ou false), a unidade não recebe. Os destinatários
são os mesmos do briefing (`chat_id` / `chat_ids`). Unidade sem aniversariante não recebe nada.
"""

import logging
import time
from datetime import date
from typing import Any, Optional

import config
from collectors import erp_mysql
from composers import whatsapp_aniversarios_message
from senders import waha

logger = logging.getLogger("briefing")

_INTERVALO_ENVIOS_S = 1.5


def chat_ids_de(entry: dict) -> list[str]:
    """Destinatários de uma entrada do unit_groups.json: `chat_id` e/ou `chat_ids`, sem repetição."""
    ids: list[str] = []
    if entry.get("chat_id"):
        ids.append(entry["chat_id"])
    for cid in entry.get("chat_ids") or []:
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def unidades_ativas(unit_groups: dict[str, dict], only_unit: Optional[int] = None) -> dict[int, dict]:
    """Unidades que recebem a lista: flag `aniversarios` ligada, ou apenas `only_unit` (ignora a flag)."""
    ativas: dict[int, dict] = {}
    for uid_str, entry in (unit_groups or {}).items():
        try:
            uid = int(uid_str)
        except (TypeError, ValueError):
            logger.warning("unit_groups.json: id de unidade inválido %r — ignorado", uid_str)
            continue
        if only_unit is not None:
            if uid == only_unit:
                ativas[uid] = entry
            continue
        if entry.get("aniversarios") is True:
            ativas[uid] = entry
    return ativas


def montar_envios(
    rows: list[dict],
    unit_groups: dict[str, dict],
    hoje: Optional[date] = None,
    only_unit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Agrupa os aniversariantes por unidade ativa e monta um envio por chat_id."""
    hoje = hoje or config.hoje_local()
    ativas = unidades_ativas(unit_groups, only_unit)
    por_unidade: dict[int, list[dict]] = {}
    for r in rows:
        try:
            uid = int(r.get("unidade_id"))
        except (TypeError, ValueError):
            continue
        if uid in ativas:
            por_unidade.setdefault(uid, []).append(r)

    envios: list[dict[str, Any]] = []
    for uid, entry in ativas.items():
        clientes = por_unidade.get(uid) or []
        if not clientes:
            continue
        chat_ids = chat_ids_de(entry)
        if not chat_ids:
            logger.warning("Unidade %s tem aniversariantes mas nenhum chat_id em unit_groups.json", uid)
            continue
        nome = entry.get("nome") or clientes[0].get("unidade_nome") or f"Unidade #{uid}"
        mensagem = whatsapp_aniversarios_message.compose_for_unit(clientes, nome, hoje)
        for chat_id in chat_ids:
            envios.append({
                "unidade_id": uid, "nome": nome, "chat_id": chat_id,
                "mensagem": mensagem, "total": len(clientes),
            })
    return envios


def run_aniversarios(dry_run: bool = False, only_unit: Optional[int] = None) -> dict[str, int]:
    """Coleta, compõe e envia (ou exibe) a lista de aniversariantes das unidades ativas."""
    hoje = config.hoje_local()
    logger.info("=== Aniversariantes do dia %s (dry_run=%s, only_unit=%s) ===", hoje, dry_run, only_unit)
    resumo = {"unidades_ativas": 0, "clientes": 0, "envios": 0, "enviados": 0}

    unit_groups = config.UNIT_GROUPS
    ativas = unidades_ativas(unit_groups, only_unit)
    resumo["unidades_ativas"] = len(ativas)
    if not ativas:
        logger.info("Nenhuma unidade com \"aniversarios\": true em config/unit_groups.json — nada a fazer.")
        return resumo

    try:
        rows = erp_mysql.get_aniversariantes_clientes(hoje=hoje)
    except Exception as exc:
        logger.error("Falha ao consultar aniversariantes no ERP: %s", exc, exc_info=True)
        return resumo
    resumo["clientes"] = sum(1 for r in rows if _uid(r) in ativas)

    envios = montar_envios(rows, unit_groups, hoje, only_unit)
    resumo["envios"] = len(envios)
    if not envios:
        logger.info("Nenhum aniversariante hoje nas %d unidade(s) ativa(s).", len(ativas))
        return resumo

    if dry_run:
        print("\n" + "=" * 60)
        print(f"🎂 ANIVERSARIANTES — {len(envios)} envio(s) (NÃO enviado)")
        print("=" * 60)
        for e in envios:
            print(f"\n--- {e['nome']} (ID {e['unidade_id']} → {e['chat_id']}) ---")
            print(e["mensagem"])
        print("=" * 60 + "\n")
        return resumo

    for i, e in enumerate(envios):
        if waha.send_text(e["chat_id"], e["mensagem"]):
            resumo["enviados"] += 1
        else:
            logger.warning("Falha ao enviar aniversariantes da unidade %s para %s", e["unidade_id"], e["chat_id"])
        if i < len(envios) - 1:
            time.sleep(_INTERVALO_ENVIOS_S)
    logger.info("Aniversariantes: %d/%d envios ok (%d cliente(s)).", resumo["enviados"], len(envios), resumo["clientes"])
    return resumo


def _uid(row: dict) -> Optional[int]:
    try:
        return int(row.get("unidade_id"))
    except (TypeError, ValueError):
        return None
