import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
import pytest

TZ = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def client(monkeypatch):
    import config
    from admin import agendamentos as ag
    db = ag.conectar(":memory:"); ag.criar_schema(db)
    from admin import app as appmod
    monkeypatch.setattr(appmod, "_db", lambda: db)
    monkeypatch.setattr(config, "UNIT_GROUPS", {"61": {"nome":"SC 401","chat_id":"a@g.us"}})
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    monkeypatch.setattr(config, "agora_local", lambda: datetime(2026, 10, 23, 10, 0, tzinfo=TZ))
    app = appmod.create_app(); app.config["TESTING"] = True
    return app.test_client(), db, ag


def _tok(c):
    return re.search(r'name="csrf_token" value="([^"]+)"', c.get("/admin/mensagens").get_data(as_text=True)).group(1)


def test_agendar_valido(client):
    c, db, ag = client
    r = c.post("/admin/mensagens", data={"csrf_token": _tok(c), "texto": "Olá *time*", "unidades": ["61"],
                                        "data": "2026-12-01", "hora": "15:00", "recorrencia": "semanal", "dias": ["0","4"]},
               follow_redirects=True)
    assert "agendada" in r.get_data(as_text=True).lower()
    a = ag.listar(db)[0]
    assert a["recorrencia"] == {"tipo":"semanal","dias":[0,4]} and a["destinos"]["unidades"] == [61]


def test_validacoes(client):
    c, db, ag = client
    base = {"csrf_token": _tok(c), "data": "2026-12-01", "hora": "15:00", "recorrencia": "nenhuma"}
    r = c.post("/admin/mensagens", data={**base, "texto": "", "unidades": ["61"]}, follow_redirects=True)
    assert "texto" in r.get_data(as_text=True).lower() and ag.listar(db) == []
    r = c.post("/admin/mensagens", data={**base, "texto": "x"}, follow_redirects=True)
    assert "destino" in r.get_data(as_text=True).lower()
    r = c.post("/admin/mensagens", data={**base, "texto": "x", "unidades": ["61"], "data": "2020-01-01"}, follow_redirects=True)
    assert "futuro" in r.get_data(as_text=True).lower()


def test_pausar_cancelar(client):
    c, db, ag = client
    aid = ag.criar(db, "x", {"unidades":[61],"todas":False,"franqueadora":False}, datetime(2026,12,1,15,0,tzinfo=TZ), {"tipo":"nenhuma"}, None)
    c.post(f"/admin/mensagens/{aid}/estado", data={"csrf_token": _tok(c), "estado": "pausado"})
    assert ag.obter(db, aid)["estado"] == "pausado"
    c.post(f"/admin/mensagens/{aid}/estado", data={"csrf_token": _tok(c), "estado": "cancelado"})
    assert ag.obter(db, aid)["estado"] == "cancelado"


def test_editar(client):
    c, db, ag = client
    aid = ag.criar(db, "x", {"unidades":[61],"todas":False,"franqueadora":False}, datetime(2026,12,1,15,0,tzinfo=TZ), {"tipo":"nenhuma"}, None)
    r = c.post(f"/admin/mensagens/{aid}/editar", data={"csrf_token": _tok(c), "texto": "novo", "unidades": ["61"],
                                                     "data": "2026-12-02", "hora": "16:00", "recorrencia": "diaria"}, follow_redirects=True)
    a = ag.obter(db, aid)
    assert a["texto"] == "novo" and a["recorrencia"] == {"tipo": "diaria"} and a["proximo_envio"] == datetime(2026,12,2,16,0,tzinfo=TZ)


def test_editar_preenche_formulario_e_botao_ia_desabilitado_sem_chave(client):
    c, db, ag = client
    aid = ag.criar(db, "texto antigo", {"unidades":[61],"todas":False,"franqueadora":True},
                   datetime(2026,12,1,15,0,tzinfo=TZ), {"tipo":"semanal","dias":[0,4]}, None)
    html = c.get(f"/admin/mensagens/{aid}/editar").get_data(as_text=True)
    assert "texto antigo" in html and 'value="2026-12-01"' in html and 'value="15:00"' in html
    assert "Salvar alterações" in html and f"/admin/mensagens/{aid}/editar" in html
    assert 'id="btn-ia" disabled' in html          # ANTHROPIC_API_KEY vazio no conftest


def test_enviando_oculta_botoes(client):
    c, db, ag = client
    aid = ag.criar(db, "x", {"unidades":[61],"todas":False,"franqueadora":False}, datetime(2026,12,1,15,0,tzinfo=TZ), {"tipo":"nenhuma"}, None)
    ag.reservar_vencidos(db, agora=datetime(2026,12,1,15,1,tzinfo=TZ))
    html = c.get("/admin/mensagens").get_data(as_text=True)
    assert "enviando" in html and 'value="cancelado"' not in html


def test_ia_provisoria_503(client):
    c, db, ag = client
    r = c.post("/admin/mensagens/ia", json={"assunto": "x", "tom": "Formal"}, headers={"X-CSRF-Token": _tok(c)})
    assert r.status_code == 503 and "erro" in r.get_json()


def test_editar_enviando_responde_409(client):
    c, db, ag = client
    aid = ag.criar(db, "x", {"unidades":[61],"todas":False,"franqueadora":False}, datetime(2026,10,23,9,0,tzinfo=TZ), {"tipo":"nenhuma"}, None)
    ag.reservar_vencidos(db, agora=datetime(2026,10,23,9,1,tzinfo=TZ))
    tok = _tok(c)
    assert c.get(f"/admin/mensagens/{aid}/editar").status_code == 409
    r = c.post(f"/admin/mensagens/{aid}/editar", data={"csrf_token": tok, "texto": "novo", "unidades": ["61"],
                                                     "data": "2026-12-02", "hora": "16:00", "recorrencia": "nenhuma"})
    assert r.status_code == 409 and ag.obter(db, aid)["texto"] == "x"


def test_editar_mantendo_primeiro_envio_passado(client):
    c, db, ag = client     # agora congelado em 23/10/2026 10:00
    aid = ag.criar(db, "x", {"unidades":[61],"todas":False,"franqueadora":False}, datetime(2026,10,20,15,0,tzinfo=TZ), {"tipo":"diaria"}, None)
    html = c.get(f"/admin/mensagens/{aid}/editar").get_data(as_text=True)
    assert 'value="2026-10-20"' in html and 'min="' not in html          # sem min= na edição
    r = c.post(f"/admin/mensagens/{aid}/editar", data={"csrf_token": _tok(c), "texto": "novo", "unidades": ["61"],
                                                     "data": "2026-10-20", "hora": "15:00", "recorrencia": "diaria"})
    assert r.status_code == 302
    a = ag.obter(db, aid)
    assert a["texto"] == "novo" and a["proximo_envio"] == datetime(2026,10,23,15,0,tzinfo=TZ)
    # Uma data NOVA no passado continua recusada
    r = c.post(f"/admin/mensagens/{aid}/editar", data={"csrf_token": _tok(c), "texto": "novo", "unidades": ["61"],
                                                     "data": "2026-10-21", "hora": "15:00", "recorrencia": "diaria"}, follow_redirects=True)
    assert "futuro" in r.get_data(as_text=True).lower()


def test_estado_transicao_recusada_mostra_erro(client):
    c, db, ag = client
    aid = ag.criar(db, "x", {"unidades":[61],"todas":False,"franqueadora":False}, datetime(2026,12,1,15,0,tzinfo=TZ), {"tipo":"nenhuma"}, None)
    c.post(f"/admin/mensagens/{aid}/estado", data={"csrf_token": _tok(c), "estado": "cancelado"})
    r = c.post(f"/admin/mensagens/{aid}/estado", data={"csrf_token": _tok(c), "estado": "ativo"}, follow_redirects=True)
    assert "não foi possível" in r.get_data(as_text=True).lower() and ag.obter(db, aid)["estado"] == "cancelado"
    assert c.post(f"/admin/mensagens/{aid}/estado", data={"csrf_token": _tok(c), "estado": "concluido"}).status_code == 400


def test_agendar_informa_primeiro_envio_calculado(client):
    c, db, ag = client
    # 01/12/2026 é terça; semanal seg/sex -> primeiro envio sexta 04/12
    r = c.post("/admin/mensagens", data={"csrf_token": _tok(c), "texto": "x", "unidades": ["61"], "data": "2026-12-01",
                                        "hora": "15:00", "recorrencia": "semanal", "dias": ["0","4"]}, follow_redirects=True)
    assert "04/12/2026 15:00" in r.get_data(as_text=True)


def test_todas_sem_unidades_configuradas_e_erro(client, monkeypatch):
    import config
    c, db, ag = client
    monkeypatch.setattr(config, "UNIT_GROUPS", {})
    r = c.post("/admin/mensagens", data={"csrf_token": _tok(c), "texto": "x", "todas": "1", "data": "2026-12-01",
                                        "hora": "15:00", "recorrencia": "nenhuma"}, follow_redirects=True)
    assert "destino" in r.get_data(as_text=True).lower() and ag.listar(db) == []
