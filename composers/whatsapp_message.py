"""Formata o briefing diário como mensagem de texto para WhatsApp."""

from datetime import date
from typing import Any


def _fmt_brl(value) -> str:
    """Formata número como R$ com separador de milhar."""
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
    """Retorna nome curto da unidade: 'Cidade - Bairro' ou fallback no nome completo."""
    cidade = row.get("cidade", "")
    nome = row.get("unidade_nome", "")
    # Se tem cidade, extrai o bairro do nome (último segmento após ' - ')
    if cidade and " - " in nome:
        parts = nome.split(" - ")
        bairro = parts[-1].strip()
        return f"{cidade} - {bairro}"
    return nome


def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


def _section(title: str) -> str:
    return f"\n{_sep()}\n{title}\n"


def compose(data: dict[str, Any]) -> str:
    """
    Recebe o dict consolidado de todos os collectors e retorna
    a string formatada para WhatsApp.
    """
    hoje = date.today().strftime("%d/%m/%Y")
    lines = []

    # ── Cabeçalho ────────────────────────────────────────────────────────────
    lines.append(f"🟢 *DAILY BRIEFING VIP* 📊 {hoje}")
    lines.append(_sep())

    # ── Faturamento ───────────────────────────────────────────────────────────
    fat = data.get("faturamento")
    lines.append("💰 *FATURAMENTO ONTEM*")
    if fat:
        rede_str = _fmt_brl(fat["total_rede"])
        lines.append(f"Rede: *{rede_str}* | Ticket médio: {_fmt_brl(fat['ticket_medio_rede'])}")

        # Meta diária da rede (se disponível)
        if fat.get("meta_diaria_rede") and fat.get("pct_meta_rede"):
            lines.append(
                f"Meta dia: {_fmt_brl(fat['meta_diaria_rede'])} → *{_fmt_pct(fat['pct_meta_rede'])}*"
            )

        if fat.get("top5"):
            lines.append("🏆 *Top 5:*")
            for u in fat["top5"]:
                meta_tag = f" ({_fmt_pct(u['pct_meta'])} da meta)" if u.get("pct_meta") else ""
                lines.append(f"  • {_short_name(u)} — {_fmt_brl(u['faturamento'])}{meta_tag}")

        if fat.get("bottom5"):
            lines.append("⚠️ *Atenção:*")
            for u in fat["bottom5"]:
                meta_tag = f" ({_fmt_pct(u['pct_meta'])} da meta)" if u.get("pct_meta") else ""
                lines.append(f"  • {_short_name(u)} — {_fmt_brl(u['faturamento'])}{meta_tag}")
    else:
        lines.append("⚠️ _Dados de faturamento indisponíveis_")

    # ── Meta mensal ───────────────────────────────────────────────────────────
    meta = data.get("meta_mensal")
    lines.append(_section("📊 *META MENSAL*"))
    if meta:
        acum = _fmt_brl(meta["acumulado_rede"])
        meta_total = _fmt_brl(meta["meta_rede"])
        pct = _fmt_pct(meta["pct_rede"])
        pct_corrido = _fmt_pct(meta.get("pct_mes_corrido"))
        lines.append(f"Acumulado: *{acum}* / {meta_total} → *{pct}*")
        lines.append(f"📅 Mês corrido: {pct_corrido} | _Meta baseada na média 3 meses_")
    else:
        lines.append("⚠️ _Dados de meta indisponíveis_")

    # ── Agenda ────────────────────────────────────────────────────────────────
    agenda = data.get("agenda")
    lines.append(_section("📅 *AGENDA ONTEM*"))
    if agenda:
        lines.append(
            f"Ocupação rede: *{_fmt_pct(agenda['ocupacao_rede_pct'])}* "
            f"({agenda['total_realizados']}/{agenda['total_agendamentos']})"
        )
        lines.append(
            f"🚫 No-shows: *{agenda['total_noshows']}* | "
            f"Cancelamentos: *{agenda['total_cancelados']}*"
        )
        lines.append(
            f"📱 App: *{agenda['total_app']}* | "
            f"Recepção: *{agenda['total_recepcao']}*"
        )
    else:
        lines.append("⚠️ _Dados de agenda indisponíveis_")

    # ── SatisfyCAM ────────────────────────────────────────────────────────────
    scam = data.get("satisfycam", {}).get("relatorio")
    lines.append(_section("😊 *SATISFYCAM*"))
    if scam:
        lines.append(
            f"✅ Satisfeitos: *{_fmt_pct(scam['pct_satisfied'])}* | "
            f"😐 Neutros: *{scam['neutral']}* | "
            f"😟 Negativos: *{_fmt_pct(scam['pct_unsatisfied'])}*"
        )
        lines.append(f"Total detectado: {scam['total_clientes']} clientes")
        if scam.get("alertas"):
            for alerta in scam["alertas"][:3]:
                lines.append(f"  ⚠️ Loja {alerta['storeId']}: {alerta['total_negativas']} neg.")
    else:
        lines.append("⚠️ _SatisfyCAM indisponível_")

    # ── Inadimplência ─────────────────────────────────────────────────────────
    inadim = data.get("inadimplencia")
    lines.append(_section("💳 *INADIMPLÊNCIA*"))
    if inadim:
        roy = inadim.get("royalties", [])
        fundo = inadim.get("fundo_publicidade", [])
        if roy:
            lines.append(f"🔴 Royalties: *{len(roy)} fatura(s)* em atraso")
            for r in roy[:5]:
                lines.append(
                    f"  • {_short_name(r)} — {_fmt_brl(r['valor'])} "
                    f"({r['dias_atraso']}d)"
                )
        else:
            lines.append("✅ Royalties: em dia")

        if fundo:
            lines.append(f"🔴 Fundo Publicidade: *{len(fundo)} fatura(s)* em atraso")
            for r in fundo[:5]:
                lines.append(
                    f"  • {_short_name(r)} — {_fmt_brl(r['valor'])} "
                    f"({r['dias_atraso']}d)"
                )
        else:
            lines.append("✅ Fundo Publicidade: em dia")
    else:
        lines.append("⚠️ _Dados de inadimplência indisponíveis_")

    # ── Perfex CRM / Leads ────────────────────────────────────────────────────
    perfex = data.get("perfex", {}).get("leads")
    lines.append(_section("🎯 *CRM / LEADS FRANQUEADOS*"))
    if perfex:
        lines.append(
            f"Novos leads 24h: *{perfex['novos_24h']}* | "
            f"Total pipeline: *{perfex['total_leads']}*"
        )
        if perfex.get("funil"):
            funil_str = " | ".join(f"{k}: {v}" for k, v in perfex["funil"].items())
            lines.append(f"Funil: {funil_str}")
    else:
        lines.append("⚠️ _Perfex CRM indisponível_")

    # ── Google Reviews ────────────────────────────────────────────────────────
    reviews = data.get("google", {}).get("reviews")
    lines.append(_section("⭐ *GOOGLE REVIEWS*"))
    if reviews:
        lines.append(
            f"Novas 24h: *{reviews['total']}* "
            f"(✅ {len(reviews['positivas'])} positivas | "
            f"❌ {len(reviews['negativas'])} negativas)"
        )
        for r in reviews["negativas"][:3]:
            autor = r.get("reviewer", {}).get("displayName", "Anônimo")
            local = r.get("_location_title", "")
            comentario = (r.get("comment") or "")[:80]
            lines.append(f"  ⚠️ {autor} ({local}): _{comentario}_")
    else:
        lines.append("⚠️ _Google Reviews indisponível_")

    # ── Alertas operacionais ──────────────────────────────────────────────────
    ausentes = data.get("barbeiros_ausentes", [])
    aniversarios = data.get("aniversarios", [])

    alertas_lines = []
    if ausentes:
        alertas_lines.append(f"👤 Sem caixa hoje: *{len(ausentes)} barbeiro(s)*")
        for a in ausentes[:5]:
            alertas_lines.append(f"  • {a['barbeiro_nome']} ({_short_name(a)})")

    if alertas_lines:
        lines.append(_section("🚨 *ALERTAS OPERACIONAIS*"))
        lines.extend(alertas_lines)

    # ── Aniversários ──────────────────────────────────────────────────────────
    if aniversarios:
        lines.append(_section("🎉 *ANIVERSÁRIOS / MARCOS*"))
        for a in aniversarios:
            if a["tipo"] == "socio":
                lines.append(f"🎂 {a['nome']} ({a['unidade_nome']}) — {a['anos']} anos")
            else:
                anos = a["anos"]
                lines.append(
                    f"🏪 {a['unidade_nome']} completa *{anos} ano{'s' if anos != 1 else ''}* hoje!"
                )

    # ── Link para dashboard completo ──────────────────────────────────────────
    dashboard_url = data.get("dashboard_url", "")
    lines.append(f"\n{_sep()}")
    if dashboard_url:
        lines.append(f"📋 *Dashboard completo:* {dashboard_url}")
    lines.append("_Barbearia VIP — Briefing automático_")

    return "\n".join(lines)
