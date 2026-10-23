#!/usr/bin/env bash
# =============================================================================
# setup.sh — Instalação inicial do Daily Briefing no servidor
# Barbearia VIP | status.franquiabv.com.br → 72.61.44.166
#
# Uso (como root ou sudo):
#   bash setup.sh
# =============================================================================
set -euo pipefail

# ── Configurações ─────────────────────────────────────────────────────────────
REPO_URL="https://github.com/joaorafaelvaz/dailyvip.git"
APP_DIR="/opt/barbearia-daily"
APP_USER="briefing"
DOMAIN="status.franquiabv.com.br"
NGINX_CONF="/etc/nginx/sites-available/daily-briefing"
SERVICE_FILE="/etc/systemd/system/daily-briefing.service"
ADMIN_SERVICE_FILE="/etc/systemd/system/daily-admin.service"

# ── Cores para output ─────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Verificações ──────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Execute como root: sudo bash setup.sh"
command -v git   >/dev/null || error "git não encontrado. Instale com: apt install git"
command -v nginx >/dev/null || error "nginx não encontrado. Instale com: apt install nginx"

# ── 1. Dependências do sistema ────────────────────────────────────────────────
info "Instalando dependências..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv certbot python3-certbot-nginx

# ── 2. Usuário do serviço ─────────────────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
    info "Criando usuário '$APP_USER'..."
    useradd --system --no-create-home --shell /bin/false "$APP_USER"
fi

# ── 3. Diretório da aplicação ─────────────────────────────────────────────────
# Garante que root pode operar no diretório independente do owner
git config --global --add safe.directory "$APP_DIR"

info "Clonando repositório em $APP_DIR..."
if [[ -d "$APP_DIR/.git" ]]; then
    warn "Repositório já existe. Fazendo pull..."
    git -C "$APP_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$APP_DIR"
fi

# Cria diretórios necessários
mkdir -p "$APP_DIR/output" "$APP_DIR/credentials" "$APP_DIR/data"   # data/: SQLite dos agendamentos

# ── 4. Virtualenv e dependências Python ───────────────────────────────────────
info "Criando virtualenv e instalando pacotes Python..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# ── 5. Arquivo .env ───────────────────────────────────────────────────────────
if [[ ! -f "$APP_DIR/.env" ]]; then
    info "Criando .env a partir do .env.example..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"

    # Ajusta automaticamente a URL do dashboard
    sed -i "s|DASHBOARD_BASE_URL=.*|DASHBOARD_BASE_URL=https://$DOMAIN|" "$APP_DIR/.env"

    warn "========================================================"
    warn " IMPORTANTE: edite $APP_DIR/.env com as credenciais!"
    warn "   nano $APP_DIR/.env"
    warn "========================================================"
else
    info ".env já existe, mantendo configuração atual."
fi

# Segredo do app administrativo (sessão/CSRF): gera se ausente ou vazio
if ! grep -q '^ADMIN_SECRET_KEY=.\+' "$APP_DIR/.env"; then
    if grep -q '^ADMIN_SECRET_KEY=' "$APP_DIR/.env"; then
        sed -i "s|^ADMIN_SECRET_KEY=.*|ADMIN_SECRET_KEY=$(openssl rand -hex 32)|" "$APP_DIR/.env"
    else
        # Garante que o .env termina em quebra de linha (senão o append gruda na última linha)
        if [[ -s "$APP_DIR/.env" && -n "$(tail -c1 "$APP_DIR/.env")" ]]; then echo >> "$APP_DIR/.env"; fi
        echo "ADMIN_SECRET_KEY=$(openssl rand -hex 32)" >> "$APP_DIR/.env"
    fi
fi

# ── 6. Permissões ─────────────────────────────────────────────────────────────
info "Ajustando permissões..."
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 750 "$APP_DIR"
chmod 640 "$APP_DIR/.env"
chmod 770 "$APP_DIR/output"     # nginx precisa ler; briefing precisa escrever

# Permite que nginx leia o output/
usermod -aG "$APP_USER" www-data 2>/dev/null || true

# ── 7. Login do dashboard (HTTP Basic Auth) ───────────────────────────────────
HTPASSWD_FILE="/etc/nginx/.htpasswd-daily"
if [[ ! -f "$HTPASSWD_FILE" ]]; then
    info "Criando usuário de acesso ao dashboard (htpasswd)..."
    apt-get install -y -qq apache2-utils
    htpasswd -cB "$HTPASSWD_FILE" franqueadora     # pede a senha no terminal
    chown root:www-data "$HTPASSWD_FILE"
    chmod 640 "$HTPASSWD_FILE"
else
    info "Arquivo de senhas $HTPASSWD_FILE já existe, mantendo."
fi

# ── 8. NGINX ──────────────────────────────────────────────────────────────────
info "Configurando NGINX..."
cp "$APP_DIR/deploy/nginx.conf" "$NGINX_CONF"

# Ajusta o root para o diretório de output
sed -i "s|root  /opt/barbearia-daily/output;|root  $APP_DIR/output;|" "$NGINX_CONF"

# Habilita o site
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/daily-briefing

# Remove default se ainda estiver lá
rm -f /etc/nginx/sites-enabled/default

# Snippet da área administrativa (/admin -> Flask em 127.0.0.1:8081), incluído pelo nginx.conf
mkdir -p /etc/nginx/snippets && cp "$APP_DIR/deploy/nginx-admin.conf" /etc/nginx/snippets/daily-admin.conf

# Testa a configuração
nginx -t
systemctl reload nginx
info "NGINX configurado e recarregado."

# ── 9. SSL com Certbot ────────────────────────────────────────────────────────
info "Obtendo certificado SSL via Certbot..."
if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "ti@barbeariavip.com.br" 2>/dev/null; then
    info "Certificado SSL instalado com sucesso."
else
    warn "Certbot falhou. O site ficará em HTTP."
    warn "Tente manualmente: certbot --nginx -d $DOMAIN"
fi

# ── 10. Serviço systemd ────────────────────────────────────────────────────────
info "Instalando serviço systemd..."
cp "$APP_DIR/deploy/daily-briefing.service" "$SERVICE_FILE"
cp "$APP_DIR/deploy/daily-admin.service" "$ADMIN_SERVICE_FILE"

# Ajusta caminho caso APP_DIR seja diferente do padrão
sed -i "s|/opt/barbearia-daily|$APP_DIR|g" "$SERVICE_FILE" "$ADMIN_SERVICE_FILE"

systemctl daemon-reload
systemctl enable daily-briefing daily-admin
systemctl start  daily-briefing daily-admin

# ── 11. Verificação final ─────────────────────────────────────────────────────
echo ""
echo "============================================================"
info "Instalação concluída!"
echo ""
echo -e "  Serviço:   ${GREEN}$(systemctl is-active daily-briefing)${NC}"
echo -e "  Admin:     ${GREEN}$(systemctl is-active daily-admin)${NC}  (https://$DOMAIN/admin/)"
echo -e "  Dashboard: ${GREEN}https://$DOMAIN${NC}"
echo ""
echo "  Próximos passos:"
echo "   1. Edite o .env:        nano $APP_DIR/.env"
echo "   2. Copie credenciais:   $APP_DIR/credentials/"
echo "   3. Teste o briefing:    sudo -u $APP_USER $APP_DIR/.venv/bin/python $APP_DIR/main.py --dry"
echo "   4. Veja os logs:        journalctl -u daily-briefing -f"
echo "============================================================"
