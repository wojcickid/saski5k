import os

from flask import Flask

from .config import Config
from .extensions import db, login_manager, mail, migrate


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)

    # --- Rozszerzenia ---
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Zaloguj się, aby kontynuować."
    login_manager.login_message_category = "info"
    mail.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        user = User.query.get(int(user_id))
        if user and not user.is_active:
            # Konto zablokowane przez admina po zalogowaniu - wyloguj przy
            # najbliższym żądaniu (zwrócenie None każe Flask-Loginowi
            # potraktować sesję jako niezalogowaną).
            return None
        return user

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

    from .pl_dates import format_pl_date, format_pl_weekday

    app.template_filter("pl_date")(format_pl_date)
    app.template_filter("pl_weekday")(format_pl_weekday)

    # --- Obsługa błędów ---
    @app.errorhandler(403)
    def forbidden(e):
        return _render_error(app, 403, "Brak uprawnień", "Nie masz dostępu do tej strony.")

    @app.errorhandler(404)
    def not_found(e):
        return _render_error(app, 404, "Nie znaleziono", "Szukana strona nie istnieje.")

    # --- Seed domyślnych ról ---
    # Schemat bazy jest teraz zarządzany przez Flask-Migrate/Alembic (katalog
    # migrations/), NIE przez db.create_all() - patrz sekcja "Baza danych /
    # migracje" w README. Tabele muszą już istnieć (`flask db upgrade`),
    # inaczej poniższe zapytanie się nie powiedzie - łapiemy to i tylko
    # ostrzegamy w logu, żeby dev-serwer nie wywalał się nieczytelnym tracebackiem.
    with app.app_context():
        from sqlalchemy.exc import OperationalError
        from .seed_data import seed_role_templates

        try:
            seed_role_templates(db)
        except OperationalError:
            app.logger.warning(
                "Baza danych nie jest jeszcze zmigrowana (brak tabel). "
                "Uruchom `flask db upgrade`, a potem zrestartuj aplikację."
            )

    return app


def _render_error(app, code, title, message):
    from flask import render_template

    return render_template("error.html", code=code, title=title, message=message), code
