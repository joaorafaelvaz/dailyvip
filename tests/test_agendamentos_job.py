from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
TZ = ZoneInfo("America/Sao_Paulo")
T0 = datetime(2026,10,25,15,0,tzinfo=TZ)


def _setup(monkeypatch, enviados, resposta=lambda chat: True):
    import config
    from admin import agendamentos as ag
    from scheduler import agendamentos_job as job
    db = ag.conectar(":memory:"); ag.criar_schema(db)
    monkeypatch.setattr(job.time, "sleep", lambda s: None)
    # O job recebe a conexao do teste (con=db) e nao a fecha; em producao abre e fecha a sua.
    original = job.processar_agendamentos
    monkeypatch.setattr(job, "processar_agendamentos", lambda agora=None, con=None: original(agora=agora, con=db if con is None else con))
    monkeypatch.setattr(config, "UNIT_GROUPS", {"61": {"nome":"SC 401","chat_id":"a@g.us"}, "63": {"nome":"Barreiros","chat_id":"b@g.us"}})
    monkeypatch.setattr(job.waha, "send_text", lambda chat, text: enviados.append(chat) or resposta(chat))
    return db, ag, job


def test_envia_vencido_e_avanca(monkeypatch):
    env = []; db, ag, job = _setup(monkeypatch, env)
    aid = ag.criar(db, "oi", {"unidades":[61,63],"todas":False,"franqueadora":False}, T0, {"tipo":"diaria"}, None)
    job.processar_agendamentos(agora=T0 + timedelta(minutes=1))
    assert env == ["a@g.us","b@g.us"]
    a = ag.obter(db, aid)
    assert a["estado"] == "ativo" and a["proximo_envio"] == T0 + timedelta(days=1)
    assert {h["status"] for h in ag.historico(db)} == {"enviado"}


def test_atraso_maior_que_2h_marca_perdido(monkeypatch):
    env = []; db, ag, job = _setup(monkeypatch, env)
    aid = ag.criar(db, "oi", {"unidades":[61],"todas":False,"franqueadora":False}, T0, {"tipo":"nenhuma"}, None)
    job.processar_agendamentos(agora=T0 + timedelta(hours=3))
    assert env == [] and ag.obter(db, aid)["estado"] == "concluido"
    assert ag.historico(db)[0]["status"] == "perdido"


def test_sucesso_parcial_conta_como_ciclo_ok(monkeypatch):
    env = []; db, ag, job = _setup(monkeypatch, env, resposta=lambda chat: chat == "a@g.us")
    aid = ag.criar(db, "oi", {"unidades":[61,63],"todas":False,"franqueadora":False}, T0, {"tipo":"nenhuma"}, None)
    job.processar_agendamentos(agora=T0 + timedelta(minutes=1))
    a = ag.obter(db, aid)
    assert a["estado"] == "concluido" and a["falhas_consecutivas"] == 0
    assert sorted(h["status"] for h in ag.historico(db)) == ["enviado", "falhou"]


def test_tres_falhas_pausam_sem_avancar(monkeypatch):
    env = []; db, ag, job = _setup(monkeypatch, env, resposta=lambda chat: False)
    aid = ag.criar(db, "oi", {"unidades":[61],"todas":False,"franqueadora":False}, T0, {"tipo":"diaria"}, None)
    for i in range(3):
        job.processar_agendamentos(agora=T0 + timedelta(minutes=1 + i))
    a = ag.obter(db, aid)
    assert a["estado"] == "pausado" and a["falhas_consecutivas"] == 3 and a["proximo_envio"] == T0


def test_retentativa_nao_reenvia_a_quem_ja_recebeu(monkeypatch):
    env = []
    # 1o ciclo: a ok, b falha -> ciclo ok (>=1 enviado) e, sendo diaria, avanca. Para testar a retentativa,
    # usamos exceção no 1o ciclo: simula queda apos enviar para a.
    db, ag, job = _setup(monkeypatch, env)
    aid = ag.criar(db, "oi", {"unidades":[61,63],"todas":False,"franqueadora":False}, T0, {"tipo":"nenhuma"}, None)
    def send(chat, text):
        env.append(chat)
        if chat == "b@g.us": raise ConnectionError("queda")
        return True
    monkeypatch.setattr(job.waha, "send_text", send)
    job.processar_agendamentos(agora=T0 + timedelta(minutes=1))     # a enviado; exceção em b -> falha do ciclo
    assert ag.obter(db, aid)["estado"] == "ativo" and ag.obter(db, aid)["falhas_consecutivas"] == 1
    monkeypatch.setattr(job.waha, "send_text", lambda chat, text: env.append(chat) or True)
    job.processar_agendamentos(agora=T0 + timedelta(minutes=2))     # só b
    assert env == ["a@g.us", "b@g.us", "b@g.us"]
    assert ag.obter(db, aid)["estado"] == "concluido"


def test_sem_destinos_registra_e_pausa(monkeypatch):
    env = []; db, ag, job = _setup(monkeypatch, env)
    aid = ag.criar(db, "oi", {"unidades":[99],"todas":False,"franqueadora":False}, T0, {"tipo":"diaria"}, None)
    job.processar_agendamentos(agora=T0 + timedelta(minutes=1))
    a = ag.obter(db, aid)
    assert env == [] and a["estado"] == "pausado" and a["proximo_envio"] == T0
    h = ag.historico(db)
    assert [(x["status"], x["chat_id"], x["destino_nome"]) for x in h] == [("pausado", "-", "sistema")]
    assert "sem destinos" in h[0]["erro"]


def test_sleep_so_entre_envios(monkeypatch):
    env = []; db, ag, job = _setup(monkeypatch, env)
    dorme = []
    monkeypatch.setattr(job.time, "sleep", lambda s: dorme.append(s))
    ag.criar(db, "oi", {"unidades":[61,63],"todas":False,"franqueadora":False}, T0, {"tipo":"nenhuma"}, None)
    job.processar_agendamentos(agora=T0 + timedelta(minutes=1))
    assert env == ["a@g.us", "b@g.us"] and dorme == [job.INTERVALO_ENVIO_S]


def test_excecao_ao_fechar_ciclo_nao_derruba_o_ciclo(monkeypatch):
    env = []; db, ag, job = _setup(monkeypatch, env)
    a1 = ag.criar(db, "oi", {"unidades":[61],"todas":False,"franqueadora":False}, T0, {"tipo":"nenhuma"}, None)
    a2 = ag.criar(db, "oi", {"unidades":[63],"todas":False,"franqueadora":False}, T0, {"tipo":"nenhuma"}, None)
    def send(chat, text):
        if chat == "a@g.us": raise ConnectionError("queda")
        env.append(chat); return True
    monkeypatch.setattr(job.waha, "send_text", send)
    original = ag.concluir_ciclo
    def concluir(con, aid, proximo, sucesso, **kw):
        if aid == a1: raise RuntimeError("banco indisponível")
        return original(con, aid, proximo, sucesso, **kw)
    monkeypatch.setattr(ag, "concluir_ciclo", concluir)
    assert job.processar_agendamentos(agora=T0 + timedelta(minutes=1)) == 2
    assert env == ["b@g.us"] and ag.obter(db, a2)["estado"] == "concluido"
