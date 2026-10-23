from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
def dt(*a): return datetime(*a, tzinfo=TZ)


def test_unica():
    from admin.agendamentos import proxima_ocorrencia as px
    assert px(None, dt(2026,10,25,15,0), {"tipo":"nenhuma"}, None) == dt(2026,10,25,15,0)
    assert px(dt(2026,10,25,15,0), dt(2026,10,25,15,0), {"tipo":"nenhuma"}, None) is None


def test_diaria_mantem_horario():
    from admin.agendamentos import proxima_ocorrencia as px
    assert px(dt(2026,10,25,15,0), dt(2026,10,25,15,0), {"tipo":"diaria"}, None) == dt(2026,10,26,15,0)
    assert px(None, dt(2026,10,25,15,0), {"tipo":"diaria"}, None) == dt(2026,10,25,15,0)


def test_semanal_varios_dias():
    from admin.agendamentos import proxima_ocorrencia as px
    rec = {"tipo":"semanal","dias":[0,4]}           # seg e sex
    assert px(None, dt(2026,10,21,9,0), rec, None) == dt(2026,10,23,9,0)   # 21/10 é quarta -> sexta 23
    assert px(dt(2026,10,23,9,0), dt(2026,10,21,9,0), rec, None) == dt(2026,10,26,9,0)  # -> segunda 26


def test_mensal_dia_31_e_ultimo():
    from admin.agendamentos import proxima_ocorrencia as px
    assert px(dt(2026,10,31,8,0), dt(2026,10,31,8,0), {"tipo":"mensal","dia":31}, None) == dt(2026,11,30,8,0)
    assert px(None, dt(2026,2,10,8,0), {"tipo":"mensal","dia":"ultimo"}, None) == dt(2026,2,28,8,0)


def test_fim_encerra():
    from admin.agendamentos import proxima_ocorrencia as px
    assert px(dt(2026,10,25,15,0), dt(2026,10,25,15,0), {"tipo":"diaria"}, dt(2026,10,25,23,59)) is None


def test_apos_arbitrario_no_mesmo_dia():
    """`apos` antes do horário do dia: a ocorrência é hoje mesmo, não amanhã."""
    from admin.agendamentos import proxima_ocorrencia as px
    assert px(dt(2026,10,25,10,0), dt(2026,10,25,15,0), {"tipo":"diaria"}, None) == dt(2026,10,25,15,0)
    assert px(dt(2026,10,27,10,0), dt(2026,10,25,15,0), {"tipo":"diaria"}, None) == dt(2026,10,27,15,0)
    # `apos` anterior ao primeiro envio nunca antecipa o primeiro
    assert px(dt(2026,10,20,10,0), dt(2026,10,25,15,0), {"tipo":"diaria"}, None) == dt(2026,10,25,15,0)
