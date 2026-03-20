# Daily Briefing — Barbearia VIP

Envia automaticamente às **8h** um briefing consolidado via WhatsApp e gera um dashboard HTML acessível em **https://status.franquiabv.xyz**.

## Stack

- **Python 3.11+** — APScheduler, PyMySQL, Jinja2, Requests
- **Fontes:** ERP MySQL · Perfex CRM · SatisfyCAM · Google Reviews
- **Saída:** WhatsApp via WAHA · Dashboard HTML estático
- **Servidor:** NGINX + Let's Encrypt em `201.22.86.97`

## Estrutura

```
daily/
├── main.py                    # Entry point + scheduler
├── config.py                  # Variáveis de ambiente
├── requirements.txt
├── .env.example               # Template de configuração
├── collectors/                # Coletores de dados (ERP, CRM, CAM, Google)
├── composers/                 # Geração do HTML e mensagem WhatsApp
├── senders/                   # Cliente WAHA
├── templates/                 # Template Jinja2 do dashboard
├── output/                    # HTMLs gerados (não versionados)
└── deploy/
    ├── nginx.conf             # Config NGINX para status.franquiabv.xyz
    ├── daily-briefing.service # Serviço systemd
    ├── setup.sh               # Instalação inicial no servidor
    ├── deploy.sh              # Atualização (git pull + restart)
    └── init-repo.sh           # Inicializa o repositório no GitHub (uma vez)
```

## Instalação no servidor

```bash
# No servidor 201.22.86.97 (como root):
git clone https://github.com/joaorafaelvaz/dailyvip.git /opt/barbearia-daily
bash /opt/barbearia-daily/deploy/setup.sh
```

O script faz automaticamente:
1. Instala dependências do sistema e Python
2. Cria virtualenv e instala pacotes
3. Configura NGINX para `status.franquiabv.xyz`
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
```

## Logs

```bash
# No servidor:
journalctl -u daily-briefing -f
tail -f /opt/barbearia-daily/daily.log
```
