# tests/test_briefing_core.py
from datetime import date


def _boom(*a, **k):
    raise RuntimeError("db off")


def _fake(chamadas, chave, retorno):
    """Fake de coletor: registra o argumento `hoje` e devolve `retorno`."""
    def f(hoje=None):
        chamadas[chave] = hoje
        return retorno
    return f


def test_collect_all_data_hoje_real(monkeypatch):
    import briefing_core as bc, config
    d = date(2026, 10, 20)
    monkeypatch.setattr(config, "hoje_local", lambda: d)      # nao retroativo
    chamadas = {}
    monkeypatch.setattr(bc.erp_mysql, "collect_all", _fake(chamadas, "erp", {"faturamento": {"x": 1}}))
    monkeypatch.setattr(bc.perfex_crm, "collect_all", _fake(chamadas, "perfex", {"leads": None}))
    monkeypatch.setattr(bc.satisfycam, "collect_all", _fake(chamadas, "scam", {"relatorio": None}))
    monkeypatch.setattr(bc.google_reviews, "collect_all", lambda: {"reviews": None})

    data = bc.collect_all_data(d)

    assert chamadas["erp"] == d and chamadas["scam"] == d
    assert chamadas["perfex"] is None                 # briefing das 8h mantem a janela atual (spec §3)
    assert data["faturamento"] == {"x": 1}            # ERP achatado na raiz
    assert data["perfex"] == {"leads": None} and data["google"] == {"reviews": None}
    assert not data.get("retroativo")


def test_retroativo_pula_google_e_satisfycam(monkeypatch):
    import briefing_core as bc, config
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    chamadas = {}
    monkeypatch.setattr(bc.erp_mysql, "collect_all", _fake(chamadas, "erp", {}))
    monkeypatch.setattr(bc.perfex_crm, "collect_all", _fake(chamadas, "perfex", {}))
    monkeypatch.setattr(bc.satisfycam, "collect_all", _boom)
    monkeypatch.setattr(bc.google_reviews, "collect_all", _boom)
    data = bc.collect_all_data(date(2026, 10, 1))
    assert chamadas["perfex"] == date(2026, 10, 1)   # retroativo: perfex filtra por hoje-1
    assert data["google"] == {"reviews": None, "retroativo": True}
    assert data["satisfycam"] == {"relatorio": None, "retroativo": True}
    assert data["retroativo"] is True


def test_colector_com_excecao_vira_dict_vazio(monkeypatch):
    import briefing_core as bc
    monkeypatch.setattr(bc.erp_mysql, "collect_all", _boom)
    monkeypatch.setattr(bc.perfex_crm, "collect_all", lambda hoje=None: {})
    monkeypatch.setattr(bc.satisfycam, "collect_all", lambda hoje=None: {})
    monkeypatch.setattr(bc.google_reviews, "collect_all", lambda: {})
    data = bc.collect_all_data()
    assert data["perfex"] == {} and "faturamento" not in data
