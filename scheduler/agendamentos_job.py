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

        # Sem destinos (unidades removidas do unit_groups.json etc.): não vai se resolver no
        # próximo minuto — pausa já, com o motivo no histórico, para o operador corrigir na tela.
        # (Uma única linha de sistema: 'falhou' e 'pausado' colidiriam no UNIQUE com chat_id "-".)
        if not destinos:
            logger.error("Agendamento %s sem destinos válidos — pausado", aid)
            ag.concluir_ciclo(con, aid, None, sucesso=False, pausar=True, motivo="sem destinos válidos")
            return

        # 3. Envia a quem ainda não recebeu esta ocorrência (retentativa não duplica)
        feitos = ag.ja_enviados(con, aid, ocorrencia)
        algum_ok = bool(feitos)
        enviados_agora = 0
        for chat, nome in destinos:
            if chat in feitos:
                continue
            if enviados_agora:
                time.sleep(INTERVALO_ENVIO_S)          # só ENTRE envios
            ok = waha.send_text(chat, a["texto"])
            enviados_agora += 1
            ag.registrar_envio(con, aid, ocorrencia, chat, nome, "enviado" if ok else "falhou",
                               None if ok else "WAHA retornou falha")
            algum_ok = algum_ok or ok

        # 4./5. Ciclo ok (>=1 enviado) avança; todos falharam -> falha do ciclo, sem avançar
        prox = ag.proxima_ocorrencia(ocorrencia, a["primeiro_envio"], a["recorrencia"], a["fim"]) if algum_ok else None
        ag.concluir_ciclo(con, aid, prox, sucesso=algum_ok)
        if not algum_ok:
            logger.error("Agendamento %s: todos os destinos falharam", aid)
    except Exception as exc:
        logger.error("Agendamento %s: exceção no envio: %s", aid, exc, exc_info=True)
        try:
            ag.concluir_ciclo(con, aid, None, sucesso=False)
        except Exception as exc2:
            # Não deixa uma linha ruim derrubar o ciclo; `recuperar_presos` a solta em 10 min
            logger.error("Agendamento %s: falha ao fechar o ciclo: %s", aid, exc2, exc_info=True)
