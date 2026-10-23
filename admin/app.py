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
        # Só os loggers raiz: "admin.relatorios", "admin.agendamentos" e "admin.ia"
        # propagam para "admin" (anexar o handler também aos filhos duplicaria cada linha).
        for name in ("admin", "briefing", "collectors"):
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
