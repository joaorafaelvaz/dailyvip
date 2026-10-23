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
