"""Agendamentos de mensagens: regra de recorrência (pura) e persistência SQLite."""
import calendar
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import config

TZ = ZoneInfo(config.TIMEZONE)
ESTADOS = ("ativo", "pausado", "enviando", "concluido", "cancelado")


def _no_horario(d: datetime, ref: datetime) -> datetime:
    return d.replace(hour=ref.hour, minute=ref.minute, second=0, microsecond=0)


def proxima_ocorrencia(apos: Optional[datetime], primeiro: datetime, rec: dict,
                       fim: Optional[datetime]) -> Optional[datetime]:
    """Primeira ocorrência depois de `apos` (None = a primeira de todas, podendo ser
    o próprio `primeiro`), nunca antes de `primeiro`, respeitando `fim`.
    O horário é sempre o de `primeiro`."""
    tipo = rec.get("tipo", "nenhuma")
    if tipo == "nenhuma":
        cand = primeiro if (apos is None or primeiro > apos) else None
    else:
        # candidato inicial: o dia de `primeiro` (se apos is None) ou o dia seguinte a `apos`
        if apos is None:
            d = _no_horario(primeiro, primeiro)
        else:
            d = _no_horario(apos, primeiro) + timedelta(days=1)
            if d <= apos:
                d += timedelta(days=1)
        if d < primeiro:                     # `apos` anterior ao primeiro envio
            d = _no_horario(primeiro, primeiro)
        cand = _primeiro_valido(d, primeiro, rec)
    if cand is not None and fim is not None and cand > fim:
        return None
    return cand


def _primeiro_valido(d: datetime, primeiro: datetime, rec: dict) -> datetime:
    """Avança `d` dia a dia (ou mês a mês no mensal) até casar com a regra."""
    tipo = rec["tipo"]
    if tipo == "diaria":
        return d
    if tipo == "semanal":
        dias = sorted({int(x) for x in rec.get("dias", [])})
        if not dias:
            raise ValueError("recorrência semanal sem dias")
        for _ in range(7):
            if d.weekday() in dias:
                return d
            d += timedelta(days=1)
        raise AssertionError("inalcançável")
    if tipo == "mensal":
        alvo = rec.get("dia", 1)
        ano, mes = d.year, d.month
        for _ in range(14):
            ultimo = calendar.monthrange(ano, mes)[1]
            dia = ultimo if alvo == "ultimo" else min(int(alvo), ultimo)
            c = _no_horario(datetime(ano, mes, dia, tzinfo=TZ), primeiro)
            if c >= d:
                return c
            mes += 1
            if mes == 13:
                mes, ano = 1, ano + 1
        raise ValueError("recorrência mensal inválida")
    raise ValueError(f"tipo de recorrência desconhecido: {tipo}")
