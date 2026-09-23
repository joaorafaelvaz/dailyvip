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
├── output/                    # HTMLs gerados (não versionados)
└── deploy/
    ├── nginx.conf             # Config NGINX para status.franquiabv.com.br
    ├── daily-briefing.service # Serviço systemd
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
# No servidor:
journalctl -u daily-briefing -f
tail -f /opt/barbearia-daily/daily.log
```
