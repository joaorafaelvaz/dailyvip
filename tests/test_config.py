# tests/test_config.py
from datetime import date, datetime
from zoneinfo import ZoneInfo


def test_hoje_local_usa_timezone_configurado(monkeypatch):
    import config
    # 23h59 UTC de 23/10 = 20h59 BRT de 23/10 -> mesmo dia
    monkeypatch.setattr(config, "_agora", lambda: datetime(2026, 10, 23, 23, 59, tzinfo=ZoneInfo("UTC")))
    assert config.hoje_local() == date(2026, 10, 23)
    # 02h UTC de 24/10 = 23h BRT de 23/10 -> ainda 23/10 em BRT
    monkeypatch.setattr(config, "_agora", lambda: datetime(2026, 10, 24, 2, 0, tzinfo=ZoneInfo("UTC")))
    assert config.hoje_local() == date(2026, 10, 23)


def test_data_dir_do_projeto_e_criado_na_importacao():
    import config, os
    # O conftest aponta config.DATA_DIR para um tmp; aqui verificamos o data/ real,
    # criado pelo os.makedirs executado na importacao de config.
    assert os.path.isdir(os.path.join(os.path.dirname(config.__file__), "data"))
