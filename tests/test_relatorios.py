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


def test_validar_data_semanal_e_mensal_em_aberto(monkeypatch):
    import config
    from admin.relatorios import validar_data, DataInvalida
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 25))   # domingo
    with pytest.raises(DataInvalida):
        validar_data("semanal", date(2026, 10, 25))   # a semana termina hoje: ainda não fechou
    validar_data("semanal", date(2026, 10, 18))       # semana anterior ok
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    with pytest.raises(DataInvalida):
        validar_data("mensal", date(2026, 10, 1))     # mês corrente
    validar_data("mensal", date(2026, 9, 1))


def test_gerar_sem_erp_nao_sobrescreve_arquivo(monkeypatch):
    import config, briefing_core
    from admin.relatorios import gerar, ColetaFalhou
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    alvo = os.path.join(config.OUTPUT_DIR, "briefing-21-10-2026.html")
    with open(alvo, "w", encoding="utf-8") as f:
        f.write("ok")
    monkeypatch.setattr(briefing_core, "collect_all_data",
                        lambda hoje=None: {"faturamento": None, "agenda": None, "profissionais": None})
    with pytest.raises(ColetaFalhou):
        gerar("diario", date(2026, 10, 20))
    assert open(alvo, encoding="utf-8").read() == "ok"


def _fakes_periodicos(monkeypatch):
    from collectors import erp_mysql, perfex_crm
    from composers import html_periodic_dashboard
    import config
    chamadas = {}

    def collect_range(ini, fim, tipo="semanal", hoje=None):
        chamadas["collect_range"] = (ini, fim, tipo, hoje)
        return {"faturamento": {"total": 1}}

    def collect_periodo(ini, fim):
        chamadas["collect_periodo"] = (ini, fim)
        return {"leads": None}

    def generate(data, ini, fim, tipo="semanal", hoje=None):
        chamadas["generate"] = (data, ini, fim, tipo, hoje)
        return os.path.join(config.OUTPUT_DIR, f"briefing-{tipo}-fake.html")

    monkeypatch.setattr(erp_mysql, "collect_range", collect_range)
    monkeypatch.setattr(perfex_crm, "collect_periodo", collect_periodo)
    monkeypatch.setattr(html_periodic_dashboard, "generate", generate)
    return chamadas


def test_gerar_semanal_despacha_por_semana(monkeypatch):
    import config
    from admin.relatorios import gerar
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    c = _fakes_periodicos(monkeypatch)
    nome = gerar("semanal", date(2026, 9, 24))                                   # quinta
    assert c["collect_range"] == (date(2026, 9, 21), date(2026, 9, 28), "semanal", date(2026, 9, 28))
    assert c["collect_periodo"] == (date(2026, 9, 21), date(2026, 9, 27))
    data, ini, fim, tipo, hoje = c["generate"]
    assert (ini, fim, tipo, hoje) == (date(2026, 9, 21), date(2026, 9, 27), "semanal", date(2026, 9, 28))
    assert data["perfex"] == {"leads": None} and data["retroativo"] is True
    assert nome == "briefing-semanal-fake.html"


def test_gerar_mensal_despacha_por_mes(monkeypatch):
    import config
    from admin.relatorios import gerar
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    c = _fakes_periodicos(monkeypatch)
    gerar("mensal", date(2026, 9, 15))
    assert c["collect_range"] == (date(2026, 9, 1), date(2026, 10, 1), "mensal", date(2026, 10, 1))
    assert c["collect_periodo"] == (date(2026, 9, 1), date(2026, 9, 30))
    assert c["generate"][1:] == (date(2026, 9, 1), date(2026, 9, 30), "mensal", date(2026, 10, 1))


def test_gerar_com_trava_ocupada(monkeypatch):
    import config
    from admin.filelock import FileLock
    from admin.relatorios import gerar, GeracaoEmAndamento
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    with FileLock(os.path.join(config.DATA_DIR, "gerar.lock")):
        with pytest.raises(GeracaoEmAndamento):
            gerar("diario", date(2026, 10, 20))
