# Área Administrativa (relatórios por data + mensagens agendadas) — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar, sob o login já existente em `status.franquiabv.com.br/admin/`, (1) uma tela que lista os dashboards gerados e gera o de qualquer data sob demanda e (2) uma tela para agendar mensagens (texto livre ou gerado por IA) a unidades, com envio único ou recorrente feito pelo serviço `daily-briefing`.

**Architecture:** App Flask (`admin/`) servido por gunicorn em `127.0.0.1:8081` atrás do nginx (`/admin/`, Basic Auth do nginx). Lógica de coleta extraída de `main.py` para `briefing_core.py` (sem efeitos colaterais de logging) e parametrizada por data de referência `hoje`. Agendamentos em SQLite (`data/agendamentos.db`); o envio é um job de 1 min no scheduler do `daily-briefing`, usando o cliente WAHA e os destinos do `unit_groups.json`.

**Tech Stack:** Python 3.11+, Flask, gunicorn, sqlite3 (stdlib), zoneinfo (+`tzdata` no Windows), APScheduler (já usado), `anthropic` SDK 1.x, pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-admin-dashboard-design.md` — a fonte da verdade; em dúvida, siga a spec.

**Convenções deste plano:**
- Comandos de teste no Windows (máquina de dev): `.venv/Scripts/python -m pytest ...`. No Linux: `.venv/bin/python -m pytest ...`.
- Todo commit termina com a linha de atribuição exigida na sessão (`Co-Authored-By: ...`), como os commits anteriores do repo.
- `hoje_local()` é a ÚNICA forma de obter "hoje" no código novo e refatorado. Nunca `date.today()`.
- Nunca edite `/etc/nginx/sites-available/daily-briefing` por script (é gerenciado pelo Certbot).

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `config.py` (modificar) | `hoje_local()`, `agora_local()`, `DATA_DIR`, `ANTHROPIC_API_KEY`, `ADMIN_TEST_CHAT_ID`, `ADMIN_SECRET_KEY` |
| `briefing_core.py` (criar) | `collect_all_data(hoje)` extraído de `main.py`; zero configuração de logging |
| `collectors/erp_mysql.py` (modificar) | parâmetro `hoje` em todas as funções diárias, `collect_all`, `collect_range`; `get_meta_mensal` capado em `hoje` |
| `collectors/perfex_crm.py`, `satisfycam.py` (modificar) | parâmetro `hoje` |
| `composers/html_dashboard.py`, `html_periodic_dashboard.py` (modificar) | `generate(..., hoje)` + `gerado_em` |
| `templates/dashboard.html.j2` (modificar) | usa `gerado_em` para hora; rótulos retroativos |
| `main.py` (modificar) | importa de `briefing_core`; registra job `processar_agendamentos` |
| `admin/filelock.py` (criar) | trava de arquivo cross-platform |
| `admin/relatorios.py` (criar) | catálogo de `output/`, data↔arquivo, `gerar()` |
| `admin/agendamentos.py` (criar) | schema SQLite, CRUD, `proxima_ocorrencia()` (pura), resolução de destinos |
| `scheduler/agendamentos_job.py` (criar) | `processar_agendamentos()` (passos 0–5 da spec §5) |
| `admin/ia.py` (criar) | `gerar_mensagem(assunto, tom)` via SDK anthropic |
| `admin/prompts/mensagem_sistema.txt` (criar) | system prompt editável |
| `admin/app.py` (criar) | Flask `create_app()`, Blueprint `/admin`, CSRF, rotas |
| `admin/templates/*.html`, `admin/static/admin.css` (criar) | UI |
| `tests/*.py` (criar) | pytest |
| `deploy/daily-admin.service`, `deploy/nginx-admin.conf` (criar); `deploy/deploy.sh`, `deploy/setup.sh`, `deploy/nginx.conf` (modificar) | operação |
| `requirements.txt`, `.gitignore`, `.env.example`, `README.md` (modificar) | housekeeping |

---

## Chunk 1: Fundação — `hoje_local`, `DATA_DIR`, `briefing_core`, coletores por data

### Task 1: Ambiente de testes

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py` (vazio), `tests/conftest.py`, `pytest.ini`

- [ ] **Step 1: Adicionar dependências** — acrescente ao final de `requirements.txt`:

```
flask>=3.0
gunicorn>=21.2
anthropic>=1.0
tzdata>=2024.1
pytest>=8.0
```

- [ ] **Step 2: Instalar no venv de dev**

Run: `.venv/Scripts/python -m pip install -r requirements.txt`
Expected: sem erro; `.venv/Scripts/python -c "import flask, anthropic, pytest, zoneinfo; print('ok')"` imprime `ok`.

- [ ] **Step 3: Criar `pytest.ini` e `tests/conftest.py`**

`pytest.ini`:
```ini
[pytest]
testpaths = tests
pythonpath = .
```

`tests/conftest.py` (isola o `.env` real e o `output/`/`data/` do projeto):
```python
import os
import pytest


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Nenhum teste lê o .env real nem escreve em output/ ou data/ do projeto."""
    monkeypatch.setenv("TIMEZONE", "America/Sao_Paulo")
    monkeypatch.setenv("ADMIN_SECRET_KEY", "test-secret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_TEST_CHAT_ID", raising=False)
    import config
    # config já pode ter sido importado (e lido um .env real): congela os valores de teste
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "ADMIN_TEST_CHAT_ID", "", raising=False)
    monkeypatch.setattr(config, "ADMIN_SECRET_KEY", "test-secret", raising=False)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs(config.DATA_DIR, exist_ok=True)
    yield
```

- [ ] **Step 4: Rodar pytest vazio** — Run: `.venv/Scripts/python -m pytest -q` → Expected: `no tests ran` (exit 5), sem erro de import.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pytest.ini tests/__init__.py tests/conftest.py
git commit -m "chore: dependencias do admin (flask, gunicorn, anthropic, tzdata) e base de testes pytest"
```

### Task 2: `config.hoje_local()`, `DATA_DIR` e variáveis do admin

**Files:**
- Modify: `config.py` (após a linha 88 `os.makedirs(OUTPUT_DIR, exist_ok=True)`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Teste**

```python
# tests/test_config.py
from datetime import date, datetime
from zoneinfo import ZoneInfo


def test_hoje_local_usa_timezone_configurado(monkeypatch):
    import config
    # 23h59 UTC de 23/10 = 20h59 BRT de 23/10 -> mesmo dia
    monkeypatch.setattr(config, "_agora", lambda: datetime(2026, 10, 23, 23, 59, tzinfo=ZoneInfo("UTC")))
    assert config.hoje_local() == date(2026, 10, 23)
    # 02h UTC de 24/10 = 23h BRT de 23/10 -> ainda 23/10 em BRT
    monkeypatch.setattr(config, "_agora", lambda: datetime(2026, 10, 24, 2, 0, tzinfo=ZoneInfo("UTC")))
    assert config.hoje_local() == date(2026, 10, 23)


def test_data_dir_existe():
    import config, os
    assert os.path.isdir(config.DATA_DIR)
```

- [ ] **Step 2: Rodar — deve falhar** — `.venv/Scripts/python -m pytest tests/test_config.py -q` → `AttributeError: module 'config' has no attribute '_agora'`.

- [ ] **Step 3: Implementar em `config.py`** — no topo: `from datetime import datetime` e `from zoneinfo import ZoneInfo`. Após `os.makedirs(OUTPUT_DIR, exist_ok=True)`:

```python
# Dados mutáveis do app administrativo (SQLite, travas) — fora do repo
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)


def _agora() -> datetime:
    """Agora, com fuso. Separado para os testes congelarem o relógio."""
    return datetime.now(ZoneInfo("UTC"))


def agora_local() -> datetime:
    """Agora no fuso do projeto (TIMEZONE)."""
    return _agora().astimezone(ZoneInfo(TIMEZONE))


def hoje_local():
    """Data de hoje no fuso do projeto. ÚNICA fonte de 'hoje' no código.

    Num servidor em UTC, date.today() erra o dia entre 21h e 24h BRT.
    """
    return agora_local().date()


# App administrativo
ANTHROPIC_API_KEY = _optional("ANTHROPIC_API_KEY")
ADMIN_TEST_CHAT_ID = _optional("ADMIN_TEST_CHAT_ID")
ADMIN_SECRET_KEY = _optional("ADMIN_SECRET_KEY") or "troque-no-env"   # vazio no .env tambem cai no default
```

- [ ] **Step 4: Rodar — deve passar** → `2 passed`.

- [ ] **Step 5: `.gitignore` e `.env.example`**

`.gitignore`, nova seção:
```
# Dados do app administrativo (SQLite, travas)
data/
```
`.env.example`, ao final:
```
# ─── Área administrativa (/admin) ─────────────────────────────────────────────
# Chave da API da Anthropic para o botão "Gerar com IA" (console.anthropic.com)
ANTHROPIC_API_KEY=
# Seu número para o botão "Enviar teste para mim" (formato WAHA)
ADMIN_TEST_CHAT_ID=5547999999999@c.us
# Segredo de sessão/CSRF do app (setup.sh gera um aleatório se vazio)
ADMIN_SECRET_KEY=
```

- [ ] **Step 6: Commit**

```bash
git add config.py .gitignore .env.example tests/test_config.py
git commit -m "feat(config): hoje_local() com fuso do projeto, DATA_DIR e variaveis do admin"
```

### Task 3: `briefing_core.py` — coleta sem efeitos colaterais

**Files:**
- Create: `briefing_core.py`
- Modify: `main.py:85-132` (remover `_collect_*` e `collect_all_data`; importar de `briefing_core`)
- Test: `tests/test_briefing_core.py`

- [ ] **Step 1: Teste (coletores substituídos por fakes)**

```python
# tests/test_briefing_core.py
from datetime import date


def _boom(*a, **k):
    raise RuntimeError("db off")


def _fake(chamadas, chave, retorno):
    """Fake de coletor: registra o argumento `hoje` e devolve `retorno`."""
    def f(hoje=None):
        chamadas[chave] = hoje
        return retorno
    return f


def test_collect_all_data_hoje_real(monkeypatch):
    import briefing_core as bc, config
    d = date(2026, 10, 20)
    monkeypatch.setattr(config, "hoje_local", lambda: d)      # nao retroativo
    chamadas = {}
    monkeypatch.setattr(bc.erp_mysql, "collect_all", _fake(chamadas, "erp", {"faturamento": {"x": 1}}))
    monkeypatch.setattr(bc.perfex_crm, "collect_all", _fake(chamadas, "perfex", {"leads": None}))
    monkeypatch.setattr(bc.satisfycam, "collect_all", _fake(chamadas, "scam", {"relatorio": None}))
    monkeypatch.setattr(bc.google_reviews, "collect_all", lambda: {"reviews": None})

    data = bc.collect_all_data(d)

    assert chamadas["erp"] == d and chamadas["scam"] == d
    assert chamadas["perfex"] is None                 # briefing das 8h mantem a janela atual (spec §3)
    assert data["faturamento"] == {"x": 1}            # ERP achatado na raiz
    assert data["perfex"] == {"leads": None} and data["google"] == {"reviews": None}
    assert not data.get("retroativo")


def test_retroativo_pula_google_e_satisfycam(monkeypatch):
    import briefing_core as bc, config
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    chamadas = {}
    monkeypatch.setattr(bc.erp_mysql, "collect_all", _fake(chamadas, "erp", {}))
    monkeypatch.setattr(bc.perfex_crm, "collect_all", _fake(chamadas, "perfex", {}))
    monkeypatch.setattr(bc.satisfycam, "collect_all", _boom)
    monkeypatch.setattr(bc.google_reviews, "collect_all", _boom)
    data = bc.collect_all_data(date(2026, 10, 1))
    assert chamadas["perfex"] == date(2026, 10, 1)   # retroativo: perfex filtra por hoje-1
    assert data["google"] == {"reviews": None, "retroativo": True}
    assert data["satisfycam"] == {"relatorio": None, "retroativo": True}
    assert data["retroativo"] is True


def test_colector_com_excecao_vira_dict_vazio(monkeypatch):
    import briefing_core as bc
    monkeypatch.setattr(bc.erp_mysql, "collect_all", _boom)
    monkeypatch.setattr(bc.perfex_crm, "collect_all", lambda hoje=None: {})
    monkeypatch.setattr(bc.satisfycam, "collect_all", lambda hoje=None: {})
    monkeypatch.setattr(bc.google_reviews, "collect_all", lambda: {})
    data = bc.collect_all_data()
    assert data["perfex"] == {} and "faturamento" not in data
```

- [ ] **Step 2: Rodar — deve falhar** (`ModuleNotFoundError: briefing_core`).

- [ ] **Step 3: Criar `briefing_core.py`**

```python
"""Coleta consolidada do briefing diário, parametrizada por data de referência.

Sem logging.basicConfig nem handlers: importável tanto pelo serviço (main.py)
quanto pelo app administrativo, cada um com seu próprio log.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Optional

import config
from collectors import erp_mysql, google_reviews, perfex_crm, satisfycam

logger = logging.getLogger("briefing")


def collect_all_data(hoje: Optional[date] = None) -> dict:
    """Executa todos os collectors em paralelo para a data de referência `hoje`
    (padrão: hoje no fuso do projeto). 'Ontem' nos relatórios é `hoje - 1`.

    Google Reviews não tem histórico: em data retroativa é pulado.
    """
    hoje = hoje or config.hoje_local()
    retroativo = hoje != config.hoje_local()

    tasks = {
        "erp": lambda: erp_mysql.collect_all(hoje),
        # Sem data (None) o Perfex mantem a janela atual "ultimas 24h"; so em
        # relatorio retroativo filtra pelo dia hoje-1 (spec §3).
        "perfex": lambda: perfex_crm.collect_all(hoje if retroativo else None),
    }
    if not retroativo:
        tasks["satisfycam"] = lambda: satisfycam.collect_all(hoje)
        tasks["google"] = google_reviews.collect_all

    results: dict = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                logger.error("Collector '%s' lançou exceção: %s", name, exc, exc_info=True)
                results[name] = {}

    if retroativo:
        results["google"] = {"reviews": None, "retroativo": True}
        results["satisfycam"] = {"relatorio": None, "retroativo": True}

    erp = results.pop("erp", {}) or {}
    data = {**erp, **results}
    data["retroativo"] = retroativo      # o template usa para rotular "situacao atual"/"indisponivel"
    return data
```

- [ ] **Step 4: Rodar — deve passar** → `3 passed`. (Os coletores reais ainda não aceitam `hoje`; os fakes cobrem. A Task 4 ajusta os reais — e só então o `main.py` passa a usar o `briefing_core`, senão o briefing das 8h cairia no `except` e sairia vazio.)

- [ ] **Step 5: Commit** (o `main.py` só troca para o `briefing_core` na Task 4, depois que os coletores aceitam `hoje`)

```bash
git add briefing_core.py tests/test_briefing_core.py
git commit -m "feat: briefing_core.collect_all_data(hoje) sem efeitos colaterais de logging"
```

### Task 4: Coletores aceitam `hoje`

**Files:**
- Modify: `collectors/erp_mysql.py` (defs nas l.62, 121, 208, 318, 431, 515, 573, 606, 670, 973, 1025), `collectors/perfex_crm.py:143-171,243-251`, `collectors/satisfycam.py:20-22,88-95`
- Test: `tests/test_collectors_hoje.py`

- [ ] **Step 1: Teste (sem banco: `_query` substituído)**

```python
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
```

- [ ] **Step 2: Rodar — deve falhar** (`TypeError: unexpected keyword argument 'hoje'`).

- [ ] **Step 3: Implementar em `erp_mysql.py`** — padrão em cada função: último parâmetro `hoje: Optional[date] = None`; primeira linha do corpo `hoje = hoje or config.hoje_local()`; trocar `date.today()` por `hoje`:

- `get_media_historica(hoje=None)` (l.62): usar `hoje` nos cálculos dos meses.
- `get_faturamento_ontem(media_hist=None, hoje=None)` (l.121): `ontem = hoje - timedelta(days=1)`.
- `get_meta_mensal(media_hist=None, hoje=None)` (l.208): o mês de referência é o de **ontem** (`ref = hoje - timedelta(days=1)`), igual ao faturamento; **substituir** o cálculo de `mes_inicio`/`mes_fim`/`dias_corridos`/`dias_mes` por
  ```python
  # Mes de referencia = mes de "ontem", acumulado ate a data de referencia (exclusive).
  # No dia 1 o briefing das 8h fecha o mes anterior; no on-demand mensal
  # (hoje = dia 1 do mes seguinte) cobre o mes inteiro; em data retroativa
  # nao inclui vendas posteriores a ela.
  ref = hoje - timedelta(days=1)
  mes_inicio = date(ref.year, ref.month, 1)
  mes_fim = hoje
  dias_corridos = ref.day
  dias_mes = calendar.monthrange(ref.year, ref.month)[1]
  ```
  (remova as linhas antigas de `prox_mes`/`prox_ano`/`mes_fim` e os antigos `dias_corridos`/`dias_mes`).
- `get_agenda_ontem(hoje=None)` (l.318), `get_profissionais_ontem(hoje=None)` (l.515): `ontem = hoje - timedelta(days=1)`.
- `get_agenda_hoje(hoje=None)` (l.431), `get_barbeiros_ausentes(hoje=None)` (l.606), `get_aniversarios_hoje(hoje=None)` (l.670): usar `hoje`.
- `get_clientes_sem_retorno(dias=45, hoje=None)` (l.573): `data_alvo = hoje - timedelta(days=dias)`.
- `collect_range(data_inicio, data_fim, tipo="semanal", hoje=None)` (l.973): repassar `hoje` a `get_media_historica(hoje)`, `get_meta_mensal(media_hist, hoje)`, `get_aniversarios_hoje(hoje)`.
- `collect_all(hoje=None)` (l.1025): repassar a todos os `get_*` (ex.: `lambda: get_faturamento_ontem(media_hist, hoje)`).

- [ ] **Step 4: Implementar em `perfex_crm.py` e `satisfycam.py`**

`perfex_crm.get_leads_pipeline(data_inicio=None, data_fim=None, hoje=None)` — no cálculo do período:
```python
    if data_inicio and data_fim:
        inicio_str = str(data_inicio); fim_str = str(data_fim)
    elif hoje is not None:
        # Relatório retroativo: "novos" = criados no dia anterior à data de referência
        inicio_str = fim_str = str(hoje - timedelta(days=1))
    else:
        inicio_str = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d")
        fim_str = str(date.today())
```
`collect_all(hoje=None)`: `result["leads"] = get_leads_pipeline(hoje=hoje)`. **Sem `hoje` o comportamento é idêntico ao atual** (spec §3).

`satisfycam.get_relatorio_ontem(hoje=None)`: `hoje = hoje or config.hoje_local(); ontem = hoje - timedelta(days=1)`. `collect_all(hoje=None)` repassa. Importe `Optional`.

- [ ] **Step 5: Rodar — deve passar** → `5 passed`.

- [ ] **Step 6: Nenhum `date.today()` sobrou** — Run: `grep -n "date.today()" collectors/erp_mysql.py collectors/perfex_crm.py collectors/satisfycam.py` → Expected: só a linha do `else` em `perfex_crm.py` (janela atual, intencional).

- [ ] **Step 7: `main.py` passa a usar `briefing_core`** — apague `_collect_erp`, `_collect_perfex`, `_collect_satisfycam`, `_collect_google` e `collect_all_data` (l.85–129). Acrescente `from briefing_core import collect_all_data` aos imports. Mantenha `from collectors import ... meta_ads`. Remova `ThreadPoolExecutor, as_completed` se ficarem sem uso.

Run: `.venv/Scripts/python -m py_compile main.py && grep -n "collect_all_data" main.py && .venv/Scripts/python -m pytest -q`
Expected: compila; só usos (não `def collect_all_data`); suíte verde.

- [ ] **Step 8: Commit**

```bash
git add collectors/erp_mysql.py collectors/perfex_crm.py collectors/satisfycam.py main.py tests/test_collectors_hoje.py
git commit -m "feat(collectors): data de referencia 'hoje' nos coletores; main.py usa briefing_core"
```

### Task 5: Composers com `hoje` + `gerado_em`

**Files:**
- Modify: `composers/html_dashboard.py:17-36`, `composers/html_periodic_dashboard.py:23-56`, `templates/dashboard.html.j2:31,531` (+ cards CRM/Google)
- Test: `tests/test_composers_hoje.py`

- [ ] **Step 1: Teste**

```python
# tests/test_composers_hoje.py
import os
from datetime import date


def test_html_dashboard_usa_hoje_no_nome_e_gerado_em_na_hora():
    from composers import html_dashboard
    path = html_dashboard.generate({"retroativo": True}, hoje=date(2026, 10, 21))
    assert os.path.basename(path) == "briefing-21-10-2026.html"
    html = open(path, encoding="utf-8").read()
    assert "21/10/2026" in html and "Gerado às 00:00" not in html
    assert "indisponíveis para datas retroativas" in html


def test_periodic_dashboard_aceita_hoje():
    from composers import html_periodic_dashboard
    path = html_periodic_dashboard.generate({}, date(2026, 9, 21), date(2026, 9, 27), tipo="semanal", hoje=date(2026, 10, 1))
    assert os.path.basename(path) == "briefing-semanal-27-09-2026.html"
```

- [ ] **Step 2: Rodar — deve falhar** (`unexpected keyword argument 'hoje'`).

- [ ] **Step 3: Implementar**

`composers/html_dashboard.py` (`from typing import Any, Optional`; remover `datetime` se sem uso):
```python
def generate(data: dict[str, Any], hoje: Optional[date] = None) -> str:
    """Dashboard para a data de referência `hoje` (arquivo briefing-<hoje>.html,
    conteúdo = dia anterior). `gerado_em` é a hora real de geração."""
    hoje = hoje or config.hoje_local()
    env = ...  # inalterado
    html = template.render(
        data=data,
        hoje=hoje,
        gerado_em=config.agora_local(),
        show_satisfycam=config.SHOW_SATISFYCAM,
        show_inadimplencia=config.SHOW_INADIMPLENCIA,
    )
    filename = f"briefing-{hoje.strftime('%d-%m-%Y')}.html"
```
`composers/html_periodic_dashboard.py`: `generate(data, data_inicio, data_fim, tipo="semanal", hoje=None)`; `hoje = hoje or config.hoje_local()`; no render `hoje=hoje, gerado_em=config.agora_local()`.

`templates/dashboard.html.j2`: l.31 → `Gerado às {{ gerado_em.strftime('%H:%M') }}`; l.531 → `Gerado em {{ gerado_em.strftime('%d/%m/%Y às %H:%M') }}`. No card do CRM, rótulo `{{ 'situação atual (snapshot de hoje)' if data.get('retroativo') else 'total no pipeline' }}` — `data['retroativo']` é definido pelo `briefing_core` (diário) e por `admin/relatorios.gerar` (semanal/mensal, Task 7). Antes do bloco `{% if reviews and reviews.total > 0 %}`:
```jinja
{% if data.get('retroativo') %}
<div class="bg-white rounded-2xl shadow p-5 mb-4 text-sm text-gray-400 italic">⭐ Google Reviews e SatisfyCAM: indisponíveis para datas retroativas</div>
{% endif %}
```

- [ ] **Step 4: Rodar — deve passar** → `2 passed`.

- [ ] **Step 5: Suíte completa** — `.venv/Scripts/python -m pytest -q` → tudo verde. `grep -n "html_dashboard.generate\|html_periodic_dashboard.generate" main.py` — chamadas existentes (sem `hoje`) seguem válidas.

- [ ] **Step 6: Commit**

```bash
git add composers/ templates/dashboard.html.j2 tests/test_composers_hoje.py
git commit -m "feat(composers): generate() por data de referencia; hora real em gerado_em; rotulos retroativos"
```

---

## Chunk 2: App Flask + tela de Relatórios

### Task 6: `admin/filelock.py`

**Files:** Create `admin/__init__.py` (vazio), `admin/filelock.py`; Test `tests/test_filelock.py`

- [ ] **Step 1: Teste**

```python
# tests/test_filelock.py
import pytest


def test_trava_exclusiva(tmp_path):
    from admin.filelock import FileLock, LockBusy
    p = tmp_path / "x.lock"
    with FileLock(p):
        with pytest.raises(LockBusy):
            with FileLock(p):
                pass
    with FileLock(p):   # liberada
        pass
```

- [ ] **Step 2: Rodar — deve falhar.**

- [ ] **Step 3: Implementar**

```python
# admin/filelock.py
"""Trava de arquivo não bloqueante, Linux (fcntl) e Windows (msvcrt)."""
import sys


class LockBusy(RuntimeError):
    pass


class FileLock:
    def __init__(self, path):
        self.path = str(path)
        self._fh = None

    def __enter__(self):
        self._fh = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            raise LockBusy(f"trava ocupada: {self.path}")
        return self

    def __exit__(self, *exc):
        if self._fh:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
        return False
```

- [ ] **Step 4: Rodar — deve passar** → `1 passed`. (No Windows, `msvcrt.locking` exige 1 byte no arquivo: se falhar com arquivo vazio, escreva `self._fh.write("x"); self._fh.flush()` antes de travar, uma única vez, quando o arquivo estiver vazio.)

- [ ] **Step 5: Commit** — `git add admin/ tests/test_filelock.py && git commit -m "feat(admin): trava de arquivo cross-platform"`

### Task 7: `admin/relatorios.py` — catálogo e data↔arquivo

**Files:** Create `admin/relatorios.py`; Test `tests/test_relatorios.py`

- [ ] **Step 1: Teste**

```python
# tests/test_relatorios.py
import os
from datetime import date
import pytest


def _touch(nome):
    import config
    open(os.path.join(config.OUTPUT_DIR, nome), "w").close()


def test_parse_nomes():
    from admin.relatorios import parse_nome
    assert parse_nome("briefing-21-10-2026.html") == ("diario", date(2026, 10, 20))     # dia dos dados = arquivo - 1
    assert parse_nome("briefing-semanal-27-09-2026.html") == ("semanal", date(2026, 9, 27))
    assert parse_nome("briefing-mensal-09-2026.html") == ("mensal", date(2026, 9, 1))
    assert parse_nome("index.html") is None
    assert parse_nome("briefing-31-02-2026.html") is None


def test_nome_para():
    from admin.relatorios import nome_para
    assert nome_para("diario", date(2026, 10, 20)) == "briefing-21-10-2026.html"
    assert nome_para("semanal", date(2026, 9, 24)) == "briefing-semanal-27-09-2026.html"  # quarta -> domingo
    assert nome_para("mensal", date(2026, 9, 15)) == "briefing-mensal-09-2026.html"


def test_listar_ordena_mais_recente_primeiro():
    from admin.relatorios import listar
    _touch("briefing-21-10-2026.html"); _touch("briefing-22-10-2026.html"); _touch("briefing-semanal-27-09-2026.html"); _touch("lixo.txt")
    r = listar()
    assert [x["data"] for x in r["diario"]] == [date(2026, 10, 21), date(2026, 10, 20)]
    assert r["semanal"][0]["arquivo"] == "briefing-semanal-27-09-2026.html"
    assert r["mensal"] == []


def test_validar_data(monkeypatch):
    import config
    from admin.relatorios import validar_data, DataInvalida
    monkeypatch.setattr(config, "hoje_local", lambda: date(2026, 10, 23))
    validar_data("diario", date(2026, 10, 22))
    with pytest.raises(DataInvalida):
        validar_data("diario", date(2026, 10, 23))   # dados de hoje ainda não fecharam
    with pytest.raises(DataInvalida):
        validar_data("diario", date(2023, 12, 31))
```

- [ ] **Step 2: Rodar — deve falhar.**

- [ ] **Step 3: Implementar**

```python
# admin/relatorios.py
"""Catálogo dos dashboards em output/ e geração sob demanda por data."""
import calendar
import logging
import os
import re
from datetime import date, timedelta
from typing import Optional

import config
from admin.filelock import FileLock, LockBusy

logger = logging.getLogger("admin.relatorios")

TIPOS = ("diario", "semanal", "mensal")
DATA_MINIMA = date(2024, 1, 1)
_RE_DIARIO = re.compile(r"^briefing-(\d{2})-(\d{2})-(\d{4})\.html$")
_RE_SEMANAL = re.compile(r"^briefing-semanal-(\d{2})-(\d{2})-(\d{4})\.html$")
_RE_MENSAL = re.compile(r"^briefing-mensal-(\d{2})-(\d{4})\.html$")


class DataInvalida(ValueError):
    pass


class GeracaoEmAndamento(RuntimeError):
    pass


def _safe_date(y, m, d) -> Optional[date]:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def parse_nome(nome: str):
    """(tipo, data_chave) ou None. Diário: chave = dia dos dados (arquivo - 1);
    semanal = domingo final; mensal = dia 1 do mês."""
    m = _RE_DIARIO.match(nome)
    if m:
        dt = _safe_date(m[3], m[2], m[1])
        return ("diario", dt - timedelta(days=1)) if dt else None
    m = _RE_SEMANAL.match(nome)
    if m:
        dt = _safe_date(m[3], m[2], m[1])
        return ("semanal", dt) if dt else None
    m = _RE_MENSAL.match(nome)
    if m:
        dt = _safe_date(m[2], m[1], 1)
        return ("mensal", dt) if dt else None
    return None


def semana_de(d: date) -> tuple[date, date]:
    """Segunda e domingo da semana que contém `d`."""
    seg = d - timedelta(days=d.weekday())
    return seg, seg + timedelta(days=6)


def nome_para(tipo: str, d: date) -> str:
    if tipo == "diario":
        return f"briefing-{(d + timedelta(days=1)).strftime('%d-%m-%Y')}.html"
    if tipo == "semanal":
        return f"briefing-semanal-{semana_de(d)[1].strftime('%d-%m-%Y')}.html"
    if tipo == "mensal":
        return f"briefing-mensal-{d.strftime('%m-%Y')}.html"
    raise ValueError(tipo)


def existe(tipo: str, d: date) -> bool:
    return os.path.exists(os.path.join(config.OUTPUT_DIR, nome_para(tipo, d)))


def url_de(nome: str) -> str:
    return f"{config.DASHBOARD_BASE_URL}/{nome}"


def listar() -> dict[str, list[dict]]:
    out = {t: [] for t in TIPOS}
    for nome in os.listdir(config.OUTPUT_DIR):
        p = parse_nome(nome)
        if p:
            tipo, d = p
            out[tipo].append({"arquivo": nome, "data": d, "url": url_de(nome)})
    for t in TIPOS:
        out[t].sort(key=lambda x: x["data"], reverse=True)
    return out


def validar_data(tipo: str, d: date) -> None:
    hoje = config.hoje_local()
    if tipo not in TIPOS:
        raise DataInvalida("tipo inválido")
    if d < DATA_MINIMA:
        raise DataInvalida(f"data anterior a {DATA_MINIMA:%d/%m/%Y}")
    if tipo == "diario" and d >= hoje:
        raise DataInvalida("o relatório diário só existe para dias já encerrados (até ontem)")
    if tipo == "semanal" and semana_de(d)[1] >= hoje:
        raise DataInvalida("a semana ainda não terminou")
    if tipo == "mensal" and (d.year, d.month) >= (hoje.year, hoje.month):
        raise DataInvalida("o mês ainda não terminou")


def gerar(tipo: str, d: date) -> str:
    """Gera o dashboard e retorna o nome do arquivo. Não envia WhatsApp."""
    validar_data(tipo, d)
    from briefing_core import collect_all_data
    from collectors import erp_mysql, perfex_crm
    from composers import html_dashboard, html_periodic_dashboard

    try:
        with FileLock(os.path.join(config.DATA_DIR, "gerar.lock")):
            if tipo == "diario":
                hoje = d + timedelta(days=1)
                data = collect_all_data(hoje)
                path = html_dashboard.generate(data, hoje=hoje)
            elif tipo == "semanal":
                seg, dom = semana_de(d)
                ref = dom + timedelta(days=1)
                data = erp_mysql.collect_range(seg, ref, tipo="semanal", hoje=ref)
                data["perfex"] = perfex_crm.collect_periodo(seg, dom)
                data["retroativo"] = True
                path = html_periodic_dashboard.generate(data, seg, dom, tipo="semanal")
            else:
                ini = date(d.year, d.month, 1)
                fim = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
                ref = fim + timedelta(days=1)
                data = erp_mysql.collect_range(ini, ref, tipo="mensal", hoje=ref)
                data["perfex"] = perfex_crm.collect_periodo(ini, fim)
                data["retroativo"] = True
                path = html_periodic_dashboard.generate(data, ini, fim, tipo="mensal")
    except LockBusy:
        raise GeracaoEmAndamento("já há uma geração em andamento; tente em instantes")
    logger.info("Relatório %s gerado sob demanda: %s", tipo, path)
    return os.path.basename(path)
```

- [ ] **Step 4: Rodar — deve passar** → `4 passed`.

- [ ] **Step 5: Commit** — `git add admin/relatorios.py tests/test_relatorios.py && git commit -m "feat(admin): catalogo de relatorios e geracao por data"`

### Task 8: `admin/app.py` + tela de Relatórios

**Files:** Create `admin/app.py`, `admin/templates/base.html`, `admin/templates/relatorios.html`, `admin/static/admin.css`; Test `tests/test_app.py`

- [ ] **Step 1: Teste**

```python
# tests/test_app.py
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
```

- [ ] **Step 2: Rodar — deve falhar** (`ModuleNotFoundError: admin.app`).

- [ ] **Step 3: Implementar `admin/app.py`**

```python
# admin/app.py
"""App administrativo: relatórios por data e mensagens agendadas.

Servido sob /admin (Blueprint) atrás do nginx, que faz a autenticação (Basic Auth).
"""
import logging
import os
import secrets
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler

from flask import (Blueprint, Flask, abort, flash, jsonify, redirect,
                   render_template, request, session, url_for)

import config
from admin import relatorios

bp = Blueprint("admin", __name__, url_prefix="/admin",
               template_folder="templates", static_folder="static", static_url_path="/static")


# ── CSRF (token na sessão; campo oculto nos formulários ou cabeçalho X-CSRF-Token) ──

def _csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@bp.before_request
def _check_csrf():
    if request.method == "POST":
        tok = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not tok or tok != session.get("csrf_token"):
            abort(400, "token CSRF inválido — recarregue a página")


@bp.app_context_processor
def _inject():
    return {"csrf_token": _csrf_token, "hoje": config.hoje_local()}


# ── Relatórios ────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return redirect(url_for("admin.relatorios_page"))


@bp.route("/relatorios")
def relatorios_page():
    return render_template("relatorios.html", lista=relatorios.listar(), tipos=relatorios.TIPOS)


@bp.route("/relatorios/gerar", methods=["POST"])
def relatorios_gerar():
    tipo = request.form.get("tipo", "")
    try:
        if tipo == "mensal" and request.form.get("mes"):
            d = date.fromisoformat(request.form["mes"] + "-01")     # <input type=month> envia YYYY-MM
        else:
            d = date.fromisoformat(request.form.get("data", ""))
    except ValueError:
        flash("Data inválida.", "erro")
        return redirect(url_for("admin.relatorios_page"))
    if tipo in relatorios.TIPOS and relatorios.existe(tipo, d) and not request.form.get("regerar"):
        return redirect(relatorios.url_de(relatorios.nome_para(tipo, d)))
    try:
        nome = relatorios.gerar(tipo, d)
    except relatorios.DataInvalida as exc:
        flash(f"Não foi possível gerar: {exc}", "erro")
        return redirect(url_for("admin.relatorios_page"))
    except relatorios.GeracaoEmAndamento as exc:
        flash(str(exc), "aviso")
        return redirect(url_for("admin.relatorios_page"))
    except Exception:
        logging.getLogger("admin").exception("Falha ao gerar relatório %s %s", tipo, d)
        flash("Erro ao gerar o relatório. Veja admin.log.", "erro")
        return redirect(url_for("admin.relatorios_page"))
    flash(f"Relatório gerado: {nome}", "ok")
    return redirect(relatorios.url_de(nome))


# ── Fábrica ───────────────────────────────────────────────────────────────────

def _setup_logging(app: Flask):
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "admin.log")
    try:
        fh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=7)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
        for name in ("admin", "admin.relatorios", "admin.agendamentos", "admin.ia", "briefing", "collectors"):
            lg = logging.getLogger(name)
            lg.setLevel(logging.INFO)
            if not any(isinstance(h, RotatingFileHandler) and h.baseFilename == fh.baseFilename for h in lg.handlers):
                lg.addHandler(fh)
    except PermissionError:
        app.logger.warning("Sem permissão para %s", log_path)


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = config.ADMIN_SECRET_KEY
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.register_blueprint(bp)
    _setup_logging(app)
    return app


app = create_app()
```
**Regra para as Tasks 12 e 13:** todas as rotas novas (`@bp.route`) e seus imports devem ser inseridos **acima** da seção `# ── Fábrica`. `app = create_app()` registra o Blueprint ao importar o módulo; qualquer `@bp.route` escrito depois dessa linha faz o Flask lançar "setup method 'route' can no longer be called". `app = create_app()` permanece a última linha do arquivo.

- [ ] **Step 4: Templates e CSS**

`admin/templates/base.html`:
```html
<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}Admin{% endblock %} — Barbearia VIP</title>
<link rel="stylesheet" href="{{ url_for('admin.static', filename='admin.css') }}">
</head><body>
<header><strong>Barbearia VIP — Admin</strong>
  <nav><a href="{{ url_for('admin.relatorios_page') }}">Relatórios</a> · <a href="#">Mensagens</a></nav>
</header>
<main>
{% with msgs = get_flashed_messages(with_categories=true) %}{% for cat, m in msgs %}<div class="flash {{ cat }}">{{ m }}</div>{% endfor %}{% endwith %}
{% block content %}{% endblock %}
</main></body></html>
```

`admin/templates/relatorios.html`:
```html
{% extends "base.html" %}{% block title %}Relatórios{% endblock %}{% block content %}
<h1>Relatórios</h1>
<form method="post" action="{{ url_for('admin.relatorios_gerar') }}" class="card" onsubmit="var b=this.querySelector('button');b.disabled=true;b.textContent='Gerando… (até 15 s)'">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <label>Tipo <select name="tipo">{% for t in tipos %}<option value="{{ t }}">{{ t }}</option>{% endfor %}</select></label>
  <label>Dia dos dados <input type="date" name="data" id="data" required max="{{ hoje.isoformat() }}"></label>
  <label>Mês (para o mensal) <input type="month" name="mes" id="mes" max="{{ hoje.strftime('%Y-%m') }}"></label>
  <label><input type="checkbox" name="regerar" value="1" onchange="if(this.checked&&!confirm('Regerar substitui o arquivo existente. Continuar?'))this.checked=false"> Regerar se já existir</label>
  <button type="submit">Abrir / Gerar</button>
  <p class="hint">Diário: escolha o dia dos dados (o arquivo leva a data do dia seguinte). Semanal: qualquer dia da semana. Mensal: qualquer dia do mês.</p>
</form>
{% for t in tipos %}
<section class="card"><h2>{{ t|capitalize }}</h2>
  {% if lista[t] %}<ul>{% for r in lista[t] %}<li><a href="{{ r.url }}" target="_blank">{{ r.data.strftime('%d/%m/%Y') }}</a> <small>{{ r.arquivo }}</small></li>{% endfor %}</ul>
  {% else %}<p class="hint">Nenhum relatório {{ t }} gerado ainda.</p>{% endif %}
</section>
{% endfor %}
{% endblock %}
```

`admin/static/admin.css`:
```css
body{font-family:system-ui,sans-serif;margin:0;background:#f7f7f8;color:#222}
header{background:#1f2937;color:#fff;padding:12px 20px;display:flex;justify-content:space-between}
header a{color:#cbd5e1}main{max-width:960px;margin:20px auto;padding:0 16px}
.card{background:#fff;border-radius:10px;padding:16px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
label{display:block;margin:8px 0}input,select,textarea{font:inherit;padding:6px}textarea{width:100%;min-height:140px}
button{font:inherit;padding:8px 14px;border:0;border-radius:6px;background:#2563eb;color:#fff;cursor:pointer}button:disabled{opacity:.6}
.hint{color:#6b7280;font-size:.9em}.flash{padding:10px;border-radius:6px;margin-bottom:12px}.flash.ok{background:#dcfce7}.flash.erro{background:#fee2e2}.flash.aviso{background:#fef9c3}
table{width:100%;border-collapse:collapse;font-size:.95em}td,th{padding:6px;border-bottom:1px solid #eee;text-align:left}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
```

- [ ] **Step 5: Rodar — deve passar** → `5 passed`.

- [ ] **Step 6: Subir localmente** — `.venv/Scripts/python -c "from admin.app import app; app.run(port=8081)"` e abrir `http://127.0.0.1:8081/admin/relatorios`. Expected: página renderiza; gerar sem `.env` local mostra "Erro ao gerar" (não um 500).

- [ ] **Step 7: Commit** — `git add admin/ tests/test_app.py && git commit -m "feat(admin): app Flask sob /admin com tela de relatorios por data"`

---

## Chunk 3: Agendamentos — modelo, próxima ocorrência, job de envio, tela

### Task 9: `admin/agendamentos.py` — `proxima_ocorrencia` (pura)

**Files:** Create `admin/agendamentos.py`; Test `tests/test_agendamentos.py`

- [ ] **Step 1: Teste**

```python
# tests/test_agendamentos.py
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
```

- [ ] **Step 2: Rodar — deve falhar.**

- [ ] **Step 3: Implementar (função pura; o resto do módulo vem na Task 10)**

```python
# admin/agendamentos.py
"""Agendamentos de mensagens: regra de recorrência (pura) e persistência SQLite."""
import calendar
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import config

TZ = ZoneInfo(config.TIMEZONE)
ESTADOS = ("ativo", "pausado", "enviando", "concluido", "cancelado")


def _no_horario(d: datetime, ref: datetime) -> datetime:
    return d.replace(hour=ref.hour, minute=ref.minute, second=0, microsecond=0)


def proxima_ocorrencia(apos: Optional[datetime], primeiro: datetime, rec: dict, fim: Optional[datetime]) -> Optional[datetime]:
    """Primeira ocorrência depois de `apos` (None = a primeira de todas, podendo ser
    o próprio `primeiro`), nunca antes de `primeiro`, respeitando `fim`.
    O horário é sempre o de `primeiro`."""
    tipo = rec.get("tipo", "nenhuma")
    if tipo == "nenhuma":
        cand = primeiro if (apos is None or primeiro > apos) else None
    else:
        # candidato inicial: o dia de `primeiro` (se apos is None) ou o dia seguinte a `apos`
        d = _no_horario(primeiro, primeiro) if apos is None else _no_horario(apos, primeiro) + timedelta(days=1)
        if apos is not None and d <= apos:
            d += timedelta(days=1)
        cand = _primeiro_valido(d, primeiro, rec)
    if cand is not None and fim is not None and cand > fim:
        return None
    return cand


def _primeiro_valido(d: datetime, primeiro: datetime, rec: dict) -> datetime:
    """Avança `d` dia a dia (ou mês a mês no mensal) até casar com a regra."""
    tipo = rec["tipo"]
    if tipo == "diaria":
        return d
    if tipo == "semanal":
        dias = sorted({int(x) for x in rec.get("dias", [])})
        if not dias:
            raise ValueError("recorrência semanal sem dias")
        for _ in range(7):
            if d.weekday() in dias:
                return d
            d += timedelta(days=1)
        raise AssertionError("inalcançável")
    if tipo == "mensal":
        alvo = rec.get("dia", 1)
        ano, mes = d.year, d.month
        for _ in range(14):
            ultimo = calendar.monthrange(ano, mes)[1]
            dia = ultimo if alvo == "ultimo" else min(int(alvo), ultimo)
            c = _no_horario(datetime(ano, mes, dia, tzinfo=TZ), primeiro)
            if c >= d:
                return c
            mes += 1
            if mes == 13:
                mes, ano = 1, ano + 1
        raise ValueError("recorrência mensal inválida")
    raise ValueError(f"tipo de recorrência desconhecido: {tipo}")
```

- [ ] **Step 4: Rodar — deve passar** → `5 passed`. Os testes são a especificação; se um caso falhar, corrija a função, não o teste.

- [ ] **Step 5: Commit** — `git add admin/agendamentos.py tests/test_agendamentos.py && git commit -m "feat(admin): regra de proxima ocorrencia (unica/diaria/semanal/mensal)"`

### Task 10: Persistência SQLite + resolução de destinos

**Files:** Modify `admin/agendamentos.py`; Test `tests/test_agendamentos_db.py`

- [ ] **Step 1: Teste**

```python
# tests/test_agendamentos_db.py
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
```

- [ ] **Step 2: Rodar — deve falhar.**

- [ ] **Step 3: Implementar (acrescentar a `admin/agendamentos.py`)**

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS agendamentos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  texto TEXT NOT NULL,
  destinos_json TEXT NOT NULL,
  primeiro_envio_iso TEXT NOT NULL,
  recorrencia_json TEXT NOT NULL,
  fim_iso TEXT,
  proximo_envio_iso TEXT,
  estado TEXT NOT NULL DEFAULT 'ativo',
  falhas_consecutivas INTEGER NOT NULL DEFAULT 0,
  reservado_em_iso TEXT,
  criado_em TEXT NOT NULL,
  atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS envios(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agendamento_id INTEGER NOT NULL,
  ocorrencia_iso TEXT NOT NULL,
  disparado_em TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  destino_nome TEXT,
  status TEXT NOT NULL,
  erro TEXT,
  UNIQUE(agendamento_id, ocorrencia_iso, chat_id)
);
CREATE INDEX IF NOT EXISTS ix_ag_estado_prox ON agendamentos(estado, proximo_envio_iso);
"""


def db_path() -> str:
    return os.path.join(config.DATA_DIR, "agendamentos.db")


def conectar(path: Optional[str] = None) -> sqlite3.Connection:
    p = path or db_path()
    con = sqlite3.connect(p, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    if p != ":memory:":
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def criar_schema(con) -> None:
    con.executescript(SCHEMA)


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def _dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s).astimezone(TZ) if s else None


def _row(r) -> dict:
    d = dict(r)
    d["destinos"] = json.loads(d.pop("destinos_json"))
    d["recorrencia"] = json.loads(d.pop("recorrencia_json"))
    d["primeiro_envio"] = _dt(d.pop("primeiro_envio_iso"))
    d["fim"] = _dt(d.pop("fim_iso"))
    d["proximo_envio"] = _dt(d.pop("proximo_envio_iso"))
    return d


def criar(con, texto, destinos, primeiro, rec, fim) -> int:
    prox = proxima_ocorrencia(None, primeiro, rec, fim)
    n = _iso(config.agora_local())
    cur = con.execute(
        "INSERT INTO agendamentos(texto,destinos_json,primeiro_envio_iso,recorrencia_json,fim_iso,"
        "proximo_envio_iso,estado,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?)",
        (texto, json.dumps(destinos), _iso(primeiro), json.dumps(rec), _iso(fim), _iso(prox),
         "ativo" if prox else "concluido", n, n))
    return cur.lastrowid


def atualizar(con, aid, texto, destinos, primeiro, rec, fim) -> None:
    prox = proxima_ocorrencia(None, primeiro, rec, fim)
    con.execute(
        "UPDATE agendamentos SET texto=?,destinos_json=?,primeiro_envio_iso=?,recorrencia_json=?,fim_iso=?,"
        "proximo_envio_iso=?,estado=?,falhas_consecutivas=0,atualizado_em=? WHERE id=?",
        (texto, json.dumps(destinos), _iso(primeiro), json.dumps(rec), _iso(fim), _iso(prox),
         "ativo" if prox else "concluido", _iso(config.agora_local()), aid))


def obter(con, aid) -> Optional[dict]:
    r = con.execute("SELECT * FROM agendamentos WHERE id=?", (aid,)).fetchone()
    return _row(r) if r else None


def listar(con, estados=("ativo", "pausado", "enviando")) -> list[dict]:
    q = ",".join("?" * len(estados))
    return [_row(r) for r in con.execute(
        f"SELECT * FROM agendamentos WHERE estado IN ({q}) ORDER BY proximo_envio_iso", estados)]


def mudar_estado(con, aid, estado) -> None:
    assert estado in ESTADOS
    # Retomar zera o contador: senao um agendamento pausado por 3 falhas pausa de novo na 1a falha
    extra = ", falhas_consecutivas=0" if estado == "ativo" else ""
    con.execute(f"UPDATE agendamentos SET estado=?{extra}, atualizado_em=? WHERE id=?",
                (estado, _iso(config.agora_local()), aid))


def reservar_vencidos(con, agora: datetime) -> list[dict]:
    """Marca como 'enviando' (atomicamente) e retorna os agendamentos vencidos."""
    con.execute("BEGIN IMMEDIATE")
    try:
        rows = con.execute(
            "SELECT * FROM agendamentos WHERE estado='ativo' AND proximo_envio_iso<=?", (_iso(agora),)).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            q = ",".join("?" * len(ids))
            con.execute(f"UPDATE agendamentos SET estado='enviando', reservado_em_iso=? WHERE id IN ({q})",
                        (_iso(agora), *ids))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return [_row(r) for r in rows]


def recuperar_presos(con, agora: datetime, minutos: int = 10) -> int:
    limite = _iso(agora - timedelta(minutes=minutos))
    return con.execute(
        "UPDATE agendamentos SET estado='ativo' WHERE estado='enviando' "
        "AND (reservado_em_iso IS NULL OR reservado_em_iso<=?)", (limite,)).rowcount


def concluir_ciclo(con, aid, proximo: Optional[datetime], sucesso: bool) -> None:
    a = obter(con, aid)
    if sucesso:
        falhas, estado = 0, ("ativo" if proximo else "concluido")
    else:
        falhas = a["falhas_consecutivas"] + 1
        estado = "pausado" if falhas >= 3 else "ativo"
        proximo = a["proximo_envio"]            # não avança
    if not sucesso and estado == "pausado":
        registrar_envio(con, aid, a["proximo_envio"], "-", "sistema", "pausado",
                        "pausado automaticamente apos 3 falhas consecutivas")
    # So atualiza se ainda esta 'enviando': um cancelar/pausar clicado durante o envio prevalece
    con.execute(
        "UPDATE agendamentos SET estado=?, proximo_envio_iso=?, falhas_consecutivas=?, reservado_em_iso=NULL, "
        "atualizado_em=? WHERE id=? AND estado='enviando'",
        (estado, _iso(proximo), falhas, _iso(config.agora_local()), aid))


def registrar_envio(con, aid, ocorrencia: datetime, chat_id, nome, status, erro=None) -> None:
    con.execute(
        "INSERT OR REPLACE INTO envios(agendamento_id,ocorrencia_iso,disparado_em,chat_id,destino_nome,status,erro)"
        " VALUES(?,?,?,?,?,?,?)",
        (aid, _iso(ocorrencia), _iso(config.agora_local()), chat_id, nome, status, erro))


def ja_enviados(con, aid, ocorrencia: datetime) -> set:
    return {r[0] for r in con.execute(
        "SELECT chat_id FROM envios WHERE agendamento_id=? AND ocorrencia_iso=? AND status='enviado'",
        (aid, _iso(ocorrencia)))}


def historico(con, limite=200) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT e.*, substr(a.texto,1,60) AS texto FROM envios e JOIN agendamentos a ON a.id=e.agendamento_id "
        "ORDER BY e.id DESC LIMIT ?", (limite,))]


def resolver_destinos(destinos: dict) -> list:
    """[(chat_id, nome)] no momento do envio, com a mesma regra do briefing."""
    out, vistos = [], set()
    grupos = config.UNIT_GROUPS or {}
    ids = list(grupos.keys()) if destinos.get("todas") else [str(u) for u in destinos.get("unidades", [])]
    for uid in ids:
        info = grupos.get(uid)
        if not info:
            continue
        chats = ([info["chat_id"]] if info.get("chat_id") else []) + [c for c in (info.get("chat_ids") or []) if c]
        for c in chats:
            if c not in vistos:
                vistos.add(c)
                out.append((c, info.get("nome", f"Unidade #{uid}")))
    if destinos.get("franqueadora"):
        for c in config.WAHA_RECIPIENTS:
            if c not in vistos:
                vistos.add(c)
                out.append((c, "Franqueadora"))
    return out
```

- [ ] **Step 4: Rodar — deve passar** → `4 passed` (+ anteriores).

- [ ] **Step 5: Commit** — `git add admin/agendamentos.py tests/test_agendamentos_db.py && git commit -m "feat(admin): persistencia SQLite dos agendamentos e resolucao de destinos"`

### Task 11: `scheduler/agendamentos_job.py` + registro no `main.py`

**Files:** Create `scheduler/__init__.py` (vazio), `scheduler/agendamentos_job.py`; Modify `main.py` (bloco do scheduler, após o job mensal); Test `tests/test_agendamentos_job.py`

- [ ] **Step 1: Teste**

```python
# tests/test_agendamentos_job.py
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
```

- [ ] **Step 2: Rodar — deve falhar.**

- [ ] **Step 3: Implementar**

```python
# scheduler/agendamentos_job.py
"""Job de 1 minuto do daily-briefing: envia as mensagens agendadas vencidas."""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import config
from admin import agendamentos as ag
from senders import waha

logger = logging.getLogger("agendamentos")
ATRASO_MAXIMO = timedelta(hours=2)
INTERVALO_ENVIO_S = 1.5


def conectar():
    con = ag.conectar()
    ag.criar_schema(con)
    return con


def processar_agendamentos(agora: Optional[datetime] = None, con=None) -> int:
    """`con` injetavel (testes); quando None, abre e fecha a propria conexao."""
    agora = agora or config.agora_local()
    propria = con is None
    if propria:
        con = conectar()
    try:
        presos = ag.recuperar_presos(con, agora)
        if presos:
            logger.warning("%d agendamento(s) presos em 'enviando' recuperados", presos)
        vencidos = ag.reservar_vencidos(con, agora)
        for a in vencidos:
            _processar_um(con, a, agora)
        if vencidos:
            logger.info("Ciclo: %d agendamento(s) processado(s)", len(vencidos))
        return len(vencidos)
    finally:
        if propria:
            con.close()


def _processar_um(con, a: dict, agora: datetime) -> None:
    aid, ocorrencia = a["id"], a["proximo_envio"]
    destinos = ag.resolver_destinos(a["destinos"])
    try:
        if agora - ocorrencia > ATRASO_MAXIMO:
            for chat, nome in destinos:
                ag.registrar_envio(con, aid, ocorrencia, chat, nome, "perdido", f"atraso > {ATRASO_MAXIMO}")
            logger.warning("Agendamento %s: ocorrência %s perdida (atraso > 2h)", aid, ocorrencia)
            prox = ag.proxima_ocorrencia(ocorrencia, a["primeiro_envio"], a["recorrencia"], a["fim"])
            ag.concluir_ciclo(con, aid, prox, sucesso=True)
            return

        feitos = ag.ja_enviados(con, aid, ocorrencia)
        algum_ok = bool(feitos)
        for chat, nome in destinos:
            if chat in feitos:
                continue
            ok = waha.send_text(chat, a["texto"])
            ag.registrar_envio(con, aid, ocorrencia, chat, nome, "enviado" if ok else "falhou",
                               None if ok else "WAHA retornou falha")
            algum_ok = algum_ok or ok
            time.sleep(INTERVALO_ENVIO_S)

        if not destinos:
            logger.warning("Agendamento %s sem destinos válidos", aid)
        sucesso = algum_ok or not destinos
        prox = ag.proxima_ocorrencia(ocorrencia, a["primeiro_envio"], a["recorrencia"], a["fim"]) if sucesso else None
        ag.concluir_ciclo(con, aid, prox, sucesso=sucesso)
        if not sucesso:
            logger.error("Agendamento %s: todos os destinos falharam", aid)
    except Exception as exc:
        logger.error("Agendamento %s: exceção no envio: %s", aid, exc, exc_info=True)
        ag.concluir_ciclo(con, aid, None, sucesso=False)
```

Em `main.py`, após o job mensal e antes do bloco do Meta Ads:
```python
    # Mensagens agendadas pelo app administrativo: verifica a cada minuto
    from apscheduler.triggers.interval import IntervalTrigger
    from scheduler.agendamentos_job import processar_agendamentos
    scheduler.add_job(
        processar_agendamentos,
        trigger=IntervalTrigger(minutes=1, timezone=config.TIMEZONE),
        id="agendamentos",
        name="Mensagens agendadas",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
```

- [ ] **Step 4: Rodar — deve passar** → `5 passed`.

- [ ] **Step 5: Commit** — `git add scheduler/ main.py tests/test_agendamentos_job.py && git commit -m "feat(scheduler): job de envio das mensagens agendadas (1 min) com recuperacao e anti-duplicidade"`

### Task 12: Tela de Mensagens (sem IA ainda)

**Files:** Modify `admin/app.py`, `admin/templates/base.html`; Create `admin/templates/mensagens.html`; Test `tests/test_app_mensagens.py`

- [ ] **Step 1: Teste**

```python
# tests/test_app_mensagens.py
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
```

- [ ] **Step 2: Rodar — deve falhar.**

- [ ] **Step 3: Rotas em `admin/app.py`** — inserir **acima de `# ── Fábrica`** (imports no topo: `from admin import agendamentos as ag`, `from senders import waha`)

```python
def _db():
    con = ag.conectar()
    ag.criar_schema(con)
    return con


def _parse_form(f):
    """Valida o formulário; retorna (campos, erros)."""
    erros = []
    texto = (f.get("texto") or "").strip()
    if not 1 <= len(texto) <= 4000:
        erros.append("O texto deve ter entre 1 e 4000 caracteres.")
    unidades = [int(u) for u in f.getlist("unidades") if str(u) in (config.UNIT_GROUPS or {})]
    destinos = {"unidades": unidades, "todas": f.get("todas") == "1", "franqueadora": f.get("franqueadora") == "1"}
    if not (unidades or destinos["todas"] or destinos["franqueadora"]):
        erros.append("Escolha ao menos um destino.")
    primeiro = None
    try:
        primeiro = datetime.combine(date.fromisoformat(f.get("data", "")),
                                    datetime.strptime(f.get("hora", ""), "%H:%M").time(), tzinfo=ag.TZ)
    except ValueError:
        erros.append("Data/hora inválida.")
    if primeiro and primeiro < config.agora_local() + timedelta(minutes=1):
        erros.append("A data/hora do primeiro envio precisa estar no futuro.")
    tipo = f.get("recorrencia", "nenhuma")
    rec = {"tipo": tipo}
    if tipo == "semanal":
        rec["dias"] = sorted({int(d) for d in f.getlist("dias") if d.isdigit() and 0 <= int(d) <= 6})
        if not rec["dias"]:
            erros.append("Marque ao menos um dia da semana.")
    elif tipo == "mensal":
        dia = (f.get("dia_mes") or "1").strip().lower()
        rec["dia"] = "ultimo" if dia == "ultimo" else (int(dia) if dia.isdigit() and 1 <= int(dia) <= 31 else None)
        if rec["dia"] is None:
            erros.append("Dia do mês inválido.")
    elif tipo not in ("nenhuma", "diaria"):
        erros.append("Repetição inválida.")
    fim = None
    if f.get("fim"):
        try:
            fim = datetime.combine(date.fromisoformat(f["fim"]), datetime.max.time().replace(microsecond=0), tzinfo=ag.TZ)
            if primeiro and fim < primeiro:
                erros.append("A data final precisa ser depois do primeiro envio.")
        except ValueError:
            erros.append("Data final inválida.")
    return {"texto": texto, "destinos": destinos, "primeiro": primeiro, "rec": rec, "fim": fim}, erros


@bp.route("/mensagens", methods=["GET", "POST"])
def mensagens_page():
    con = _db()
    if request.method == "POST":
        campos, erros = _parse_form(request.form)
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            ag.criar(con, campos["texto"], campos["destinos"], campos["primeiro"], campos["rec"], campos["fim"])
            flash("Mensagem agendada.", "ok")
            return redirect(url_for("admin.mensagens_page"))
    unidades = sorted(((int(k), v.get("nome", k)) for k, v in (config.UNIT_GROUPS or {}).items()), key=lambda x: x[1])
    return render_template("mensagens.html", unidades=unidades, proximos=ag.listar(con), historico=ag.historico(con),
                           ia_disponivel=bool(config.ANTHROPIC_API_KEY), teste_disponivel=bool(config.ADMIN_TEST_CHAT_ID),
                           form=request.form)


@bp.route("/mensagens/<int:aid>/estado", methods=["POST"])
def mensagens_estado(aid):
    estado = request.form.get("estado")
    if estado not in ("ativo", "pausado", "cancelado"):
        abort(400)
    con = _db()
    if not ag.obter(con, aid):
        abort(404)
    ag.mudar_estado(con, aid, estado)
    flash("Estado atualizado.", "ok")
    return redirect(url_for("admin.mensagens_page"))


@bp.route("/mensagens/teste", methods=["POST"])
def mensagens_teste():
    if not config.ADMIN_TEST_CHAT_ID:
        abort(400, "ADMIN_TEST_CHAT_ID não configurado")
    texto = (request.form.get("texto") or "").strip()
    if not texto:
        flash("Escreva o texto antes de testar.", "erro")
        return redirect(url_for("admin.mensagens_page"))
    ok = waha.send_text(config.ADMIN_TEST_CHAT_ID, texto)
    flash("Teste enviado para o seu número." if ok else "Falha ao enviar o teste (WAHA).", "ok" if ok else "erro")
    return redirect(url_for("admin.mensagens_page"))
```

Edição (**obrigatória**, spec §5):
```python
@bp.route("/mensagens/<int:aid>/editar", methods=["GET", "POST"])
def mensagens_editar(aid):
    con = _db()
    a = ag.obter(con, aid)
    if not a or a["estado"] in ("cancelado", "concluido"):
        abort(404)
    if request.method == "POST":
        campos, erros = _parse_form(request.form)
        if erros:
            for e in erros:
                flash(e, "erro")
        else:
            ag.atualizar(con, aid, campos["texto"], campos["destinos"], campos["primeiro"], campos["rec"], campos["fim"])
            flash("Agendamento atualizado.", "ok")
            return redirect(url_for("admin.mensagens_page"))
    unidades = sorted(((int(k), v.get("nome", k)) for k, v in (config.UNIT_GROUPS or {}).items()), key=lambda x: x[1])
    return render_template("mensagens.html", unidades=unidades, proximos=ag.listar(con), historico=ag.historico(con),
                           ia_disponivel=bool(config.ANTHROPIC_API_KEY), teste_disponivel=bool(config.ADMIN_TEST_CHAT_ID),
                           form=request.form, editando=a)
```
No template, quando `editando` existe: `action="{{ url_for('admin.mensagens_editar', aid=editando.id) }}"`, campos pré-preenchidos a partir de `editando` (texto, unidades marcadas, data/hora de `primeiro_envio`, recorrência e dias, fim) e o botão diz "Salvar alterações". Teste adicional em `tests/test_app_mensagens.py`:
```python
def test_editar(client):
    c, db, ag = client
    aid = ag.criar(db, "x", {"unidades":[61],"todas":False,"franqueadora":False}, datetime(2026,12,1,15,0,tzinfo=TZ), {"tipo":"nenhuma"}, None)
    r = c.post(f"/admin/mensagens/{aid}/editar", data={"csrf_token": _tok(c), "texto": "novo", "unidades": ["61"],
                                                     "data": "2026-12-02", "hora": "16:00", "recorrencia": "diaria"}, follow_redirects=True)
    a = ag.obter(db, aid)
    assert a["texto"] == "novo" and a["recorrencia"] == {"tipo": "diaria"} and a["proximo_envio"] == datetime(2026,12,2,16,0,tzinfo=TZ)
```
Prévia do texto (spec §5): abaixo do `textarea`, `<div id="previa" class="hint"></div>` e, no `<script>`, `texto.addEventListener('input',()=>{previa.innerHTML=texto.value.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])).replace(/\*(.+?)\*/g,'<b>$1</b>').replace(/_(.+?)_/g,'<i>$1</i>').replace(/\n/g,'<br>');})` (escapa HTML antes de aplicar negrito/itálico).

- [ ] **Step 4: Template `admin/templates/mensagens.html`** (e em `base.html` troque o link `#` por `{{ url_for('admin.mensagens_page') }}`)

```html
{% extends "base.html" %}{% block title %}Mensagens{% endblock %}{% block content %}
<h1>Mensagens agendadas</h1>
<form method="post" class="card" id="f">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <label>Texto <textarea name="texto" id="texto" maxlength="4000" required>{{ form.get('texto','') }}</textarea></label>
  <fieldset><legend>Gerar com IA</legend>
    <input name="assunto" id="assunto" placeholder="Assunto (ex.: lembrete de fechamento de caixa toda sexta)" style="width:60%">
    <select id="tom"><option>Amigável</option><option>Formal</option><option>Urgente</option></select>
    <button type="button" id="btn-ia" {% if not ia_disponivel %}disabled title="Configure ANTHROPIC_API_KEY no .env"{% endif %}>Gerar com IA</button>
    <span id="ia-status" class="hint"></span>
  </fieldset>
  <fieldset><legend>Destinos</legend>
    <label><input type="checkbox" name="todas" value="1"> Todas as unidades</label>
    <label><input type="checkbox" name="franqueadora" value="1"> Franqueadora</label>
    <div class="grid">{% for uid, nome in unidades %}<label><input type="checkbox" name="unidades" value="{{ uid }}"> {{ nome }}</label>{% endfor %}</div>
  </fieldset>
  <label>Primeiro envio <input type="date" name="data" required> <input type="time" name="hora" required value="09:00"></label>
  <label>Repetição <select name="recorrencia" id="rec"><option value="nenhuma">Nenhuma</option><option value="diaria">Diária</option><option value="semanal">Semanal</option><option value="mensal">Mensal</option></select></label>
  <div id="semanal" hidden>{% for i, n in [(0,'Seg'),(1,'Ter'),(2,'Qua'),(3,'Qui'),(4,'Sex'),(5,'Sáb'),(6,'Dom')] %}<label style="display:inline-block;margin-right:10px"><input type="checkbox" name="dias" value="{{ i }}"> {{ n }}</label>{% endfor %}</div>
  <div id="mensal" hidden><label>Dia do mês <input name="dia_mes" value="1" size="6"> (ou <code>ultimo</code>)</label></div>
  <label>Até (opcional) <input type="date" name="fim"></label>
  <button type="submit">Agendar</button>
  <button type="submit" formaction="{{ url_for('admin.mensagens_teste') }}" formnovalidate {% if not teste_disponivel %}disabled title="Configure ADMIN_TEST_CHAT_ID no .env"{% endif %}>Enviar teste para mim</button>
</form>
<section class="card"><h2>Próximos envios</h2>
<table><tr><th>Próximo</th><th>Texto</th><th>Destinos</th><th>Repetição</th><th>Estado</th><th></th></tr>
{% for a in proximos %}<tr>
<td>{{ a.proximo_envio.strftime('%d/%m/%Y %H:%M') if a.proximo_envio else '—' }}</td><td>{{ a.texto[:60] }}</td>
<td>{% if a.destinos.todas %}todas{% else %}{{ a.destinos.unidades|length }} unid.{% endif %}{% if a.destinos.franqueadora %} + franqueadora{% endif %}</td>
<td>{{ a.recorrencia.tipo }}</td><td>{{ a.estado }}</td>
<td><form method="post" action="{{ url_for('admin.mensagens_estado', aid=a.id) }}" style="display:inline"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
{% if a.estado == 'enviando' %}<em>enviando…</em>{% else %}
{% if a.estado == 'ativo' %}<button name="estado" value="pausado">Pausar</button>{% elif a.estado == 'pausado' %}<button name="estado" value="ativo">Retomar</button>{% endif %}
<a href="{{ url_for('admin.mensagens_editar', aid=a.id) }}">Editar</a>
<button name="estado" value="cancelado" onclick="return confirm('Cancelar este agendamento?')">Cancelar</button>{% endif %}</form></td>
</tr>{% endfor %}</table></section>
<section class="card"><h2>Histórico</h2>
<table><tr><th>Quando</th><th>Destino</th><th>Status</th><th>Texto</th><th>Erro</th></tr>
{% for h in historico %}<tr><td>{{ h.disparado_em[:16].replace('T',' ') }}</td><td>{{ h.destino_nome }}</td><td>{{ h.status }}</td><td>{{ h.texto }}</td><td>{{ h.erro or '' }}</td></tr>{% endfor %}</table></section>
<script>
const rec=document.getElementById('rec');
function sync(){document.getElementById('semanal').hidden=rec.value!=='semanal';document.getElementById('mensal').hidden=rec.value!=='mensal';}
rec.addEventListener('change',sync);sync();
const bi=document.getElementById('btn-ia');
if(bi){bi.addEventListener('click',async()=>{const s=document.getElementById('ia-status');bi.disabled=true;s.textContent='Gerando…';
try{const r=await fetch('{{ url_for('admin.mensagens_ia') }}',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'{{ csrf_token() }}'},
body:JSON.stringify({assunto:document.getElementById('assunto').value,tom:document.getElementById('tom').value})});
const j=await r.json();if(r.ok){document.getElementById('texto').value=j.texto;s.textContent='Pronto — revise antes de agendar.';}else{s.textContent=j.erro||'Falha ao gerar.';}}
catch(e){s.textContent='Sem resposta do servidor.';}finally{bi.disabled=false;}});}
</script>
{% endblock %}
```
Até a Task 13 existir, `url_for('admin.mensagens_ia')` quebra o template: na Task 12, registre uma rota provisória `@bp.route("/mensagens/ia", methods=["POST"]) def mensagens_ia(): return jsonify({"erro": "IA ainda não disponível"}), 503` — a Task 13 a substitui.

- [ ] **Step 5: Rodar — deve passar** → `3 passed`; suíte completa verde.

- [ ] **Step 6: Commit** — `git add admin/ tests/test_app_mensagens.py && git commit -m "feat(admin): tela de mensagens agendadas (agendar, pausar, cancelar, historico, teste)"`

---

## Chunk 4: IA, deploy e verificação

### Task 13: `admin/ia.py` + rota `/mensagens/ia`

**Files:** Create `admin/ia.py`, `admin/prompts/mensagem_sistema.txt`; Modify `admin/app.py`; Test `tests/test_ia.py`

- [ ] **Step 1: Teste (cliente Anthropic substituído por fake)**

```python
# tests/test_ia.py
import pytest


class _Blk:
    type = "text"
    def __init__(self, t): self.text = t


class _Resp:
    def __init__(self, text, stop="end_turn"):
        self.content = [_Blk(text)]; self.stop_reason = stop


def _fake_client(monkeypatch, resposta, capt=None):
    from admin import ia
    class Msgs:
        def create(self, **kw):
            if capt is not None: capt.update(kw)
            return resposta
    class Client:
        beta = type("B", (), {"messages": Msgs()})()
        def with_options(self, **kw): return self
    monkeypatch.setattr(ia, "_client", lambda: Client())


def test_sem_chave_levanta(monkeypatch):
    import config
    from admin import ia
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    with pytest.raises(ia.IAIndisponivel):
        ia.gerar_mensagem("teste", "Amigável")


def test_gera_texto(monkeypatch):
    import config
    from admin import ia
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    capt = {}
    _fake_client(monkeypatch, _Resp("  Olá *time*! Lembrete.  "), capt)
    assert ia.gerar_mensagem("lembrete de caixa", "Formal") == "Olá *time*! Lembrete."
    assert capt["model"] == "claude-opus-5-5" and capt["output_config"] == {"effort": "low"}
    assert capt["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in capt["betas"]
    assert "Assunto: lembrete de caixa" in capt["messages"][0]["content"] and "Tom: Formal" in capt["messages"][0]["content"]


def test_recusa_vira_erro_amigavel(monkeypatch):
    import config
    from admin import ia
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    _fake_client(monkeypatch, _Resp("", stop="refusal"))
    with pytest.raises(ia.IAErro, match="não conseguiu"):
        ia.gerar_mensagem("x", "Amigável")
```

- [ ] **Step 2: Rodar — deve falhar.**

- [ ] **Step 3: Implementar**

`admin/prompts/mensagem_sistema.txt`:
```
Você escreve mensagens curtas de WhatsApp para a rede de franquias Barbearia VIP. O público são os franqueados e as equipes das unidades.
Regras:
- Português do Brasil, direto e cordial; o tom pedido (Amigável, Formal ou Urgente) define o registro.
- Formatação do WhatsApp: *negrito* para o ponto principal; emojis com moderação (no máximo 2).
- Curta: até cerca de 600 caracteres, em 1 a 3 parágrafos.
- Nunca invente datas, valores, nomes de pessoas ou unidades que não estejam no assunto. Se faltar um dado essencial, deixe um marcador entre colchetes, ex.: [data].
- Responda SOMENTE com o texto da mensagem, sem título, sem explicações, sem aspas.
```

`admin/ia.py`:
```python
"""Geração de mensagem com a API da Anthropic (SDK oficial)."""
import logging
import os

import config

logger = logging.getLogger("admin.ia")
MODELO = "claude-opus-5-5"
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "mensagem_sistema.txt")
TONS = ("Amigável", "Formal", "Urgente")


class IAIndisponivel(RuntimeError):
    """Sem chave configurada."""


class IAErro(RuntimeError):
    """Falha ao gerar; a mensagem é segura para mostrar ao usuário."""


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _system_prompt() -> str:
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        return f.read().strip()


def gerar_mensagem(assunto: str, tom: str) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise IAIndisponivel("ANTHROPIC_API_KEY não configurada")
    assunto = (assunto or "").strip()
    if not assunto:
        raise IAErro("Informe o assunto.")
    if tom not in TONS:
        tom = TONS[0]
    import anthropic
    try:
        resp = _client().with_options(timeout=30.0, max_retries=1).beta.messages.create(
            model=MODELO,
            max_tokens=1024,
            output_config={"effort": "low"},
            system=_system_prompt(),
            messages=[{"role": "user", "content": f"Assunto: {assunto}\nTom: {tom}"}],
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        raise IAErro("Chave da Anthropic inválida. Confira ANTHROPIC_API_KEY no .env.")
    except anthropic.RateLimitError:
        raise IAErro("Limite de uso da IA atingido. Tente de novo em instantes.")
    except anthropic.APIStatusError as exc:
        logger.error("Anthropic status %s: %s", exc.status_code, exc.message)
        raise IAErro("Serviço de IA indisponível no momento." if exc.status_code >= 500 else f"Erro da IA: {exc.message}")
    except (anthropic.APITimeoutError, anthropic.APIConnectionError):
        raise IAErro("Sem resposta da IA (tempo esgotado). Tente de novo.")
    if resp.stop_reason == "refusal":
        raise IAErro("A IA não conseguiu gerar uma mensagem para esse assunto. Reformule o pedido.")
    texto = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()
    if not texto:
        raise IAErro("A IA retornou vazio. Tente de novo.")
    return texto
```

Rota definitiva em `admin/app.py` (substitui a provisória da Task 12; fica **acima de `# ── Fábrica`**, `from admin import ia` no topo):
```python
from admin import ia


@bp.route("/mensagens/ia", methods=["POST"])
def mensagens_ia():
    payload = request.get_json(silent=True) or {}
    try:
        texto = ia.gerar_mensagem(payload.get("assunto", ""), payload.get("tom", ""))
    except ia.IAIndisponivel:
        return jsonify({"erro": "IA não configurada (ANTHROPIC_API_KEY)."}), 503
    except ia.IAErro as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception:
        logging.getLogger("admin.ia").exception("Falha inesperada na IA")
        return jsonify({"erro": "Falha inesperada ao gerar."}), 500
    return jsonify({"texto": texto})
```

Teste de tela (acrescente a `tests/test_app_mensagens.py`):
```python
def test_botao_ia_desabilitado_sem_chave(client):
    c, db, ag = client
    html = c.get("/admin/mensagens").get_data(as_text=True)
    assert 'id="btn-ia" disabled' in html
```

- [ ] **Step 4: Rodar — deve passar** → `3 passed` em `test_ia.py` + o novo em `test_app_mensagens.py`; suíte completa verde.

- [ ] **Step 5: Teste real único (opcional, < US$0,01)** — com `ANTHROPIC_API_KEY` no ambiente local: `.venv/Scripts/python -c "from admin import ia; print(ia.gerar_mensagem('lembrete de fechamento de caixa toda sexta', 'Amigável'))"`.

- [ ] **Step 6: Commit** — `git add admin/ia.py admin/prompts admin/app.py tests/test_ia.py && git commit -m "feat(admin): gerar mensagem com IA (Anthropic SDK, opus-5-5, fallback de recusa)"`

### Task 14: Deploy — service, snippet do nginx, `deploy.sh`, `setup.sh`

**Files:** Create `deploy/daily-admin.service`, `deploy/nginx-admin.conf`; Modify `deploy/deploy.sh`, `deploy/setup.sh`, `deploy/nginx.conf`, `README.md`

- [ ] **Step 1: `deploy/daily-admin.service`**

```ini
[Unit]
Description=Daily Briefing — Área administrativa (Flask)
After=network.target

[Service]
Type=simple
User=briefing
Group=briefing
WorkingDirectory=/opt/barbearia-daily
# 1 worker + threads: um unico processo escreve/rotaciona admin.log (2 workers
# rotacionando o mesmo arquivo corrompem o log). Trafego interno, baixo.
ExecStart=/opt/barbearia-daily/.venv/bin/gunicorn -w 1 --threads 4 -b 127.0.0.1:8081 --timeout 120 admin.app:app
Restart=on-failure
RestartSec=10
EnvironmentFile=/opt/barbearia-daily/.env
# Saida do gunicorn vai ao journal; o app escreve admin.log sozinho (RotatingFileHandler)
StandardOutput=journal
StandardError=journal
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: `deploy/nginx-admin.conf`** (snippet; incluído DENTRO do bloco `server` 443)

```nginx
# Área administrativa (Flask em 127.0.0.1:8081). Incluir dentro do bloco server:
#   include snippets/daily-admin.conf;
# Sem barra final no proxy_pass: o prefixo /admin/ é preservado (o Flask roteia sob /admin).
# "^~": prefixo com prioridade sobre as locations regex do site (senao a regra
# "~* \.(css|js|...)$" do nginx.conf capturaria /admin/static/admin.css -> 404)
location ^~ /admin/ {
    proxy_pass http://127.0.0.1:8081;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_read_timeout 130s;
}
location = /admin { return 302 /admin/; }
location = / { return 302 /admin/relatorios; }
```

Em `deploy/nginx.conf` (instalações novas), dentro do `server`, após as diretivas `auth_basic`: `include snippets/daily-admin.conf;`.

- [ ] **Step 3: `deploy/deploy.sh`** — insira o bloco **3b ANTES** do bloco `# 3. Atualiza config do NGINX se mudou` (o snippet precisa existir antes de um eventual `nginx.conf` com `include`), e os blocos 4c/4b depois dele:

```bash
# 3b. Snippet do nginx da área administrativa (arquivo próprio; nunca toca no do Certbot)
SNIPPET_SRC="$APP_DIR/deploy/nginx-admin.conf"
SNIPPET_DST="/etc/nginx/snippets/daily-admin.conf"
if [[ ! -f "$SNIPPET_DST" ]] || ! cmp -s "$SNIPPET_SRC" "$SNIPPET_DST"; then
    info "Snippet do nginx (/admin) mudou — aplicando..."
    mkdir -p /etc/nginx/snippets
    [[ -f "$SNIPPET_DST" ]] && cp "$SNIPPET_DST" "$SNIPPET_DST.bak"
    cp "$SNIPPET_SRC" "$SNIPPET_DST"
    if nginx -t; then
        systemctl reload nginx
    else
        warn "nginx -t falhou com o snippet novo — restaurando o anterior."
        if [[ -f "$SNIPPET_DST.bak" ]]; then cp "$SNIPPET_DST.bak" "$SNIPPET_DST"; else rm -f "$SNIPPET_DST"; fi
        nginx -t && systemctl reload nginx || true
    fi
fi
if ! grep -q "snippets/daily-admin.conf" /etc/nginx/sites-available/daily-briefing 2>/dev/null; then
    warn "A config ativa do nginx ainda NÃO inclui o snippet do /admin. Uma única vez, adicione dentro do bloco server (443):"
    warn "    include snippets/daily-admin.conf;"
    warn "  e rode: nginx -t && systemctl reload nginx"
fi

# 4c. Segredo do app administrativo (sessao/CSRF): gera se ausente ou vazio
if ! grep -qE '^ADMIN_SECRET_KEY=.+' "$APP_DIR/.env"; then
    info "Gerando ADMIN_SECRET_KEY no .env..."
    sed -i '/^ADMIN_SECRET_KEY=/d' "$APP_DIR/.env"
    echo "ADMIN_SECRET_KEY=$(openssl rand -hex 32)" >> "$APP_DIR/.env"
fi

# 4b. Serviço da área administrativa (instala na primeira vez, atualiza se mudou)
ADMIN_UNIT_SRC="$APP_DIR/deploy/daily-admin.service"
ADMIN_UNIT_DST="/etc/systemd/system/daily-admin.service"
if [[ ! -f "$ADMIN_UNIT_DST" ]] || ! cmp -s "$ADMIN_UNIT_SRC" "$ADMIN_UNIT_DST"; then
    info "Instalando/atualizando daily-admin.service..."
    cp "$ADMIN_UNIT_SRC" "$ADMIN_UNIT_DST"
    systemctl daemon-reload
    systemctl enable daily-admin >/dev/null 2>&1 || true
fi
```

Substitua o passo 5 (`systemctl restart "$SERVICE"` + verificação) por:
```bash
# 5. Reinicia os serviços
for svc in "$SERVICE" daily-admin; do
    info "Reiniciando $svc..."
    systemctl restart "$svc"
done
sleep 3
ok=1
for svc in "$SERVICE" daily-admin; do
    if systemctl is-active --quiet "$svc"; then info "$svc ativo."; else warn "$svc NÃO está ativo — journalctl -u $svc -n 30"; ok=0; fi
done
if [[ $ok -eq 1 ]]; then info "Deploy concluído com sucesso."; else exit 1; fi
```

(O passo 2 já instala `requirements.txt` quando ele muda — este deploy muda, então `flask`/`gunicorn`/`anthropic` entram.)

- [ ] **Step 4: `deploy/setup.sh`** — após criar o `.env` (passo 5):
```bash
if ! grep -q '^ADMIN_SECRET_KEY=.\+' "$APP_DIR/.env"; then
    if grep -q '^ADMIN_SECRET_KEY=' "$APP_DIR/.env"; then
        sed -i "s|^ADMIN_SECRET_KEY=.*|ADMIN_SECRET_KEY=$(openssl rand -hex 32)|" "$APP_DIR/.env"
    else
        echo "ADMIN_SECRET_KEY=$(openssl rand -hex 32)" >> "$APP_DIR/.env"
    fi
fi
```
No passo do NGINX, antes de `nginx -t`: `mkdir -p /etc/nginx/snippets && cp "$APP_DIR/deploy/nginx-admin.conf" /etc/nginx/snippets/daily-admin.conf`.
No passo do systemd: copie também `daily-admin.service`; `systemctl enable daily-briefing daily-admin && systemctl start daily-briefing daily-admin`.

- [ ] **Step 5: Validar** — `bash -n deploy/deploy.sh && bash -n deploy/setup.sh && echo OK` → `OK`.

- [ ] **Step 6: README** — seção "Área administrativa (/admin)": o que é, variáveis novas do `.env`, o passo manual único do `include`, logs (`tail -f admin.log` para o app; `journalctl -u daily-admin -f` para o gunicorn), e que `data/agendamentos.db` é o único arquivo a incluir em backup.

- [ ] **Step 7: Commit** — `git add deploy/ README.md && git commit -m "feat(deploy): servico daily-admin, snippet nginx /admin, deploy.sh e setup.sh atualizados"`

### Task 15: Verificação de ponta a ponta (`bvip`, depois produção)

**Pré-requisitos (do usuário):** `.env` com `ANTHROPIC_API_KEY`, `ADMIN_TEST_CHAT_ID`, `ADMIN_SECRET_KEY`; HTTPS de produção recuperado.

- [ ] **Step 1: Deploy no `bvip`** — `sudo bash deploy/deploy.sh`. Expected: dois serviços ativos; aviso do `include` impresso.
- [ ] **Step 2: Include (uma vez)** — no bloco `server` 443 do arquivo do Certbot, após `auth_basic_user_file`, adicione `include snippets/daily-admin.conf;`; `nginx -t && systemctl reload nginx`.
- [ ] **Step 3: Relatórios** — `https://<host>/admin/relatorios` pede login; gerar o diário de ontem−3; abrir; conferir "Gerado às" com hora real e a nota de Google Reviews retroativo.
- [ ] **Step 4: Mensagens** — gerar texto com IA; "Enviar teste para mim" chega; agendar para +2 min na unidade de teste e ver `enviado` no histórico; agendar recorrente e pausar/retomar/cancelar.
- [ ] **Step 5: Logs** — `tail -n 50 admin.log`; `grep "Ciclo:" daily.log | tail` mostra o job.
- [ ] **Step 6: Produção** — passos 1–2 no `barbeariavip`; conferir que o briefing das 8h do dia seguinte sai inalterado.
- [ ] **Step 7: Memória do projeto** — registrar em `project_daily_briefing.md`: serviço `daily-admin` (8081), `data/agendamentos.db`, variáveis novas, passo manual do `include`.
