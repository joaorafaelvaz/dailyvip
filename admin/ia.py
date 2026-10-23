"""Geração de mensagem com a API da Anthropic (SDK oficial)."""
import logging
import os

import config

logger = logging.getLogger("admin.ia")
MODELO = "claude-opus-5-5"
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "mensagem_sistema.txt")
TONS = ("Amigável", "Formal", "Urgente")


class IAIndisponivel(RuntimeError):
    """Sem chave configurada."""


class IAErro(RuntimeError):
    """Falha ao gerar; a mensagem é segura para mostrar ao usuário."""


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _system_prompt() -> str:
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        return f.read().strip()


def gerar_mensagem(assunto: str, tom: str) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise IAIndisponivel("ANTHROPIC_API_KEY não configurada")
    assunto = (assunto or "").strip()
    if not assunto:
        raise IAErro("Informe o assunto.")
    if tom not in TONS:
        tom = TONS[0]
    import anthropic
    try:
        resp = _client().with_options(timeout=30.0, max_retries=1).beta.messages.create(
            model=MODELO,
            max_tokens=1024,
            output_config={"effort": "low"},
            system=_system_prompt(),
            messages=[{"role": "user", "content": f"Assunto: {assunto}\nTom: {tom}"}],
            # Recusa do classificador de segurança -> a API refaz a chamada noutro modelo
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        raise IAErro("Chave da Anthropic inválida. Confira ANTHROPIC_API_KEY no .env.")
    except anthropic.RateLimitError:
        raise IAErro("Limite de uso da IA atingido. Tente de novo em instantes.")
    except anthropic.APIStatusError as exc:
        logger.error("Anthropic status %s: %s", exc.status_code, exc.message)
        raise IAErro("Serviço de IA indisponível no momento." if exc.status_code >= 500 else f"Erro da IA: {exc.message}")
    except (anthropic.APITimeoutError, anthropic.APIConnectionError):
        raise IAErro("Sem resposta da IA (tempo esgotado). Tente de novo.")
    if resp.stop_reason == "refusal":
        raise IAErro("A IA não conseguiu gerar uma mensagem para esse assunto. Reformule o pedido.")
    texto = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()
    if not texto:
        raise IAErro("A IA retornou vazio. Tente de novo.")
    return texto
