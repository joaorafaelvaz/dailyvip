import pytest


class _Blk:
    type = "text"
    def __init__(self, t): self.text = t


class _Resp:
    def __init__(self, text, stop="end_turn"):
        self.content = [_Blk(text)]; self.stop_reason = stop


def _fake_client(monkeypatch, resposta, capt=None):
    """`resposta` pode ser uma exceção: aí `create()` a levanta."""
    from admin import ia
    class Msgs:
        def create(self, **kw):
            if capt is not None: capt.update(kw)
            if isinstance(resposta, BaseException): raise resposta
            return resposta
    class Client:
        beta = type("B", (), {"messages": Msgs()})()
        def with_options(self, **kw): return self
    monkeypatch.setattr(ia, "_client", lambda: Client())


def test_sem_chave_levanta(monkeypatch):
    import config
    from admin import ia
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    with pytest.raises(ia.IAIndisponivel):
        ia.gerar_mensagem("teste", "Amigável")


def test_gera_texto(monkeypatch):
    import config
    from admin import ia
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    capt = {}
    _fake_client(monkeypatch, _Resp("  Olá *time*! Lembrete.  "), capt)
    assert ia.gerar_mensagem("lembrete de caixa", "Formal") == "Olá *time*! Lembrete."
    assert capt["model"] == "claude-opus-5-5" and capt["output_config"] == {"effort": "low"}
    assert capt["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in capt["betas"]
    assert "Assunto: lembrete de caixa" in capt["messages"][0]["content"] and "Tom: Formal" in capt["messages"][0]["content"]


class Status503(object):
    """Fábrica de um APIStatusError 503 sem precisar de um httpx.Response real."""
    def __new__(cls):
        import anthropic
        class _Err(anthropic.APIStatusError):
            def __init__(self):
                self.message, self.status_code, self.body, self.request_id = "boom", 503, None, None
        return _Err()


def test_erro_5xx_vira_indisponivel_encadeado(monkeypatch):
    import config
    from admin import ia
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    _fake_client(monkeypatch, Status503())
    with pytest.raises(ia.IAErro, match="indisponível") as info:
        ia.gerar_mensagem("x", "Amigável")
    assert info.value.__cause__ is not None and info.value.__cause__.status_code == 503


def test_recusa_vira_erro_amigavel(monkeypatch):
    import config
    from admin import ia
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    _fake_client(monkeypatch, _Resp("", stop="refusal"))
    with pytest.raises(ia.IAErro, match="não conseguiu"):
        ia.gerar_mensagem("x", "Amigável")
