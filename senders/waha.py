"""Cliente HTTP para envio de mensagens via WAHA (WhatsApp HTTP API)."""

import logging
import time
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_RETRY_WAIT = 3  # segundos entre tentativas


def send_text(chat_id: str, text: str, session: Optional[str] = None) -> bool:
    """
    Envia uma mensagem de texto para um chat_id via WAHA.

    Args:
        chat_id: Número no formato '5547999999999@c.us' ou ID de grupo
        text: Texto da mensagem (suporta formatação WhatsApp: *bold*, _italic_)
        session: Nome da sessão WAHA (padrão: config.WAHA_SESSION)

    Returns:
        True se enviado com sucesso, False caso contrário.
    """
    session = session or config.WAHA_SESSION
    url = f"{config.WAHA_URL}/api/sendText"
    headers = {}
    if config.WAHA_API_KEY:
        headers["X-Api-Key"] = config.WAHA_API_KEY

    payload = {
        "session": session,
        "chatId": chat_id,
        "text": text,
    }

    for attempt in range(1, 3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
            resp.raise_for_status()
            logger.info("Mensagem enviada para %s (tentativa %d)", chat_id, attempt)
            return True
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "Falha ao enviar para %s (tentativa %d/%d): %s",
                chat_id, attempt, 2, exc,
            )
            if attempt < 2:
                time.sleep(_RETRY_WAIT)

    return False


def broadcast(text: str, recipients: Optional[list[str]] = None) -> dict[str, bool]:
    """
    Envia a mesma mensagem para todos os destinatários configurados.

    Args:
        text: Texto a enviar
        recipients: Lista de chat_ids. Se None, usa config.WAHA_RECIPIENTS.

    Returns:
        Dict {chat_id: sucesso}
    """
    targets = recipients or config.WAHA_RECIPIENTS
    results = {}
    for chat_id in targets:
        results[chat_id] = send_text(chat_id, text)
        if len(targets) > 1:
            time.sleep(1)  # pequeno intervalo para não sobrecarregar o WAHA
    return results
