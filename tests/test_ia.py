import pytest


class _Blk:
    type = "text"
    def __init__(self, t): self.text = t


class _Resp:
    def __init__(self, text, stop="end_turn"):
        self.content = [_Blk(text)]; self.stop_reason = stop


def _fake_client(monkeypatch, resposta, capt=None):
    from admin import ia
    class Msgs:
        def create(self, **kw):
            if capt is not None: capt.update(kw)
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


def test_recusa_vira_erro_amigavel(monkeypatch):
    import config
    from admin import ia
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    _fake_client(monkeypatch, _Resp("", stop="refusal"))
    with pytest.raises(ia.IAErro, match="não conseguiu"):
        ia.gerar_mensagem("x", "Amigável")
