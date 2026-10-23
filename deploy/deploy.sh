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

# 5. Reinicia o serviço
info "Reiniciando serviço..."
systemctl restart "$SERVICE"

# Aguarda 3s e verifica status
sleep 3
if systemctl is-active --quiet "$SERVICE"; then
    info "Serviço ativo. Deploy concluído com sucesso."
else
    echo ""
    warn "Serviço não iniciou corretamente. Verifique:"
    warn "  journalctl -u $SERVICE -n 30"
    exit 1
fi
