import os

from flask import Flask

from .config import Config
from .extensions import db, login_manager, mail


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)

    # --- Rozszerzenia ---
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Zaloguj się, aby kontynuować."
    login_manager.login_message_category = "info"
    mail.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # --- Blueprinty ---
    from .auth import auth_bp
    from .main import main_bp
    from .coordinator import coordinator_bp
    from .admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(coordinator_bp)
    app.register_blueprint(admin_bp)

    # --- Kontekst szablonów ---
    @app.context_processor
    def inject_globals():
        return {
            "event_name": app.config["EVENT_NAME"],
        }

    _MONTHS_PL = {
        1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
        5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
        9: "września", 10: "października", 11: "listopada", 12: "grudnia",
    }

    @app.template_filter("pl_date")
    def pl_date(d):
        """Formatuje datę po polsku, np. '16 sierpnia 2026'."""
        if not d:
            return ""
        return f"{d.day} {_MONTHS_PL[d.month]} {d.year}"

    _WEEKDAYS_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]

    @app.template_filter("pl_weekday")
    def pl_weekday(d):
        """Zwraca nazwę dnia tygodnia po polsku, np. 'sobota' - przydatne dla
        edycji specjalnych, które mogą wypadać w dowolny dzień tygodnia."""
        if not d:
            return ""
        return _WEEKDAYS_PL[d.weekday()]

    # --- Obsługa błędów ---
    @app.errorhandler(403)
    def forbidden(e):
        return _render_error(app, 403, "Brak uprawnień", "Nie masz dostępu do tej strony.")

    @app.errorhandler(404)
    def not_found(e):
        return _render_error(app, 404, "Nie znaleziono", "Szukana strona nie istnieje.")

    # --- Inicjalizacja bazy danych + seed domyślnych ról ---
    with app.app_context():
        db.create_all()
        from .seed_data import seed_role_templates

        seed_role_templates(db)

    return app


def _render_error(app, code, title, message):
    from flask import render_template

    return render_template("error.html", code=code, title=title, message=message), code
