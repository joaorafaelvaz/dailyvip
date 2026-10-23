# Área administrativa: relatórios por data e mensagens agendadas — Design

Data: 2026-10-23 · Status: aprovado pelo usuário (seções 1–4) · Abordagem: A (mini app web no mesmo servidor)

## 1. Objetivo

Dar à franqueadora, no mesmo endereço e login já existentes (`https://status.franquiabv.com.br`, HTTP Basic Auth no nginx), duas capacidades:

1. **Relatórios por data** — listar os dashboards já gerados em `output/` e, para datas sem relatório, gerá-lo sob demanda.
2. **Mensagens agendadas** — escrever uma mensagem (ou gerá-la com IA a partir de um assunto), escolher unidades, data/hora e repetição; acompanhar próximos envios e histórico.

Fora de escopo (projeto separado, já decidido): login individual por franqueado com escopo por unidade; dashboards por unidade.

## 2. Arquitetura

```
navegador ──HTTPS+BasicAuth──▶ nginx ──/admin/──▶ gunicorn/Flask (daily-admin, 127.0.0.1:8081)
                                  │                      │ lê/escreve
                                  └── /*.html (output/)  ▼
                                                  data/agendamentos.db (SQLite)
                                                         ▲ lê (job a cada minuto)
                                   daily-briefing (main.py, APScheduler) ── WAHA ──▶ WhatsApp
```

- **`daily-admin`**: serviço systemd novo, usuário `briefing`, mesmo `.env`, `gunicorn -b 127.0.0.1:8081 admin.app:app`. Só o nginx o alcança.
- **`daily-briefing`**: ganha um job `processar_agendamentos` a cada minuto. É o único que envia WhatsApp (reaproveita `senders/waha.py`, `config.UNIT_GROUPS`, fuso `config.TIMEZONE`).
- **nginx**: `location /admin/ { proxy_pass http://127.0.0.1:8081/; }` + `location = / { return 302 /admin/relatorios; }` num **snippet** (`deploy/nginx-admin.conf` → `/etc/nginx/snippets/daily-admin.conf`). O arquivo gerenciado pelo Certbot recebe **uma** linha `include snippets/daily-admin.conf;` dentro do bloco `server` de 443, aplicada manualmente uma vez. `deploy.sh` copia o snippet e recarrega o nginx quando ele mudar; nunca toca no arquivo do Certbot.
- Auth: a diretiva `auth_basic` já está no nível do `server`, logo cobre `/admin/`. O app não implementa login próprio.

## 3. Módulos novos

```
admin/
  app.py              # Flask: rotas, CSRF, flash; create_app()
  relatorios.py       # catálogo de output/ (parse de nomes) + mapeamento data↔arquivo + geração sob demanda (com trava)
  agendamentos.py     # modelo SQLite (CRUD) + cálculo de próxima ocorrência (puro, testável)
  ia.py               # geração de texto via SDK anthropic
  prompts/mensagem_sistema.txt  # system prompt editável
  templates/{base,relatorios,mensagens}.html
  static/admin.css
scheduler/agendamentos_job.py   # usado por main.py: envia o que venceu
tests/test_agendamentos.py, tests/test_relatorios.py, tests/test_app.py
deploy/daily-admin.service, deploy/nginx-admin.conf
```

Refatoração necessária no código existente: coletores diários aceitam **data de referência** (`hoje: date | None = None`, padrão `date.today()`): `erp_mysql.collect_all(hoje)`, `get_media_historica`, `get_faturamento_ontem`, `get_meta_mensal`, `get_agenda_ontem`, `get_agenda_hoje`, `get_profissionais_ontem`, `get_clientes_sem_retorno`, `get_barbeiros_ausentes`, `get_aniversarios_hoje`; `perfex_crm.collect_all(hoje)` filtra "novos" pelo dia `hoje-1`; `html_dashboard.generate(data, hoje)` usa `hoje` no nome do arquivo e no cabeçalho. `main.collect_all_data(hoje)` repassa. O briefing das 8h chama sem argumento e não muda.

## 4. Relatórios por data (`/admin/relatorios`)

**Catálogo** (`relatorios.listar()`): varre `config.OUTPUT_DIR` e interpreta:

| Arquivo | Tipo | Chave de data (o que o usuário escolhe) |
|---|---|---|
| `briefing-DD-MM-YYYY.html` | diário | **dia dos dados = data do arquivo − 1** |
| `briefing-semanal-DD-MM-YYYY.html` | semanal | semana seg–dom que termina em DD-MM-YYYY (qualquer dia da semana resolve para ela) |
| `briefing-mensal-MM-YYYY.html` | mensal | mês |

**Tela:** seletor de tipo + `<input type=date>` (ou `type=month` no mensal) + lista dos existentes (mais recentes primeiro, com link). Ao escolher: existe → link **Abrir** (URL = `DASHBOARD_BASE_URL/<arquivo>`); não existe → botão **Gerar**; existe → também **Regerar** (confirmação).

**Geração** (`relatorios.gerar(tipo, data)`):
- diário: `hoje = dia + 1`; `collect_all_data(hoje)` → `html_dashboard.generate(data, hoje)`. Google Reviews: coletor pulado quando `hoje != date.today()`; template mostra "indisponível para datas retroativas".
- semanal: `erp_mysql.collect_range(seg, dom+1, "semanal")` + `perfex_crm.collect_periodo(seg, dom)` → `html_periodic_dashboard.generate(..., "semanal")`.
- mensal: idem com o mês.
- Trava: `fcntl.flock` em `data/gerar.lock`; se ocupado, responde "já há uma geração em andamento". Limite: não gera datas futuras nem anteriores a 2024-01-01.
- Síncrono na requisição (5–15 s); botão mostra spinner e desabilita.
- Não envia WhatsApp.

## 5. Mensagens agendadas (`/admin/mensagens`)

**Modelo (SQLite, `data/agendamentos.db`, WAL):**

```
agendamentos(id, texto, destinos_json, primeiro_envio_iso, recorrencia_json, fim_iso NULL,
             proximo_envio_iso, estado[ativo|pausado|enviando|concluido|cancelado],
             falhas_consecutivas, criado_em, atualizado_em)
envios(id, agendamento_id, disparado_em, chat_id, destino_nome, status[enviado|falhou|perdido], erro NULL)
```

- `destinos_json`: `{"unidades":[61,63], "todas":false, "franqueadora":false}`. Os `chat_id` são resolvidos **no envio** via `config.UNIT_GROUPS` (string + lista, mesma regra do briefing) e `config.WAHA_RECIPIENTS`.
- `recorrencia_json`: `{"tipo":"nenhuma"}` | `{"tipo":"diaria"}` | `{"tipo":"semanal","dias":[0..6]}` (0=segunda) | `{"tipo":"mensal","dia":1..31|"ultimo"}`.

**Próxima ocorrência** (`agendamentos.proxima_ocorrencia(apos, primeiro_envio, recorrencia, fim)` — função pura): sempre em `America/Sao_Paulo`, mantém o horário de `primeiro_envio`; mensal com dia > dias do mês ou "ultimo" usa o último dia; retorna `None` se passou de `fim` ou se `tipo == nenhuma` e já disparou.

**Job (a cada minuto, em `daily-briefing`):**
1. `SELECT ... WHERE estado='ativo' AND proximo_envio_iso <= agora` (uma transação; marca `estado='enviando'` antes de sair — impede duplicidade entre ciclos).
2. Se `agora - proximo_envio > 2h` → registra `envios.status='perdido'` por destino, **não envia**.
3. Senão envia a cada `chat_id` com `waha.send_text`, `time.sleep(1.5)` entre eles, grava `envios` por destino.
4. Calcula a próxima; `None` → `estado='concluido'`; senão `estado='ativo'`, `proximo_envio_iso` atualizado.
5. Qualquer exceção: log + estado volta a `ativo` (sem avançar a data) para tentar no próximo ciclo; após 3 falhas consecutivas do mesmo agendamento (`falhas_consecutivas`), pausa e registra.

**Tela:** formulário (texto com prévia, assunto+tom+**Gerar com IA**, destinos, data/hora, recorrência, "até"), botões **Agendar** e **Enviar teste para mim** (`ADMIN_TEST_CHAT_ID` do `.env`; envio imediato só para ele). Lista *Próximos envios* (pausar/retomar/editar/cancelar) e *Histórico* (últimos 200 envios, status por destino).

**Validação:** texto 1–4000 chars; ≥1 destino válido; `primeiro_envio` no futuro (≥ agora+1 min); semanal exige ≥1 dia; mensal exige dia 1–31 ou "ultimo"; `fim` ≥ `primeiro_envio`.

## 6. Geração com IA (`admin/ia.py`)

- SDK oficial `anthropic` (1.x). `client.beta.messages.create(model="claude-opus-5-5", max_tokens=1024, output_config={"effort":"low"}, system=<prompts/mensagem_sistema.txt>, messages=[{"role":"user","content": f"Assunto: {assunto}\nTom: {tom}"}], betas=["server-side-fallback-2026-07-01"], fallbacks="default")`, timeout 30 s via `with_options`.
- Fallback de recusa ativado (acima). Verificar `stop_reason == "refusal"` → mensagem "a IA não conseguiu gerar para esse assunto".
- Resposta: primeiro bloco `text`, trimado, vai para a caixa de texto (editável). Nunca é agendada automaticamente.
- Erros mapeados (cadeia específica→genérica): `AuthenticationError` (chave inválida), `RateLimitError` (tente de novo em instantes), `APIStatusError>=500` (indisponível), `APITimeoutError`/`APIConnectionError` (sem resposta). Sem `ANTHROPIC_API_KEY`: botão desabilitado com aviso.
- Custo estimado: <US$0,01 por geração.
- System prompt (arquivo): contexto Barbearia VIP, público (franqueados/equipes), pt-BR, formatação WhatsApp (`*negrito*`, emojis com moderação), curto (≤ ~600 chars), não inventar datas/valores/nomes ausentes do assunto, responder só com a mensagem pronta.

## 7. Configuração

`.env` (novas): `ANTHROPIC_API_KEY`, `ADMIN_TEST_CHAT_ID` (opcional), `ADMIN_PORT=8081` (opcional), `ADMIN_SECRET_KEY` (CSRF/sessão; `setup.sh` gera se ausente). `requirements.txt`: `flask`, `gunicorn`, `anthropic`. `.gitignore`: `data/`.

`deploy/daily-admin.service`: igual ao `daily-briefing.service` com `ExecStart=.venv/bin/gunicorn -w 2 -b 127.0.0.1:8081 --timeout 120 admin.app:app` (timeout alto por causa da geração síncrona). `setup.sh` instala/habilita; `deploy.sh` reinicia os dois serviços e copia o snippet do nginx.

## 8. Erros e observabilidade

- App: exceções viram `flash` com texto humano; stack trace só em `admin.log` (RotatingFileHandler, 5 MB × 7).
- Job: cada ciclo loga quantos agendamentos processou; falhas por destino ficam em `envios.erro`.
- Nada sensível em log (chave, texto completo das mensagens só no banco).

## 9. Testes

- `test_agendamentos.py`: próxima ocorrência (diária/semanal multi-dia/mensal 31→30/"ultimo"/fim/única), regra das 2 h, marcação `enviando` evita duplicidade (banco em memória).
- `test_relatorios.py`: parse dos 3 padrões de nome, data↔arquivo (diário −1 dia), resolução de semana/mês, rejeição de datas inválidas.
- `test_app.py`: Flask test client — rotas respondem, CSRF obrigatório, validações do formulário, botão IA desabilitado sem chave; WAHA/ERP/Anthropic substituídos por fakes.
- Manual no `bvip`: subir `daily-admin`, gerar um relatório diário de data passada, agendar um teste para `ADMIN_TEST_CHAT_ID` 2 min à frente e ver chegar; depois produção.

## 10. Decisões registradas

- Única mensagem para todos os destinos (sem personalização por unidade).
- Destino "Franqueadora" disponível como opção.
- Atraso tolerado: 2 h; além disso, "perdido".
- Horário livre (qualquer hora, inclusive várias por dia), independente do briefing das 8h.
