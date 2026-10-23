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


# ── Persistência (SQLite, data/agendamentos.db) ──────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS agendamentos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  texto TEXT NOT NULL,
  destinos_json TEXT NOT NULL,
  primeiro_envio_iso TEXT NOT NULL,
  recorrencia_json TEXT NOT NULL,
  fim_iso TEXT,
  proximo_envio_iso TEXT,
  estado TEXT NOT NULL DEFAULT 'ativo',
  falhas_consecutivas INTEGER NOT NULL DEFAULT 0,
  reservado_em_iso TEXT,
  criado_em TEXT NOT NULL,
  atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS envios(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agendamento_id INTEGER NOT NULL,
  ocorrencia_iso TEXT NOT NULL,
  disparado_em TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  destino_nome TEXT,
  status TEXT NOT NULL,
  erro TEXT,
  UNIQUE(agendamento_id, ocorrencia_iso, chat_id)
);
CREATE INDEX IF NOT EXISTS ix_ag_estado_prox ON agendamentos(estado, proximo_envio_iso);
"""


def db_path() -> str:
    return os.path.join(config.DATA_DIR, "agendamentos.db")


def conectar(path: Optional[str] = None) -> sqlite3.Connection:
    """isolation_level=None: autocommit; transação explícita só em `reservar_vencidos`."""
    p = path or db_path()
    con = sqlite3.connect(p, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    if p != ":memory:":
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def criar_schema(con) -> None:
    con.executescript(SCHEMA)


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def _dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s).astimezone(TZ) if s else None


def _row(r) -> dict:
    d = dict(r)
    d["destinos"] = json.loads(d.pop("destinos_json"))
    d["recorrencia"] = json.loads(d.pop("recorrencia_json"))
    d["primeiro_envio"] = _dt(d.pop("primeiro_envio_iso"))
    d["fim"] = _dt(d.pop("fim_iso"))
    d["proximo_envio"] = _dt(d.pop("proximo_envio_iso"))
    return d


def criar(con, texto, destinos, primeiro, rec, fim) -> int:
    prox = proxima_ocorrencia(None, primeiro, rec, fim)
    n = _iso(config.agora_local())
    cur = con.execute(
        "INSERT INTO agendamentos(texto,destinos_json,primeiro_envio_iso,recorrencia_json,fim_iso,"
        "proximo_envio_iso,estado,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?)",
        (texto, json.dumps(destinos), _iso(primeiro), json.dumps(rec), _iso(fim), _iso(prox),
         "ativo" if prox else "concluido", n, n))
    return cur.lastrowid


def atualizar(con, aid, texto, destinos, primeiro, rec, fim) -> None:
    prox = proxima_ocorrencia(None, primeiro, rec, fim)
    con.execute(
        "UPDATE agendamentos SET texto=?,destinos_json=?,primeiro_envio_iso=?,recorrencia_json=?,fim_iso=?,"
        "proximo_envio_iso=?,estado=?,falhas_consecutivas=0,atualizado_em=? WHERE id=?",
        (texto, json.dumps(destinos), _iso(primeiro), json.dumps(rec), _iso(fim), _iso(prox),
         "ativo" if prox else "concluido", _iso(config.agora_local()), aid))


def obter(con, aid) -> Optional[dict]:
    r = con.execute("SELECT * FROM agendamentos WHERE id=?", (aid,)).fetchone()
    return _row(r) if r else None


def listar(con, estados=("ativo", "pausado", "enviando")) -> list[dict]:
    q = ",".join("?" * len(estados))
    return [_row(r) for r in con.execute(
        f"SELECT * FROM agendamentos WHERE estado IN ({q}) ORDER BY proximo_envio_iso", estados)]


def mudar_estado(con, aid, estado) -> None:
    assert estado in ESTADOS
    # Retomar zera o contador: senão um agendamento pausado por 3 falhas pausa de novo na 1ª falha
    extra = ", falhas_consecutivas=0" if estado == "ativo" else ""
    con.execute(f"UPDATE agendamentos SET estado=?{extra}, atualizado_em=? WHERE id=?",
                (estado, _iso(config.agora_local()), aid))


def reservar_vencidos(con, agora: datetime) -> list[dict]:
    """Marca como 'enviando' (atomicamente) e retorna os agendamentos vencidos."""
    con.execute("BEGIN IMMEDIATE")
    try:
        rows = con.execute(
            "SELECT * FROM agendamentos WHERE estado='ativo' AND proximo_envio_iso<=?", (_iso(agora),)).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            q = ",".join("?" * len(ids))
            con.execute(f"UPDATE agendamentos SET estado='enviando', reservado_em_iso=? WHERE id IN ({q})",
                        (_iso(agora), *ids))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return [_row(r) for r in rows]


def recuperar_presos(con, agora: datetime, minutos: int = 10) -> int:
    """Linhas em 'enviando' há mais de `minutos` (restart no meio do envio) voltam a 'ativo'."""
    limite = _iso(agora - timedelta(minutes=minutos))
    return con.execute(
        "UPDATE agendamentos SET estado='ativo' WHERE estado='enviando' "
        "AND (reservado_em_iso IS NULL OR reservado_em_iso<=?)", (limite,)).rowcount


def concluir_ciclo(con, aid, proximo: Optional[datetime], sucesso: bool) -> None:
    a = obter(con, aid)
    if sucesso:
        falhas, estado = 0, ("ativo" if proximo else "concluido")
    else:
        falhas = a["falhas_consecutivas"] + 1
        estado = "pausado" if falhas >= 3 else "ativo"
        proximo = a["proximo_envio"]            # não avança
    if not sucesso and estado == "pausado":
        registrar_envio(con, aid, a["proximo_envio"], "-", "sistema", "pausado",
                        "pausado automaticamente apos 3 falhas consecutivas")
    # Só atualiza se ainda está 'enviando': um cancelar/pausar clicado durante o envio prevalece
    con.execute(
        "UPDATE agendamentos SET estado=?, proximo_envio_iso=?, falhas_consecutivas=?, reservado_em_iso=NULL, "
        "atualizado_em=? WHERE id=? AND estado='enviando'",
        (estado, _iso(proximo), falhas, _iso(config.agora_local()), aid))


def registrar_envio(con, aid, ocorrencia: datetime, chat_id, nome, status, erro=None) -> None:
    con.execute(
        "INSERT OR REPLACE INTO envios(agendamento_id,ocorrencia_iso,disparado_em,chat_id,destino_nome,status,erro)"
        " VALUES(?,?,?,?,?,?,?)",
        (aid, _iso(ocorrencia), _iso(config.agora_local()), chat_id, nome, status, erro))


def ja_enviados(con, aid, ocorrencia: datetime) -> set:
    return {r[0] for r in con.execute(
        "SELECT chat_id FROM envios WHERE agendamento_id=? AND ocorrencia_iso=? AND status='enviado'",
        (aid, _iso(ocorrencia)))}


def historico(con, limite=200) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT e.*, substr(a.texto,1,60) AS texto FROM envios e JOIN agendamentos a ON a.id=e.agendamento_id "
        "ORDER BY e.id DESC LIMIT ?", (limite,))]


def resolver_destinos(destinos: dict) -> list:
    """[(chat_id, nome)] no momento do envio, com a mesma regra do briefing."""
    out, vistos = [], set()
    grupos = config.UNIT_GROUPS or {}
    ids = list(grupos.keys()) if destinos.get("todas") else [str(u) for u in destinos.get("unidades", [])]
    for uid in ids:
        info = grupos.get(uid)
        if not info:
            continue
        chats = ([info["chat_id"]] if info.get("chat_id") else []) + [c for c in (info.get("chat_ids") or []) if c]
        for c in chats:
            if c not in vistos:
                vistos.add(c)
                out.append((c, info.get("nome", f"Unidade #{uid}")))
    if destinos.get("franqueadora"):
        for c in config.WAHA_RECIPIENTS:
            if c not in vistos:
                vistos.add(c)
                out.append((c, "Franqueadora"))
    return out
