from datetime import datetime
from zoneinfo import ZoneInfo
TZ = ZoneInfo("America/Sao_Paulo")
D = {"unidades": [61], "todas": False, "franqueadora": False}


def _db():
    from admin import agendamentos as ag
    db = ag.conectar(":memory:"); ag.criar_schema(db); return db, ag


def test_crud_e_estados():
    db, ag = _db()
    aid = ag.criar(db, texto="Olá", destinos=D, primeiro=datetime(2026,10,25,15,0,tzinfo=TZ), rec={"tipo":"diaria"}, fim=None)
    a = ag.obter(db, aid)
    assert a["estado"] == "ativo" and a["proximo_envio"] == datetime(2026,10,25,15,0,tzinfo=TZ)
    ag.mudar_estado(db, aid, "pausado"); assert ag.obter(db, aid)["estado"] == "pausado"
    assert [x["id"] for x in ag.listar(db)] == [aid]


def test_vencidos_marca_enviando():
    db, ag = _db()
    aid = ag.criar(db, "x", D, datetime(2026,10,25,15,0,tzinfo=TZ), {"tipo":"nenhuma"}, None)
    v = ag.reservar_vencidos(db, agora=datetime(2026,10,25,15,1,tzinfo=TZ))
    assert [x["id"] for x in v] == [aid] and ag.obter(db, aid)["estado"] == "enviando"
    assert ag.reservar_vencidos(db, agora=datetime(2026,10,25,15,2,tzinfo=TZ)) == []   # não reserva duas vezes


def test_recupera_enviando_presos():
    db, ag = _db()
    aid = ag.criar(db, "x", D, datetime(2026,10,25,15,0,tzinfo=TZ), {"tipo":"nenhuma"}, None)
    ag.reservar_vencidos(db, agora=datetime(2026,10,25,15,1,tzinfo=TZ))
    ag.recuperar_presos(db, agora=datetime(2026,10,25,15,20,tzinfo=TZ), minutos=10)
    assert ag.obter(db, aid)["estado"] == "ativo"


def test_resolver_destinos(monkeypatch):
    import config
    from admin import agendamentos as ag
    monkeypatch.setattr(config, "UNIT_GROUPS", {"61": {"nome":"SC 401","chat_id":"a@g.us"}, "20": {"nome":"Itajaí","chat_ids":["b@c.us","c@g.us"]}})
    monkeypatch.setattr(config, "WAHA_RECIPIENTS", ["f@g.us"])
    r = ag.resolver_destinos({"unidades":[61,20],"todas":False,"franqueadora":True})
    assert r == [("a@g.us","SC 401"),("b@c.us","Itajaí"),("c@g.us","Itajaí"),("f@g.us","Franqueadora")]
    assert len(ag.resolver_destinos({"unidades":[],"todas":True,"franqueadora":False})) == 3
