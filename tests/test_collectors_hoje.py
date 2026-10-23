# tests/test_collectors_hoje.py
from datetime import date


def _captura(monkeypatch, modulo):
    chamadas = []
    monkeypatch.setattr(modulo, "_query", lambda sql, args=None: chamadas.append((sql, args)) or [])
    return chamadas


def test_faturamento_ontem_usa_hoje_menos_um(monkeypatch):
    from collectors import erp_mysql
    c = _captura(monkeypatch, erp_mysql)
    erp_mysql.get_faturamento_ontem({}, hoje=date(2026, 10, 20))
    assert c[0][1] == (date(2026, 10, 19), date(2026, 10, 20))


def test_meta_mensal_retroativa_capa_no_hoje(monkeypatch):
    from collectors import erp_mysql
    c = _captura(monkeypatch, erp_mysql)
    r = erp_mysql.get_meta_mensal({}, hoje=date(2026, 10, 20))
    assert c[0][1] == (date(2026, 10, 1), date(2026, 10, 20))   # [inicio do mes de ontem, hoje)
    assert r["pct_mes_corrido"] == round(19 / 31 * 100, 1)       # ontem = dia 19
    c.clear()
    r = erp_mysql.get_meta_mensal({}, hoje=date(2026, 11, 1))    # dia 1: fecha outubro inteiro
    assert c[0][1] == (date(2026, 10, 1), date(2026, 11, 1)) and r["pct_mes_corrido"] == 100.0


def test_agenda_hoje_e_aniversarios_usam_hoje(monkeypatch):
    from collectors import erp_mysql
    c = _captura(monkeypatch, erp_mysql)
    monkeypatch.setattr(erp_mysql, "_get_slots_disponiveis", lambda dt: {})
    erp_mysql.get_agenda_hoje(hoje=date(2026, 10, 20))
    assert date(2026, 10, 20) in c[-1][1]
    c.clear()
    erp_mysql.get_aniversarios_hoje(hoje=date(2026, 3, 5))
    assert c[0][1] == (5, 3, 5, 3)


def test_collect_all_padrao_e_hoje_local(monkeypatch):
    from collectors import erp_mysql
    import config
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    c = _captura(monkeypatch, erp_mysql)
    monkeypatch.setattr(erp_mysql, "_get_slots_disponiveis", lambda dt: {})
    erp_mysql.collect_all()
    assert any(a == (date(2026, 10, 22), date(2026, 10, 23)) for _, a in c)   # faturamento de ontem = 22/10


def test_satisfycam_e_perfex_aceitam_hoje(monkeypatch):
    from collectors import satisfycam, perfex_crm
    monkeypatch.setattr(satisfycam, "_query", lambda sql, args=(): [])
    r = satisfycam.get_relatorio_ontem(hoje=date(2026, 10, 20))
    assert r["data"] == "2026-10-19"
    monkeypatch.setattr(perfex_crm, "_fetch_all_leads", lambda: [
        {"id": 1, "dateadded": "2026-10-19 10:00:00", "status": "1"},
        {"id": 2, "dateadded": "2026-10-20 10:00:00", "status": "1"},
    ])
    r = perfex_crm.get_leads_pipeline(hoje=date(2026, 10, 20))
    assert r["novos_periodo"] == 1   # so o dia 19 (hoje-1)
