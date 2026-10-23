import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

# Antes de qualquer import de admin.app: sem admin.log nos testes e cookie sem Secure
# (o test client fala HTTP puro).
os.environ["ADMIN_NO_FILE_LOG"] = "1"
os.environ["ADMIN_INSECURE_COOKIE"] = "1"

# Relógio congelado por padrão: 23/10/2026 13:00 UTC = 10:00 BRT. Testes que precisam
# de outro instante sobrescrevem `config._agora` (ou `agora_local`/`hoje_local`).
AGORA_TESTES = datetime(2026, 10, 23, 13, 0, tzinfo=ZoneInfo("UTC"))


@pytest.fixture(autouse=True)
def _relogio_congelado(monkeypatch):
    import config
    monkeypatch.setattr(config, "_agora", lambda: AGORA_TESTES)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Nenhum teste lê o .env real nem escreve em output/ ou data/ do projeto."""
    monkeypatch.setenv("ADMIN_SECRET_KEY", "test-secret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_TEST_CHAT_ID", raising=False)
    import config
    # config já pode ter sido importado (e lido um .env real): congela os valores de teste
    # (TIMEZONE é lido do ambiente na importação, por isso o setattr e não setenv)
    monkeypatch.setattr(config, "TIMEZONE", "America/Sao_Paulo")
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "ADMIN_TEST_CHAT_ID", "", raising=False)
    monkeypatch.setattr(config, "ADMIN_SECRET_KEY", "test-secret", raising=False)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs(config.DATA_DIR, exist_ok=True)
    yield
