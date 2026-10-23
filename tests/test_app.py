import re
from datetime import date
import pytest


@pytest.fixture
def client(monkeypatch):
    import config
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    from admin.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _csrf(client, path):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_raiz_redireciona(client):
    r = client.get("/admin/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/relatorios")


def test_relatorios_lista(client):
    import config, os
    open(os.path.join(config.OUTPUT_DIR, "briefing-21-10-2026.html"), "w").close()
    html = client.get("/admin/relatorios").get_data(as_text=True)
    assert "briefing-21-10-2026.html" in html and "20/10/2026" in html


def test_gerar_exige_csrf(client):
    r = client.post("/admin/relatorios/gerar", data={"tipo": "diario", "data": "2026-10-20"})
    assert r.status_code == 400


def test_gerar_chama_relatorios_gerar(client, monkeypatch):
    from admin import relatorios
    monkeypatch.setattr(relatorios, "gerar", lambda tipo, d: "briefing-21-10-2026.html")
    tok = _csrf(client, "/admin/relatorios")
    r = client.post("/admin/relatorios/gerar", data={"tipo": "diario", "data": "2026-10-20", "csrf_token": tok})
    assert r.status_code == 302 and "briefing-21-10-2026.html" in r.headers["Location"]


def test_gerar_data_invalida_mostra_erro(client):
    tok = _csrf(client, "/admin/relatorios")
    r = client.post("/admin/relatorios/gerar", data={"tipo": "diario", "data": "2026-10-23", "csrf_token": tok}, follow_redirects=True)
    assert "dias já encerrados" in r.get_data(as_text=True)


def test_formulario_limita_data_a_ontem(client):
    html = client.get("/admin/relatorios").get_data(as_text=True)
    assert 'name="data"' in html and 'max="2026-10-22"' in html
    assert 'name="data" id="data" required' not in html


def test_existente_sem_regerar_abre_sem_gerar(client, monkeypatch):
    import config, os
    from admin import relatorios
    open(os.path.join(config.OUTPUT_DIR, "briefing-21-10-2026.html"), "w").close()
    chamadas = []
    monkeypatch.setattr(relatorios, "gerar", lambda tipo, d: chamadas.append((tipo, d)) or "x.html")
    tok = _csrf(client, "/admin/relatorios")
    r = client.post("/admin/relatorios/gerar", data={"tipo": "diario", "data": "2026-10-20", "csrf_token": tok})
    assert r.status_code == 302 and r.headers["Location"] == relatorios.url_de("briefing-21-10-2026.html")
    assert chamadas == []


def test_mensal_usa_campo_mes(client, monkeypatch):
    from admin import relatorios
    chamadas = []
    monkeypatch.setattr(relatorios, "gerar", lambda tipo, d: chamadas.append((tipo, d)) or "briefing-mensal-09-2026.html")
    tok = _csrf(client, "/admin/relatorios")
    r = client.post("/admin/relatorios/gerar", data={"tipo": "mensal", "mes": "2026-09", "csrf_token": tok})
    assert r.status_code == 302 and chamadas == [("mensal", date(2026, 9, 1))]


def test_gerar_sem_erp_mostra_erro_e_preserva_arquivo(client, monkeypatch):
    import config, os, briefing_core
    alvo = os.path.join(config.OUTPUT_DIR, "briefing-21-10-2026.html")
    with open(alvo, "w", encoding="utf-8") as f:
        f.write("ok")
    monkeypatch.setattr(briefing_core, "collect_all_data",
                        lambda hoje=None: {"faturamento": None, "agenda": None, "profissionais": None})
    tok = _csrf(client, "/admin/relatorios")
    r = client.post("/admin/relatorios/gerar",
                    data={"tipo": "diario", "data": "2026-10-20", "regerar": "1", "csrf_token": tok},
                    follow_redirects=True)
    assert "ERP indisponível" in r.get_data(as_text=True)
    assert open(alvo, encoding="utf-8").read() == "ok"
