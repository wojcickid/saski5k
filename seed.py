"""Skrypt seedujący bazę danych: domyślne role oraz konta demonstracyjne.

Uruchomienie:  flask db upgrade && python seed.py
- Zakłada, że schemat bazy jest już utworzony przez migracje (`flask db upgrade`) -
  ten skrypt NIE tworzy tabel, tylko wypełnia je danymi.
- Seeduje domyślny słownik ról (dzieje się to też automatycznie przy starcie
  aplikacji - patrz app/__init__.py).
- Dodatkowo tworzy konta demo (admin / koordynator / wolontariusz) oraz
  kilka nadchodzących sobót z wygenerowanymi rolami, żeby MVP dało się od
  razu przeklikać.
"""

from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.exc import OperationalError

from app import create_app
from app.extensions import db
from app.models import User, Role, SaturdayEvent
from app.seed_data import seed_role_templates, apply_default_roles_to_event

DEMO_PASSWORD = "haslo123"

DEMO_USERS = [
    dict(
        first_name="Anna",
        last_name="Admin",
        email="admin@parkrun-lublin.pl",
        parkrun_id="A1000001",
        role=Role.ADMIN,
    ),
    dict(
        first_name="Kamil",
        last_name="Koordynator",
        email="koordynator@parkrun-lublin.pl",
        parkrun_id="A1000002",
        role=Role.COORDINATOR,
    ),
    dict(
        first_name="Wojtek",
        last_name="Wolontariusz",
        email="wolontariusz@parkrun-lublin.pl",
        parkrun_id="A1000003",
        role=Role.VOLUNTEER,
    ),
]


def next_saturday(from_date):
    days_ahead = (5 - from_date.weekday()) % 7
    days_ahead = days_ahead or 7
    return from_date + timedelta(days=days_ahead)


def main():
    app = create_app()
    with app.app_context():
        try:
            seed_role_templates(db)
        except OperationalError:
            print(
                "Baza danych nie jest jeszcze zmigrowana (brak tabel).\n"
                "Uruchom najpierw:  flask db upgrade\n"
                "...a dopiero potem ponownie:  python seed.py"
            )
            return

        print("== Konta demonstracyjne ==")
        for data in DEMO_USERS:
            existing = User.query.filter_by(email=data["email"]).first()
            if existing:
                print(f"  - {data['email']} już istnieje, pomijam.")
                continue
            user = User(**data)
            user.set_password(DEMO_PASSWORD)
            db.session.add(user)
            print(f"  - utworzono {data['email']} (rola: {data['role']}, hasło: {DEMO_PASSWORD})")
        db.session.commit()

        print("== Nadchodzące soboty ==")
        d = date.today()
        for _ in range(6):
            d = next_saturday(d)
            if SaturdayEvent.query.filter_by(date=d).first():
                print(f"  - {d} już istnieje, pomijam.")
                continue
            event = SaturdayEvent(date=d)
            db.session.add(event)
            db.session.commit()
            apply_default_roles_to_event(db, event)
            print(f"  - utworzono sobotę {d} z domyślnym zestawem ról")

        print("\nGotowe! Możesz się zalogować danymi z sekcji 'Konta demonstracyjne' powyżej.")


if __name__ == "__main__":
    main()
