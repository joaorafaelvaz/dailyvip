import os
import pytest


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Nenhum teste lê o .env real nem escreve em output/ ou data/ do projeto."""
    monkeypatch.setenv("TIMEZONE", "America/Sao_Paulo")
    monkeypatch.setenv("ADMIN_SECRET_KEY", "test-secret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_TEST_CHAT_ID", raising=False)
    import config
    # config já pode ter sido importado (e lido um .env real): congela os valores de teste
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "ADMIN_TEST_CHAT_ID", "", raising=False)
    monkeypatch.setattr(config, "ADMIN_SECRET_KEY", "test-secret", raising=False)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs(config.DATA_DIR, exist_ok=True)
    yield
