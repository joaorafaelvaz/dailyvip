"""Formata a lista de clientes aniversariantes do dia para o grupo do franqueado."""

import re
from datetime import date, datetime
from typing import Any, Optional

import config


def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


def _fmt_telefone(valor: Any) -> str:
    """Telefone legível: mantém a máscara do ERP; só dígitos viram (XX) XXXXX-XXXX."""
    if not valor:
        return "sem telefone"
    texto = str(valor).strip()
    if not texto:
        return "sem telefone"
    digitos = re.sub(r"\D", "", texto)
    if texto == digitos:
        if digitos.startswith("55") and len(digitos) in (12, 13):
            digitos = digitos[2:]
        if len(digitos) == 11:
            return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
        if len(digitos) == 10:
            return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return texto


def _fmt_ultima_visita(valor: Any) -> str:
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%d/%m")
    return ""


def compose_for_unit(rows: list[dict], unidade_nome: str, hoje: Optional[date] = None) -> str:
    """
    Mensagem para UMA unidade com os clientes que fazem aniversário hoje.

    `rows` já vem filtrado para a unidade (saída de get_aniversariantes_clientes).
    Retorna string vazia quando não há aniversariantes: a unidade não recebe nada.
    """
    if not rows:
        return ""
    hoje = hoje or config.hoje_local()
    total = len(rows)
    meses = config.ANIVERSARIOS_MESES

    lines = [
        f"🎂 *ANIVERSARIANTES DE HOJE* — {hoje.strftime('%d/%m/%Y')}",
        f"📍 *{unidade_nome}*",
        _sep(),
        (f"*{total}* cliente{'s' if total != 1 else ''} que "
         f"{'visitaram' if total != 1 else 'visitou'} a unidade nos últimos {meses} meses:"),
        "",
    ]
    for r in rows:
        nome = (r.get("cliente_nome") or "Cliente").strip()
        anos = r.get("anos")
        idade = f" — {int(anos)} anos" if anos not in (None, "") and int(anos) > 0 else ""
        visita = _fmt_ultima_visita(r.get("ultima_visita"))
        visita_txt = f" | última visita {visita}" if visita else ""
        lines.append(f"  • {nome}{idade} | 📱 {_fmt_telefone(r.get('cliente_telefone'))}{visita_txt}")
    lines.append(_sep())
    lines.append("💡 Uma mensagem de parabéns hoje é um bom motivo para o cliente voltar.")
    return "\n".join(lines)
