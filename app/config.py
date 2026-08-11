import os

basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def _bool_env(name, default="false"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-zmien-w-produkcji")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(basedir, "instance", "parkrun.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Liczba nadchodzących sobót widocznych domyślnie w kalendarzu (kroki 4-8 wg specyfikacji)
    UPCOMING_SATURDAYS_COUNT = int(os.environ.get("UPCOMING_SATURDAYS_COUNT", 8))

    # Dane wydarzenia parkrun
    EVENT_NAME = os.environ.get("EVENT_NAME", "parkrun Ogród Saski, Lublin")
    DEFAULT_MEETING_TIME = os.environ.get("DEFAULT_MEETING_TIME", "08:40")
    DEFAULT_RUN_TIME = os.environ.get("DEFAULT_RUN_TIME", "09:00")

    # Flask-Mail (SMTP). Ustaw MAIL_SUPPRESS_SEND=false i podaj dane SMTP, aby faktycznie wysyłać e-maile.
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = _bool_env("MAIL_USE_TLS", "true")
    MAIL_USE_SSL = _bool_env("MAIL_USE_SSL", "false")
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", MAIL_USERNAME or "wolontariat@parkrun-ogrodsaski.pl"
    )
    # Gdy True - e-maile nie są realnie wysyłane, tylko logowane w konsoli
    # (pozwala uruchomić MVP od razu, bez konfigurowania SMTP)
    MAIL_SUPPRESS_SEND = _bool_env("MAIL_SUPPRESS_SEND", "true")
