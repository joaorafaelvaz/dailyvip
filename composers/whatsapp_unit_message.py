"""Formata briefing individual por unidade para envio ao grupo do franqueado."""

from datetime import date
from decimal import Decimal
from typing import Any, Optional


def _fmt_brl(value) -> str:
    try:
        v = float(value or 0)
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ --"


def _fmt_pct(value) -> str:
    if value is None:
        return "--"
    return f"{value:.1f}%"


def _short_name(row: dict) -> str:
    cidade = row.get("cidade", "")
    nome = row.get("unidade_nome", "")
    if cidade and " - " in nome:
        parts = nome.split(" - ")
        bairro = parts[-1].strip()
        return f"{cidade} - {bairro}"
    return nome


def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


def _find_unit(rows: list[dict], unidade_id: int) -> Optional[dict]:
    """Encontra uma unidade pelo ID em uma lista de rows."""
    for r in rows:
        if r.get("unidade_id") == unidade_id:
            return r
    return None


def compose_for_unit(data: dict[str, Any], unidade_id: int, unidade_nome: str = "") -> str:
    """
    Gera mensagem de briefing específica para uma unidade.

    Inclui:
    - Performance da unidade vs. média da rede
    - Agenda da unidade
    - Inadimplência da unidade (se houver)
    - Barbeiros ausentes da unidade
    - Link para dashboard completo
    """
    hoje = date.today().strftime("%d/%m/%Y")
    lines = []

    # ── Cabeçalho ──────────────────────────────────────────────
    display_name = unidade_nome or f"Unidade #{unidade_id}"
    lines.append(f"📊 *BRIEFING DIÁRIO* — {hoje}")
    lines.append(f"📍 *{display_name}*")
    lines.append(_sep())

    # ── Faturamento da unidade vs rede ─────────────────────────
    fat = data.get("faturamento")
    if fat and fat.get("unidades"):
        unit_data = _find_unit(fat["unidades"], unidade_id)
        if unit_data:
            faturamento = float(unit_data.get("faturamento") or 0)
            ticket = float(unit_data.get("ticket_medio") or 0)
            total_vendas = unit_data.get("total_vendas", 0)
            ticket_rede = float(fat.get("ticket_medio_rede") or 0)

            lines.append("💰 *FATURAMENTO ONTEM*")
            lines.append(f"Faturamento: *{_fmt_brl(faturamento)}*")
            lines.append(f"Vendas: *{total_vendas}* | Ticket médio: *{_fmt_brl(ticket)}*")

            # Comparação com a rede
            if ticket_rede > 0:
                diff_ticket = ((ticket - ticket_rede) / ticket_rede) * 100
                emoji = "🔼" if diff_ticket >= 0 else "🔽"
                lines.append(
                    f"Ticket rede: {_fmt_brl(ticket_rede)} | "
                    f"Sua unidade: {emoji} {diff_ticket:+.1f}%"
                )

            total_rede = float(fat.get("total_rede") or 0)
            if total_rede > 0:
                participacao = (faturamento / total_rede) * 100
                lines.append(f"Participação na rede: *{participacao:.1f}%*")
        else:
            lines.append("💰 *FATURAMENTO ONTEM*")
            lines.append("⚠️ _Sem dados de faturamento para esta unidade_")
    else:
        lines.append("💰 *FATURAMENTO ONTEM*")
        lines.append("⚠️ _Dados indisponíveis_")

    # ── Agenda da unidade ──────────────────────────────────────
    agenda = data.get("agenda")
    lines.append(f"\n{_sep()}")
    lines.append("📅 *AGENDA ONTEM*")
    if agenda and agenda.get("unidades"):
        unit_agenda = _find_unit(agenda["unidades"], unidade_id)
        if unit_agenda:
            total_slots = int(unit_agenda.get("total_slots") or 0)
            ocupados = int(unit_agenda.get("ocupados") or 0)
            realizados = int(unit_agenda.get("realizados") or 0)
            noshows = int(unit_agenda.get("noshows") or 0)
            fechamentos = int(unit_agenda.get("fechamentos") or 0)
            app = int(unit_agenda.get("agend_app") or 0)
            recepcao = int(unit_agenda.get("agend_recepcao") or 0)

            ocupacao = float(unit_agenda.get("ocupacao_pct") or 0)
            ocupacao_rede = float(agenda.get("ocupacao_rede_pct") or 0)

            lines.append(f"Ocupação: *{ocupacao:.1f}%* ({ocupados}/{total_slots} slots)")
            lines.append(f"Realizados: *{realizados}* | Ocupação rede: {ocupacao_rede:.1f}%")
            lines.append(f"🚫 No-shows: *{noshows}* | 🔒 Fechamentos: *{fechamentos}*")
            lines.append(f"📱 App: *{app}* | Recepção: *{recepcao}*")
        else:
            lines.append("⚠️ _Sem dados de agenda_")
    else:
        lines.append("⚠️ _Dados indisponíveis_")

    # ── Inadimplência da unidade ───────────────────────────────
    inadim = data.get("inadimplencia")
    if inadim:
        roy = inadim.get("royalties", [])
        fundo = inadim.get("fundo_publicidade", [])

        # Filtra só desta unidade (por nome, já que não temos unidade_id na query)
        roy_unit = [r for r in roy if _matches_unit(r, unidade_id, unidade_nome)]
        fundo_unit = [r for r in fundo if _matches_unit(r, unidade_id, unidade_nome)]

        if roy_unit or fundo_unit:
            lines.append(f"\n{_sep()}")
            lines.append("💳 *INADIMPLÊNCIA*")
            for r in roy_unit:
                lines.append(
                    f"🔴 Royalties: {_fmt_brl(r['valor'])} — "
                    f"vencido há *{r['dias_atraso']}* dias"
                )
            for r in fundo_unit:
                lines.append(
                    f"🔴 Fundo Publicidade: {_fmt_brl(r['valor'])} — "
                    f"vencido há *{r['dias_atraso']}* dias"
                )

    # ── Footer ─────────────────────────────────────────────────
    lines.append(f"\n{_sep()}")
    lines.append("_Barbearia VIP — Briefing automático_")

    return "\n".join(lines)


def _get_ranking(unidades: list[dict], unidade_id: int) -> Optional[int]:
    """Retorna posição no ranking de faturamento (1 = melhor)."""
    sorted_units = sorted(
        unidades,
        key=lambda x: float(x.get("faturamento") or 0),
        reverse=True,
    )
    for i, u in enumerate(sorted_units, 1):
        if u.get("unidade_id") == unidade_id:
            return i
    return None


def _matches_unit(row: dict, unidade_id: int, unidade_nome: str) -> bool:
    """Verifica se uma row pertence à unidade (por ID ou nome)."""
    if row.get("unidade_id") == unidade_id:
        return True
    if unidade_nome and row.get("unidade_nome", "") == unidade_nome:
        return True
    return False
