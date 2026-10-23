import os
from datetime import date
import pytest


def _touch(nome):
    import config
    open(os.path.join(config.OUTPUT_DIR, nome), "w").close()


def test_parse_nomes():
    from admin.relatorios import parse_nome
    assert parse_nome("briefing-21-10-2026.html") == ("diario", date(2026, 10, 20))     # dia dos dados = arquivo - 1
    assert parse_nome("briefing-semanal-27-09-2026.html") == ("semanal", date(2026, 9, 27))
    assert parse_nome("briefing-mensal-09-2026.html") == ("mensal", date(2026, 9, 1))
    assert parse_nome("index.html") is None
    assert parse_nome("briefing-31-02-2026.html") is None


def test_nome_para():
    from admin.relatorios import nome_para
    assert nome_para("diario", date(2026, 10, 20)) == "briefing-21-10-2026.html"
    assert nome_para("semanal", date(2026, 9, 24)) == "briefing-semanal-27-09-2026.html"  # quarta -> domingo
    assert nome_para("mensal", date(2026, 9, 15)) == "briefing-mensal-09-2026.html"


def test_listar_ordena_mais_recente_primeiro():
    from admin.relatorios import listar
    _touch("briefing-21-10-2026.html"); _touch("briefing-22-10-2026.html"); _touch("briefing-semanal-27-09-2026.html"); _touch("lixo.txt")
    r = listar()
    assert [x["data"] for x in r["diario"]] == [date(2026, 10, 21), date(2026, 10, 20)]
    assert r["semanal"][0]["arquivo"] == "briefing-semanal-27-09-2026.html"
    assert r["mensal"] == []


def test_validar_data(monkeypatch):
    import config
    from admin.relatorios import validar_data, DataInvalida
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    validar_data("diario", date(2026, 10, 22))
    with pytest.raises(DataInvalida):
        validar_data("diario", date(2026, 10, 23))   # dados de hoje ainda não fecharam
    with pytest.raises(DataInvalida):
        validar_data("diario", date(2023, 12, 31))
