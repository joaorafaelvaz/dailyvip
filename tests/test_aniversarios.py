# tests/test_aniversarios.py — rotina de clientes aniversariantes por unidade
from datetime import date, datetime

import pytest


def _captura(monkeypatch, modulo):
    chamadas = []
    monkeypatch.setattr(modulo, "_query", lambda sql, args=None: chamadas.append((sql, args)) or [])
    return chamadas


# ── Coletor ───────────────────────────────────────────────────────────────────

def test_meses_atras_limita_dia_ao_fim_do_mes():
    from collectors.erp_mysql import _meses_atras
    assert _meses_atras(date(2026, 10, 29), 12) == date(2025, 10, 29)
    assert _meses_atras(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert _meses_atras(date(2024, 2, 29), 12) == date(2023, 2, 28)


def test_aniversariantes_parametros_e_janela(monkeypatch):
    from collectors import erp_mysql
    c = _captura(monkeypatch, erp_mysql)
    erp_mysql.get_aniversariantes_clientes(hoje=date(2026, 10, 29))
    sql, args = c[0]
    assert args == (date(2026, 10, 29), 29, 10, date(2025, 10, 29), date(2026, 10, 30))
    assert "c.marketing = 1" in sql and "c.status = 1" in sql and "u.status = 1" in sql
    assert sql.count("DAY(c.data_nascimento)") == 1


def test_aniversariantes_29_fevereiro_entra_em_1_marco_ano_nao_bissexto(monkeypatch):
    from collectors import erp_mysql
    c = _captura(monkeypatch, erp_mysql)
    erp_mysql.get_aniversariantes_clientes(hoje=date(2026, 3, 1))     # 2026 não é bissexto
    sql, args = c[0]
    assert args == (date(2026, 3, 1), 1, 3, 29, 2, date(2025, 3, 1), date(2026, 3, 2))
    assert sql.count("DAY(c.data_nascimento)") == 2
    c.clear()
    erp_mysql.get_aniversariantes_clientes(hoje=date(2028, 3, 1))     # 2028 é bissexto: 29/02 existe
    assert c[0][1] == (date(2028, 3, 1), 1, 3, date(2027, 3, 1), date(2028, 3, 2))


def test_aniversariantes_usa_hoje_local_e_meses_config(monkeypatch):
    from collectors import erp_mysql
    import config
    c = _captura(monkeypatch, erp_mysql)
    monkeypatch.setattr(config, "ANIVERSARIOS_MESES", 6)
    erp_mysql.get_aniversariantes_clientes()                          # relógio congelado: 23/10/2026
    assert c[0][1] == (date(2026, 10, 23), 23, 10, date(2026, 4, 23), date(2026, 10, 24))


# ── Compositor ────────────────────────────────────────────────────────────────

def _row(nome, uid=1, tel="(48) 99999-0001", anos=30, visita=datetime(2026, 9, 12, 15, 0), unome="Florianópolis - Santa Mônica"):
    return {"cliente_nome": nome, "unidade_id": uid, "cliente_telefone": tel, "anos": anos,
            "ultima_visita": visita, "unidade_nome": unome}


def test_compose_vazio_retorna_string_vazia():
    from composers import whatsapp_aniversarios_message as m
    assert m.compose_for_unit([], "Qualquer", date(2026, 10, 29)) == ""


def test_compose_formata_cabecalho_clientes_e_telefones():
    from composers import whatsapp_aniversarios_message as m
    rows = [_row("Ana Lima"), _row("Bruno Souza", tel="48988887777", anos=41, visita=datetime(2026, 1, 3))]
    txt = m.compose_for_unit(rows, "Florianópolis - Santa Mônica", date(2026, 10, 29))
    assert "🎂 *ANIVERSARIANTES DE HOJE* — 29/10/2026" in txt
    assert "📍 *Florianópolis - Santa Mônica*" in txt
    assert "*2* clientes que visitaram a unidade nos últimos 12 meses" in txt
    assert "• Ana Lima — 30 anos | 📱 (48) 99999-0001 | última visita 12/09" in txt
    assert "• Bruno Souza — 41 anos | 📱 (48) 98888-7777 | última visita 03/01" in txt


def test_compose_singular_sem_telefone_e_sem_idade():
    from composers import whatsapp_aniversarios_message as m
    txt = m.compose_for_unit([_row("Caio", tel=None, anos=0, visita=None)], "X", date(2026, 10, 29))
    assert "*1* cliente que visitou a unidade" in txt
    assert "• Caio | 📱 sem telefone" in txt and "última visita" not in txt


def test_fmt_telefone_variantes():
    from composers.whatsapp_aniversarios_message import _fmt_telefone
    assert _fmt_telefone("5548999990001") == "(48) 99999-0001"
    assert _fmt_telefone("4833330001") == "(48) 3333-0001"
    assert _fmt_telefone("+55 (48) 9 9999-0001") == "+55 (48) 9 9999-0001"
    assert _fmt_telefone("   ") == "sem telefone"


# ── Job ───────────────────────────────────────────────────────────────────────

GRUPOS = {
    "1": {"nome": "Florianópolis - Santa Mônica", "chat_id": "g1@g.us", "aniversarios": True},
    "20": {"nome": "Itajaí - Centro", "chat_ids": ["g20@g.us", "n20@c.us"], "aniversarios": True},
    "47": {"nome": "BC - Av. Brasil", "chat_id": "g20@g.us"},               # sem flag → não recebe
    "5": {"nome": "BC - Centro", "chat_id": "g5@g.us", "aniversarios": "sim"},  # só true liga
    "x": {"nome": "lixo", "chat_id": "gx@g.us", "aniversarios": True},
}


def test_unidades_ativas_so_com_flag_true_e_only_unit_ignora_flag():
    from scheduler.aniversarios_job import unidades_ativas
    assert set(unidades_ativas(GRUPOS)) == {1, 20}
    assert set(unidades_ativas(GRUPOS, only_unit=47)) == {47}
    assert unidades_ativas(GRUPOS, only_unit=99) == {}
    assert unidades_ativas({}) == {}


def test_montar_envios_agrupa_por_unidade_e_um_envio_por_chat():
    from scheduler.aniversarios_job import montar_envios
    rows = [_row("Ana", uid=1), _row("Beto", uid=20, unome="Itajaí - Centro"),
            _row("Caio", uid=20, unome="Itajaí - Centro"), _row("Dani", uid=47), _row("Edu", uid=5)]
    envios = montar_envios(rows, GRUPOS, date(2026, 10, 29))
    assert [(e["unidade_id"], e["chat_id"], e["total"]) for e in envios] == [
        (1, "g1@g.us", 1), (20, "g20@g.us", 2), (20, "n20@c.us", 2),
    ]
    assert "Beto" in envios[1]["mensagem"] and "Caio" in envios[1]["mensagem"] and "Dani" not in envios[1]["mensagem"]
    assert envios[1]["nome"] == "Itajaí - Centro"


def test_montar_envios_unidade_ativa_sem_aniversariante_nao_gera_envio():
    from scheduler.aniversarios_job import montar_envios
    assert montar_envios([_row("Ana", uid=1)], GRUPOS, date(2026, 10, 29))[0]["unidade_id"] == 1
    assert montar_envios([], GRUPOS, date(2026, 10, 29)) == []


def test_montar_envios_only_unit_sem_flag(caplog):
    from scheduler.aniversarios_job import montar_envios
    envios = montar_envios([_row("Dani", uid=47), _row("Ana", uid=1)], GRUPOS, date(2026, 10, 29), only_unit=47)
    assert [(e["unidade_id"], e["chat_id"]) for e in envios] == [(47, "g20@g.us")]


def test_run_dry_nao_envia_e_test_envia_por_chat(monkeypatch, capsys):
    import config
    from scheduler import aniversarios_job as job
    monkeypatch.setattr(config, "UNIT_GROUPS", GRUPOS)
    monkeypatch.setattr(job.erp_mysql, "get_aniversariantes_clientes",
                        lambda hoje=None: [_row("Ana", uid=1), _row("Beto", uid=20), _row("Dani", uid=47)])
    enviados = []
    monkeypatch.setattr(job.waha, "send_text", lambda chat_id, text: enviados.append(chat_id) or chat_id != "n20@c.us")
    monkeypatch.setattr(job.time, "sleep", lambda s: None)

    r = job.run_aniversarios(dry_run=True)
    assert enviados == []
    assert r == {"unidades_ativas": 2, "clientes": 2, "envios": 3, "enviados": 0}
    assert "NÃO enviado" in capsys.readouterr().out

    r = job.run_aniversarios(dry_run=False)
    assert enviados == ["g1@g.us", "g20@g.us", "n20@c.us"]
    assert r["enviados"] == 2 and r["envios"] == 3


def test_run_sem_unidade_ativa_nao_consulta_erp(monkeypatch):
    import config
    from scheduler import aniversarios_job as job
    monkeypatch.setattr(config, "UNIT_GROUPS", {"47": {"nome": "x", "chat_id": "g@g.us"}})
    monkeypatch.setattr(job.erp_mysql, "get_aniversariantes_clientes", lambda hoje=None: pytest.fail("não devia consultar"))
    assert job.run_aniversarios(dry_run=True)["unidades_ativas"] == 0


def test_run_falha_no_erp_nao_lanca(monkeypatch):
    import config
    from scheduler import aniversarios_job as job
    monkeypatch.setattr(config, "UNIT_GROUPS", GRUPOS)
    def boom(hoje=None):
        raise RuntimeError("mysql fora")
    monkeypatch.setattr(job.erp_mysql, "get_aniversariantes_clientes", boom)
    assert job.run_aniversarios(dry_run=False)["envios"] == 0
