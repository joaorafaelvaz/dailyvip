"""Formata o relatório diário de Meta Ads de uma conta para envio via WhatsApp."""

from datetime import date
from typing import Any, Optional


def _fmt_money(value, moeda: str = "BRL") -> str:
    if value is None:
        return "--"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "--"
    num = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {num}" if moeda == "BRL" else f"{moeda} {num}"


def _fmt_int(value) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def _fmt_pct(value) -> str:
    if value is None:
        return "--"
    return f"{float(value):.2f}%"


def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


def _bloco_metricas(m: dict[str, Any], moeda: str) -> list[str]:
    lines = [
        f"💸 Investimento: *{_fmt_money(m.get('gasto'), moeda)}*",
        f"👁️ Alcance: *{_fmt_int(m.get('alcance'))}* | Impressões: {_fmt_int(m.get('impressoes'))}",
        f"🖱️ Cliques: *{_fmt_int(m.get('cliques'))}* "
        f"(link: {_fmt_int(m.get('cliques_link'))}) | CTR: {_fmt_pct(m.get('ctr'))}",
        f"CPC: {_fmt_money(m.get('cpc'), moeda)} | CPM: {_fmt_money(m.get('cpm'), moeda)}",
    ]
    resultados = m.get("resultados") or []
    if resultados:
        lines.append("🎯 *Resultados:*")
        for r in resultados:
            custo = r.get("custo_unitario")
            custo_txt = f" — {_fmt_money(custo, moeda)}/un." if custo else ""
            lines.append(f"  • {r['label']}: *{_fmt_int(r['quantidade'])}*{custo_txt}")
    elif float(m.get("gasto") or 0) > 0:
        lines.append("🎯 Resultados: _nenhuma conversão registrada_")
    return lines


def compose(dados: dict[str, Any], nome_exibicao: Optional[str] = None) -> str:
    """
    Gera a mensagem WhatsApp do relatório de Meta Ads de uma conta.

    Args:
        dados: retorno de collectors.meta_ads.collect_account (ou {"erro": ..., "dia": ...})
        nome_exibicao: nome da unidade/cliente para o cabeçalho (padrão: nome da conta)
    """
    dia: date = dados.get("dia") or date.today()
    dia_txt = dia.strftime("%d/%m/%Y")
    conta = dados.get("conta") or {}
    titulo = nome_exibicao or conta.get("nome") or conta.get("id") or "Meta Ads"

    lines = [
        f"📣 *META ADS — RELATÓRIO DIÁRIO* — {dia_txt}",
        f"📍 *{titulo}*",
    ]
    if conta.get("nome") and nome_exibicao and conta["nome"] != nome_exibicao:
        lines.append(f"_Conta: {conta['nome']}_")
    lines.append(_sep())

    if dados.get("erro"):
        lines.append("⚠️ _Não foi possível obter os dados do Meta Ads hoje._")
        lines.append(f"_Motivo: {dados['erro'][:160]}_")
        return "\n".join(lines)

    moeda = conta.get("moeda", "BRL")
    ontem = dados.get("ontem") or {}
    mes = dados.get("mes") or {}

    # ── Ontem ────────────────────────────────────────────────────
    lines.append("📅 *ONTEM*")
    if float(ontem.get("gasto") or 0) == 0 and not ontem.get("impressoes"):
        lines.append("_Sem veiculação registrada neste dia._")
    else:
        lines.extend(_bloco_metricas(ontem, moeda))

    # ── Campanhas ────────────────────────────────────────────────
    campanhas = dados.get("campanhas") or []
    if campanhas:
        lines.append(f"\n{_sep()}")
        lines.append("📂 *CAMPANHAS (ontem, por investimento)*")
        for c in campanhas:
            res = c.get("resultados") or []
            res_txt = ""
            if res:
                principal = res[0]
                res_txt = f" | {principal['label']}: {_fmt_int(principal['quantidade'])}"
            lines.append(
                f"  • {c['nome']} — {_fmt_money(c['gasto'], moeda)} | "
                f"cliques: {_fmt_int(c['cliques'])}{res_txt}"
            )

    # ── Mês acumulado ────────────────────────────────────────────
    inicio = mes.get("inicio")
    if inicio:
        periodo = f"{inicio.strftime('%d/%m')} a {dia.strftime('%d/%m')}"
    else:
        periodo = dia.strftime("%m/%Y")
    lines.append(f"\n{_sep()}")
    lines.append(f"📆 *ACUMULADO DO MÊS* ({periodo})")
    lines.extend(_bloco_metricas(mes, moeda))

    return "\n".join(lines)
