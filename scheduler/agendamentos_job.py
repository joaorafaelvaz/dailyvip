"""Job de 1 minuto do daily-briefing: envia as mensagens agendadas vencidas (spec §5, passos 0–5)."""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import config
from admin import agendamentos as ag
from senders import waha

logger = logging.getLogger("agendamentos")
ATRASO_MAXIMO = timedelta(hours=2)
INTERVALO_ENVIO_S = 1.5


def conectar():
    con = ag.conectar()
    ag.criar_schema(con)
    return con


def processar_agendamentos(agora: Optional[datetime] = None, con=None) -> int:
    """`con` injetável (testes); quando None, abre e fecha a própria conexão."""
    agora = agora or config.agora_local()
    propria = con is None
    if propria:
        con = conectar()
    try:
        # 0. Recuperação: 'enviando' há >10 min (restart no meio do envio) volta a 'ativo'
        presos = ag.recuperar_presos(con, agora)
        if presos:
            logger.warning("%d agendamento(s) presos em 'enviando' recuperados", presos)
        # 1. Reserva atômica dos vencidos (marca 'enviando')
        vencidos = ag.reservar_vencidos(con, agora)
        for a in vencidos:
            _processar_um(con, a, agora)
        if vencidos:
            logger.info("Ciclo: %d agendamento(s) processado(s)", len(vencidos))
        return len(vencidos)
    finally:
        if propria:
            con.close()


def _processar_um(con, a: dict, agora: datetime) -> None:
    aid, ocorrencia = a["id"], a["proximo_envio"]
    destinos = ag.resolver_destinos(a["destinos"])
    try:
        # 2. Atraso > 2h: registra 'perdido' por destino e não envia
        if agora - ocorrencia > ATRASO_MAXIMO:
            for chat, nome in destinos:
                ag.registrar_envio(con, aid, ocorrencia, chat, nome, "perdido", f"atraso > {ATRASO_MAXIMO}")
            logger.warning("Agendamento %s: ocorrência %s perdida (atraso > 2h)", aid, ocorrencia)
            prox = ag.proxima_ocorrencia(ocorrencia, a["primeiro_envio"], a["recorrencia"], a["fim"])
            ag.concluir_ciclo(con, aid, prox, sucesso=True)
            return

        # 3. Envia a quem ainda não recebeu esta ocorrência (retentativa não duplica)
        feitos = ag.ja_enviados(con, aid, ocorrencia)
        algum_ok = bool(feitos)
        for chat, nome in destinos:
            if chat in feitos:
                continue
            ok = waha.send_text(chat, a["texto"])
            ag.registrar_envio(con, aid, ocorrencia, chat, nome, "enviado" if ok else "falhou",
                               None if ok else "WAHA retornou falha")
            algum_ok = algum_ok or ok
            time.sleep(INTERVALO_ENVIO_S)

        if not destinos:
            logger.warning("Agendamento %s sem destinos válidos", aid)
        # 4./5. Ciclo ok (>=1 enviado) avança; todos falharam -> falha do ciclo, sem avançar
        sucesso = algum_ok or not destinos
        prox = ag.proxima_ocorrencia(ocorrencia, a["primeiro_envio"], a["recorrencia"], a["fim"]) if sucesso else None
        ag.concluir_ciclo(con, aid, prox, sucesso=sucesso)
        if not sucesso:
            logger.error("Agendamento %s: todos os destinos falharam", aid)
    except Exception as exc:
        logger.error("Agendamento %s: exceção no envio: %s", aid, exc, exc_info=True)
        ag.concluir_ciclo(con, aid, None, sucesso=False)
