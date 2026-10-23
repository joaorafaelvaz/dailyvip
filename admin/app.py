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
from admin import agendamentos as ag
from admin import relatorios
from senders import waha

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
        if not tok or not secrets.compare_digest(tok, session.get("csrf_token", "")):
            abort(400, "token CSRF inválido — recarregue a página")


@bp.app_context_processor
def _inject():
    hoje = config.hoje_local()
    # `ontem` = último dia com dados fechados (limite do <input type=date> do diário)
    return {"csrf_token": _csrf_token, "hoje": hoje, "ontem": hoje - timedelta(days=1)}


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
    except (relatorios.DataInvalida, relatorios.ColetaFalhou) as exc:
        flash(f"Não foi possível gerar: {exc}", "erro")
        return redirect(url_for("admin.relatorios_page"))
    except relatorios.GeracaoEmAndamento as exc:
        flash(str(exc), "aviso")
        return redirect(url_for("admin.relatorios_page"))
    except Exception:
        logging.getLogger("admin").exception("Falha ao gerar relatório %s %s", tipo, d)
        flash("Erro ao gerar o relatório. Veja admin.log.", "erro")
        return redirect(url_for("admin.relatorios_page"))
    # Sem flash de sucesso: o redirect vai para o arquivo estático, e a mensagem
    # só apareceria (já velha) na próxima visita ao /admin.
    return redirect(relatorios.url_de(nome))


# ── Mensagens agendadas ───────────────────────────────────────────────────────

def _db():
    con = ag.conectar()
    ag.criar_schema(con)
    return con


def _parse_form(f):
    """Valida o formulário (spec §5 'Validação'); retorna (campos, erros)."""
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


def _valores(f, editando=None) -> dict:
    """Valores para pré-preencher o formulário: POST com erro > agendamento em edição > vazio."""
    if f:
        return {"texto": f.get("texto", ""), "unidades": set(f.getlist("unidades")),
                "todas": f.get("todas") == "1", "franqueadora": f.get("franqueadora") == "1",
                "data": f.get("data", ""), "hora": f.get("hora", "09:00"),
                "recorrencia": f.get("recorrencia", "nenhuma"), "dias": set(f.getlist("dias")),
                "dia_mes": f.get("dia_mes", "1"), "fim": f.get("fim", "")}
    if editando:
        rec, p, d = editando["recorrencia"], editando["primeiro_envio"], editando["destinos"]
        return {"texto": editando["texto"], "unidades": {str(u) for u in d.get("unidades", [])},
                "todas": bool(d.get("todas")), "franqueadora": bool(d.get("franqueadora")),
                "data": p.date().isoformat(), "hora": p.strftime("%H:%M"),
                "recorrencia": rec.get("tipo", "nenhuma"), "dias": {str(x) for x in rec.get("dias", [])},
                "dia_mes": str(rec.get("dia", 1)), "fim": editando["fim"].date().isoformat() if editando["fim"] else ""}
    return {"texto": "", "unidades": set(), "todas": False, "franqueadora": False, "data": "", "hora": "09:00",
            "recorrencia": "nenhuma", "dias": set(), "dia_mes": "1", "fim": ""}


def _render_mensagens(con, editando=None):
    unidades = sorted(((int(k), v.get("nome", k)) for k, v in (config.UNIT_GROUPS or {}).items()), key=lambda x: x[1])
    return render_template("mensagens.html", unidades=unidades, proximos=ag.listar(con), historico=ag.historico(con),
                           ia_disponivel=bool(config.ANTHROPIC_API_KEY), teste_disponivel=bool(config.ADMIN_TEST_CHAT_ID),
                           v=_valores(request.form, editando), editando=editando)


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
    return _render_mensagens(con)


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
    return _render_mensagens(con, editando=a)


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


@bp.route("/mensagens/ia", methods=["POST"])
def mensagens_ia():
    # Provisória: a Task 13 (admin/ia.py) substitui esta rota.
    return jsonify({"erro": "IA ainda não disponível"}), 503


# ── Fábrica ───────────────────────────────────────────────────────────────────

# Só os loggers raiz: "admin.relatorios", "admin.agendamentos" e "admin.ia"
# propagam para "admin" (anexar o handler também aos filhos duplicaria cada linha).
_LOGGERS_RAIZ = ("admin", "briefing", "collectors", "composers")


def _setup_logging(app: Flask):
    if os.environ.get("ADMIN_NO_FILE_LOG"):      # testes: nada de admin.log
        return
    log_path = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "admin.log"))
    loggers = [logging.getLogger(n) for n in _LOGGERS_RAIZ]
    for lg in loggers:
        lg.setLevel(logging.INFO)

    # Reaproveita um handler já anexado (create_app() repetido não deve abrir outro handle)
    fh = next((h for lg in loggers for h in lg.handlers
               if isinstance(h, RotatingFileHandler) and h.baseFilename == log_path), None)
    faltam = [lg for lg in loggers if fh not in lg.handlers]
    if not faltam:
        return
    if fh is None:
        try:
            fh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=7)
        except PermissionError:
            app.logger.warning("Sem permissão para %s", log_path)
            return
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
    for lg in faltam:
        lg.addHandler(fh)


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = config.ADMIN_SECRET_KEY
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    # Em produção o cookie só trafega em HTTPS (nginx). ADMIN_INSECURE_COOKIE=1
    # libera HTTP puro (testes, app.run local).
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("ADMIN_INSECURE_COOKIE") != "1"
    app.register_blueprint(bp)
    _setup_logging(app)
    return app


app = create_app()
