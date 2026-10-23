#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Atualiza o Daily Briefing no servidor (git pull + restart)
#
# Uso:
#   bash /opt/barbearia-daily/deploy/deploy.sh
#   # ou via GitHub Actions / webhook
# =============================================================================
set -euo pipefail

APP_DIR="/opt/barbearia-daily"
SERVICE="daily-briefing"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $*"; }

info "Iniciando deploy — $(date '+%Y-%m-%d %H:%M:%S')"

# Garante que root pode operar no diretório independente do owner
git config --global --add safe.directory "$APP_DIR"

# 1. Atualiza código e RE-EXECUTA este script já atualizado.
# Motivo: o bash carrega o deploy.sh na memória antes do git pull; sem o
# re-exec, o restante do deploy roda com a lógica ANTIGA (foi assim que uma
# trava nova no nginx não protegeu o próprio deploy que a introduziu).
if [[ -z "${DEPLOY_POST_PULL:-}" ]]; then
    info "git pull..."
    git -C "$APP_DIR" fetch origin
    LOCAL=$(git -C "$APP_DIR" rev-parse HEAD)
    REMOTE=$(git -C "$APP_DIR" rev-parse origin/main)

    if [[ "$LOCAL" == "$REMOTE" ]]; then
        warn "Nenhuma alteração no repositório. Deploy cancelado."
        exit 0
    fi

    git -C "$APP_DIR" pull --ff-only origin main
    info "Código atualizado: ${LOCAL:0:7} → ${REMOTE:0:7}"
    export DEPLOY_POST_PULL=1 DEPLOY_LOCAL="$LOCAL" DEPLOY_REMOTE="$REMOTE"
    exec bash "$APP_DIR/deploy/deploy.sh" "$@"
fi
LOCAL="$DEPLOY_LOCAL"
REMOTE="$DEPLOY_REMOTE"

# 2. Atualiza dependências Python se requirements mudou
if git -C "$APP_DIR" diff --name-only "$LOCAL" "$REMOTE" | grep -q "requirements.txt"; then
    info "requirements.txt mudou — atualizando pacotes..."
    "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
fi

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

# 3. Atualiza config do NGINX se mudou
if git -C "$APP_DIR" diff --name-only "$LOCAL" "$REMOTE" | grep -q "deploy/nginx.conf"; then
    NGINX_LIVE=/etc/nginx/sites-available/daily-briefing
    if grep -qE "managed by Certbot|listen 443|ssl_certificate" "$NGINX_LIVE" 2>/dev/null; then
        # O Certbot reescreveu o arquivo ativo (bloco SSL + redirect). Copiar o
        # nginx.conf do repo (HTTP-only) por cima derrubaria o HTTPS.
        warn "nginx.conf mudou, mas a config ativa é gerenciada pelo Certbot — NÃO sobrescrita."
        warn "Aplique a diferença manualmente e recarregue:"
        warn "  diff $APP_DIR/deploy/nginx.conf $NGINX_LIVE"
        warn "  nano $NGINX_LIVE && nginx -t && systemctl reload nginx"
    else
        info "nginx.conf mudou — recarregando NGINX..."
        cp "$APP_DIR/deploy/nginx.conf" "$NGINX_LIVE"
        nginx -t && systemctl reload nginx
    fi
fi

# 4. Atualiza serviço systemd se mudou
if git -C "$APP_DIR" diff --name-only "$LOCAL" "$REMOTE" | grep -q "deploy/daily-briefing.service"; then
    info "Service file mudou — recarregando systemd..."
    cp "$APP_DIR/deploy/daily-briefing.service" /etc/systemd/system/daily-briefing.service
    systemctl daemon-reload
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

# 4d. data/ (SQLite dos agendamentos): o app cria o schema ao importar, então o
# diretório precisa existir e ser gravável pelo usuário do serviço.
mkdir -p "$APP_DIR/data" && chown briefing:briefing "$APP_DIR/data"

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
