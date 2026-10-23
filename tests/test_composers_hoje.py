# tests/test_composers_hoje.py
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


def _congela_relogio(monkeypatch):
    import config
    monkeypatch.setattr(
        config, "agora_local",
        lambda: datetime(2026, 10, 21, 14, 37, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )


def test_html_dashboard_usa_hoje_no_nome_e_gerado_em_na_hora(monkeypatch):
    from composers import html_dashboard
    _congela_relogio(monkeypatch)
    path = html_dashboard.generate({"retroativo": True}, hoje=date(2026, 10, 21))
    assert os.path.basename(path) == "briefing-21-10-2026.html"
    html = open(path, encoding="utf-8").read()
    assert "21/10/2026" in html and "Gerado às 14:37" in html
    assert "indisponíveis para datas retroativas" in html


def test_periodic_dashboard_aceita_hoje(monkeypatch):
    from composers import html_periodic_dashboard
    _congela_relogio(monkeypatch)
    path = html_periodic_dashboard.generate({}, date(2026, 9, 21), date(2026, 9, 27), tipo="semanal", hoje=date(2026, 10, 1))
    assert os.path.basename(path) == "briefing-semanal-27-09-2026.html"
    html = open(path, encoding="utf-8").read()
    assert "Gerado às 14:37" in html
