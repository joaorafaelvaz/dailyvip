from datetime import datetime, timedelta
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


def test_atualizar_preserva_pausado_e_recalcula():
    db, ag = _db()
    aid = ag.criar(db, "x", D, datetime(2026,10,25,15,0,tzinfo=TZ), {"tipo":"diaria"}, None)
    assert ag.mudar_estado(db, aid, "pausado") == 1
    assert ag.atualizar(db, aid, "y", D, datetime(2026,11,1,9,0,tzinfo=TZ), {"tipo":"diaria"}, None) == 1
    a = ag.obter(db, aid)
    assert a["estado"] == "pausado" and a["texto"] == "y" and a["proximo_envio"] == datetime(2026,11,1,9,0,tzinfo=TZ)


def test_atualizar_com_primeiro_no_passado_recalcula_a_partir_de_agora(monkeypatch):
    import config
    db, ag = _db()
    aid = ag.criar(db, "x", D, datetime(2026,10,25,15,0,tzinfo=TZ), {"tipo":"diaria"}, None)
    monkeypatch.setattr(config, "agora_local", lambda: datetime(2026,10,27,10,0,tzinfo=TZ))   # 2 dias depois (terça)
    # Regra alterada (diária -> semanal às terças): recalcula a partir de agora, não de `primeiro`
    assert ag.atualizar(db, aid, "novo", D, datetime(2026,10,25,15,0,tzinfo=TZ), {"tipo":"semanal","dias":[1]}, None) == 1
    a = ag.obter(db, aid)
    assert a["texto"] == "novo" and a["estado"] == "ativo" and a["proximo_envio"] == datetime(2026,10,27,15,0,tzinfo=TZ)


def test_atualizar_mantem_ocorrencia_vencida_se_regra_inalterada(monkeypatch):
    """Job atrasado: a ocorrência vencida ainda não foi enviada; editar só o texto não a pula."""
    import config
    db, ag = _db()
    p = datetime(2026,10,25,15,0,tzinfo=TZ)
    aid = ag.criar(db, "x", D, p, {"tipo":"diaria"}, None)
    monkeypatch.setattr(config, "agora_local", lambda: datetime(2026,10,27,10,0,tzinfo=TZ))
    assert ag.atualizar(db, aid, "novo", D, p, {"tipo":"diaria"}, None) == 1
    a = ag.obter(db, aid)
    assert a["texto"] == "novo" and a["estado"] == "ativo" and a["proximo_envio"] == p
    # ...mas um `fim` anterior à ocorrência vencida encerra o agendamento
    assert ag.atualizar(db, aid, "novo", D, p, {"tipo":"diaria"}, datetime(2026,10,24,23,59,59,tzinfo=TZ)) == 1
    a = ag.obter(db, aid)
    assert a["estado"] == "concluido" and a["proximo_envio"] is None


def test_atualizar_usa_estado_atual_do_banco_e_nao_o_lido(monkeypatch):
    """Outra requisição pausa entre a leitura e o UPDATE: o estado gravado é o do banco."""
    db, ag = _db()
    aid = ag.criar(db, "x", D, datetime(2026,10,25,15,0,tzinfo=TZ), {"tipo":"diaria"}, None)
    obter_original = ag.obter
    def obter_e_pausa(con, i):
        r = obter_original(con, i)
        db.execute("UPDATE agendamentos SET estado='pausado' WHERE id=?", (i,))
        return r
    monkeypatch.setattr(ag, "obter", obter_e_pausa)
    assert ag.atualizar(db, aid, "y", D, datetime(2026,11,1,9,0,tzinfo=TZ), {"tipo":"diaria"}, None) == 1
    assert obter_original(db, aid)["estado"] == "pausado"


def test_atualizar_unico_atrasado_pendente_nao_conclui(monkeypatch):
    import config
    db, ag = _db()
    p = datetime(2026,10,25,15,0,tzinfo=TZ)
    aid = ag.criar(db, "x", D, p, {"tipo":"nenhuma"}, None)
    monkeypatch.setattr(config, "agora_local", lambda: p + timedelta(minutes=5))
    assert ag.atualizar(db, aid, "novo", D, p, {"tipo":"nenhuma"}, None) == 1
    a = ag.obter(db, aid)
    assert a["estado"] == "ativo" and a["proximo_envio"] == p


def test_atualizar_nao_toca_cancelado_nem_enviando():
    db, ag = _db()
    p = datetime(2026,10,25,15,0,tzinfo=TZ)
    a1 = ag.criar(db, "x", D, p, {"tipo":"nenhuma"}, None); ag.mudar_estado(db, a1, "cancelado")
    a2 = ag.criar(db, "x", D, p, {"tipo":"nenhuma"}, None); ag.reservar_vencidos(db, agora=p + timedelta(minutes=1))
    assert ag.atualizar(db, a1, "y", D, p, {"tipo":"nenhuma"}, None) == 0
    assert ag.atualizar(db, a2, "y", D, p, {"tipo":"nenhuma"}, None) == 0
    assert ag.obter(db, a1)["texto"] == "x" and ag.obter(db, a2)["estado"] == "enviando"


def test_transicoes_de_estado():
    import pytest
    db, ag = _db()
    p = datetime(2026,10,25,15,0,tzinfo=TZ)
    aid = ag.criar(db, "x", D, p, {"tipo":"diaria"}, None)
    assert ag.mudar_estado(db, aid, "cancelado") == 1
    assert ag.mudar_estado(db, aid, "ativo") == 0 and ag.obter(db, aid)["estado"] == "cancelado"   # recusado
    aid2 = ag.criar(db, "x", D, p, {"tipo":"diaria"}, None)
    ag.reservar_vencidos(db, agora=p + timedelta(minutes=1))
    assert ag.mudar_estado(db, aid2, "pausado") == 0 and ag.obter(db, aid2)["estado"] == "enviando"  # recusado
    aid3 = ag.criar(db, "x", D, p, {"tipo":"diaria"}, None)
    db.execute("UPDATE agendamentos SET falhas_consecutivas=3, estado='pausado' WHERE id=?", (aid3,))
    assert ag.mudar_estado(db, aid3, "ativo") == 1
    a = ag.obter(db, aid3)
    assert a["estado"] == "ativo" and a["falhas_consecutivas"] == 0        # retomar zera o contador
    with pytest.raises(ValueError):
        ag.mudar_estado(db, aid3, "concluido")                             # só a máquina conclui


def test_concluir_ciclo_nao_registra_pausa_se_cancelado_durante_envio():
    db, ag = _db()
    p = datetime(2026,10,25,15,0,tzinfo=TZ)
    aid = ag.criar(db, "x", D, p, {"tipo":"diaria"}, None)
    db.execute("UPDATE agendamentos SET falhas_consecutivas=2 WHERE id=?", (aid,))
    ag.reservar_vencidos(db, agora=p + timedelta(minutes=1))
    db.execute("UPDATE agendamentos SET estado='cancelado' WHERE id=?", (aid,))   # usuário cancelou no meio
    assert ag.concluir_ciclo(db, aid, None, sucesso=False) == 0
    assert ag.obter(db, aid)["estado"] == "cancelado" and ag.historico(db) == []
