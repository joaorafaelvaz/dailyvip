# Daily Briefing — Barbearia VIP

Envia automaticamente às **8h** um briefing consolidado via WhatsApp e gera um dashboard HTML acessível em **https://status.franquiabv.com.br**.

## Stack

- **Python 3.11+** — APScheduler, PyMySQL, Jinja2, Requests
- **Fontes:** ERP MySQL · Perfex CRM · SatisfyCAM · Google Reviews · Meta Ads
- **Saída:** WhatsApp via WAHA · Dashboard HTML estático
- **Servidor:** NGINX + Let's Encrypt em `72.61.44.166`

## Estrutura

```
daily/
├── main.py                    # Entry point + scheduler
├── config.py                  # Variáveis de ambiente
├── requirements.txt
├── .env.example               # Template de configuração
├── collectors/                # Coletores de dados (ERP, CRM, CAM, Google, Meta Ads)
├── composers/                 # Geração do HTML e mensagem WhatsApp
├── config/
│   ├── unit_groups.json       # Unidade → grupo WhatsApp do franqueado
│   └── meta_ads_accounts.json # Conta de anúncios Meta → destinatários
├── senders/                   # Cliente WAHA
├── templates/                 # Template Jinja2 do dashboard
├── admin/                     # Área administrativa (Flask): relatórios por data + mensagens agendadas
├── scheduler/                 # Job de envio das mensagens agendadas (roda no daily-briefing)
├── output/                    # HTMLs gerados (não versionados)
├── data/                      # agendamentos.db (SQLite, não versionado)
└── deploy/
    ├── nginx.conf             # Config NGINX para status.franquiabv.com.br
    ├── nginx-admin.conf       # Snippet NGINX do /admin (proxy para o Flask)
    ├── daily-briefing.service # Serviço systemd do briefing
    ├── daily-admin.service    # Serviço systemd da área administrativa (gunicorn :8081)
    ├── setup.sh               # Instalação inicial no servidor
    ├── deploy.sh              # Atualização (git pull + restart)
    └── init-repo.sh           # Inicializa o repositório no GitHub (uma vez)
```

## Instalação no servidor

```bash
# No servidor 72.61.44.166 (como root):
git clone https://github.com/joaorafaelvaz/dailyvip.git /opt/barbearia-daily
bash /opt/barbearia-daily/deploy/setup.sh
```

O script faz automaticamente:
1. Instala dependências do sistema e Python
2. Cria virtualenv e instala pacotes
3. Configura NGINX para `status.franquiabv.com.br`
4. Obtém certificado SSL via Certbot
5. Registra e inicia o serviço systemd

Após o setup, edite o `.env`:
```bash
nano /opt/barbearia-daily/.env
```

## Atualizar no servidor

```bash
sudo bash /opt/barbearia-daily/deploy/deploy.sh
```

## Uso local / testes

```bash
cp .env.example .env      # edite com suas credenciais
python -m venv .venv
.venv/bin/pip install -r requirements.txt

python main.py --dry      # coleta + gera HTML, sem enviar WhatsApp
python main.py --test     # coleta + gera HTML + envia WhatsApp
python main.py            # modo produção (cron às 8h)

python main.py --dry-meta                          # relatórios Meta Ads no terminal
python main.py --test-meta                         # envia relatórios Meta Ads agora
python main.py --test-meta --meta-account act_123  # envia só o de uma conta
python main.py --test-meta --meta-to 5547999999999@c.us  # envia tudo para esse número (teste)
```

## Área administrativa (/admin)

Sob o mesmo login do dashboard (Basic Auth do NGINX), em **https://status.franquiabv.com.br/admin/**:

- **/admin/relatorios** — lista os dashboards já gerados e gera o de qualquer data (diário, semanal, mensal) sob demanda.
- **/admin/mensagens** — agenda mensagens de WhatsApp para unidades/franqueadora (envio único ou recorrente),
  com texto livre ou gerado por IA. O envio é feito pelo serviço `daily-briefing` (job de 1 min).

É um app Flask servido pelo gunicorn em `127.0.0.1:8081` (serviço `daily-admin`); o NGINX faz o proxy
de `/admin/` via o snippet `/etc/nginx/snippets/daily-admin.conf` (origem: `deploy/nginx-admin.conf`).

Variáveis novas no `.env`:

| Variável | Uso |
|---|---|
| `ANTHROPIC_API_KEY` | Opcional. Sem ela o botão "Gerar com IA" fica desabilitado. |
| `ADMIN_TEST_CHAT_ID` | Opcional. Chat do WhatsApp que recebe o "Enviar teste para mim" (ex.: `5547999999999@c.us`). |
| `ADMIN_SECRET_KEY` | Segredo de sessão/CSRF. `setup.sh` e `deploy.sh` geram um se estiver ausente ou vazio. |

**Passo manual (uma única vez) em servidor já existente:** o arquivo ativo do NGINX é gerenciado pelo
Certbot e o `deploy.sh` não o reescreve. Dentro do bloco `server` 443, logo após `auth_basic_user_file`, adicione:

```nginx
include snippets/daily-admin.conf;
```

e rode `nginx -t && systemctl reload nginx`. O `deploy.sh` avisa enquanto o `include` não existir.
Em instalações novas o `deploy/nginx.conf` já traz o `include`.

Backup: `data/agendamentos.db` é o único arquivo com estado (agendamentos + histórico de envios).

Rodar localmente (HTTP puro, sem NGINX):

```bash
ADMIN_INSECURE_COOKIE=1 .venv/bin/python -m flask --app admin.app run --port 8081
# abra http://127.0.0.1:8081/admin/
```

- `ADMIN_INSECURE_COOKIE=1` libera o cookie de sessão em HTTP. **Somente para uso local** — nunca no `.env`
  de produção (o `daily-admin.service` não define essa variável; em produção o cookie exige HTTPS).
- `ADMIN_NO_FILE_LOG=1` desliga o `admin.log` (usado pelos testes).

## Relatório diário de Meta Ads

Envia, por conta de anúncios, o resumo de **ontem** (investimento, alcance,
cliques, CPC/CPM, resultados e top campanhas) mais o acumulado do mês.
Sai todo dia às **8h30** (`META_BRIEFING_HOUR/MINUTE` no `.env`).

1. No Business Manager, crie um **System User** com acesso à conta de anúncios
   e gere um token com a permissão `ads_read`. Coloque em `META_ACCESS_TOKEN` no `.env`.
2. Adicione a conta em `config/meta_ads_accounts.json`:
   ```json
   {
     "accounts": [
       {
         "ad_account_id": "act_123456789012345",
         "nome": "Cidade - Bairro",
         "unidade_id": 20
       }
     ]
   }
   ```
   Sem `chat_id`/`chat_ids`, a mensagem vai para os destinatários da unidade
   em `unit_groups.json`. Informe `chat_id` para mandar a outro grupo/número.
3. Teste com `python main.py --dry-meta` e depois `--test-meta`.

**Contas em outra Business Manager:** gere um token de System User naquela BM,
coloque no `.env` em uma variável própria (ex.: `META_ACCESS_TOKEN_PORTUGAL=...`)
e aponte o nome dela no campo `token_env` da conta:
```json
{ "ad_account_id": "act_999", "nome": "Portugal - Oeiras", "chat_id": "...@g.us", "token_env": "META_ACCESS_TOKEN_PORTUGAL" }
```
Contas sem `token_env` continuam usando `META_ACCESS_TOKEN`. O token nunca vai no JSON.

**Dia sem veiculação:** se ontem a conta teve gasto e impressões zerados (campanhas
pausadas), o relatório **não é enviado** ao cliente (`META_SKIP_EMPTY=true`, padrão).
A partir do 3º dia vazio consecutivo (`META_EMPTY_ALERT_DAYS`) a franqueadora recebe
um aviso, repetido a cada 7 dias enquanto continuar vazio. Para uma conta receber o
relatório mesmo vazio, use `"enviar_vazio": true` na entrada dela. A contagem fica em
`output/meta_ads_state.json`.

## Logs

```bash
# No servidor — briefing (inclui o job das mensagens agendadas):
journalctl -u daily-briefing -f
tail -f /opt/barbearia-daily/daily.log

# Área administrativa — app (admin.log, rotacionado 5 MB × 7) e gunicorn (journal):
tail -f /opt/barbearia-daily/admin.log
journalctl -u daily-admin -f
```
