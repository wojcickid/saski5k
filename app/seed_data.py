"""Domyślny słownik ról wolontariackich parkrun oraz funkcje pomocnicze do seedowania."""

# (nazwa, kategoria, opis, czy domyślna) - dokładne nazwy ról używane przez
# parkrun.pl (harmonogram/eksport przyszłego rostera), żeby import
# harmonogramu (coordinator.import_roster) dopasowywał się do słownika
# jeden-do-jednego.
DEFAULT_ROLE_TEMPLATES = [
    # --- Obowiązkowe / kluczowe ---
    ("Koordynator(ka) spotkania", "core", "Nadzoruje przebieg całego wydarzenia", True),
    ("Mierząc(a)y czas", "core", "Mierzy czasy biegaczy na mecie", True),
    ("Odprawa debiutantów", "core", "Wita nowych uczestników i tłumaczy zasady parkrun", True),
    ("Skanując(a)y uczestników", "core", "Skanuje kody kreskowe uczestników i żetony pozycji", True),
    ("Wydając(a)y tokeny", "core", "Wydaje żetony z pozycją na mecie", True),
    ("Zamykając(a)y stawkę", "core", "Zamyka stawkę, dba o bezpieczeństwo ostatnich uczestników", True),
    # --- Dodatkowe / wspierające ---
    ("Fotograf", "support", "Robi zdjęcia z wydarzenia", True),
    ("Rozstawiając(a)y oznakowanie", "support", "Rozstawia oznakowanie trasy przed startem", True),
    ("Zbierając(a)y oznakowanie", "support", "Zbiera oznakowanie trasy po zakończeniu biegu", True),
    ("Przygotowując(a)y raport", "support", "Pisze raport z wydarzenia", True),
    ("Sprawdzając(a)y trasę", "support", "Sprawdza stan trasy przed biegiem", True),
    ("Sortując(a)y tokeny", "support", "Sortuje żetony pozycji po zakończeniu biegu", True),
    ("Wprowadzając(a)y wyniki", "support", "Wprowadza wyniki do systemu parkrun", True),
    ("Komunikacja i promocja", "support", "Komunikacja i promocja wydarzenia", True),
    ("Ubezpieczając(a)y trasę", "support", "Ubezpiecza trasę i wskazuje kierunek biegu", True),
    ("Przechowując(a)y wyposażenie", "support", "Dba o sprzęt klubowy", True),
    ("parkwalker", "support", "Pokonuje trasę spacerem na końcu stawki", True),
    ("Inne", "support", "Inne zadania wolontariackie", True),
    # Nie-domyślna: u nas odbywa się ok. co 5 spotkań, nie na każdą sobotę.
    # Zawsze kilka osób naraz, każda na inny wyznaczony czas (np. 20, 25, 30 min)
    # - przy dodawaniu roli na konkretną sobotę użyj pola "etykiety slotów"
    # (main/saturday_detail.html), żeby każdy slot pokazywał swój czas.
    (
        "Wyznaczanie tempa", "support",
        "Prowadzi grupę biegaczy na wyznaczonym, stałym czasie (pace) - jednocześnie kilka osób, "
        "każda na inny czas (np. 20, 25, 30 min)",
        False,
    ),
]


def seed_role_templates(db):
    """Zasila tabelę RoleTemplate domyślnym słownikiem ról, jeśli jest pusta."""
    from .models import RoleTemplate

    if RoleTemplate.query.count() > 0:
        return

    for i, (name, category, description, is_default) in enumerate(DEFAULT_ROLE_TEMPLATES):
        db.session.add(
            RoleTemplate(name=name, category=category, description=description, sort_order=i, is_default=is_default)
        )
    db.session.commit()


def apply_default_roles_to_event(db, event):
    """Tworzy zestaw ról (EventRole) dla nowo utworzonej soboty na podstawie
    ról oznaczonych przez koordynatora jako domyślne (RoleTemplate.is_default),
    po `RoleTemplate.default_slots` niezależnych slotów na rolę (część ról,
    np. Parkwalker czy Pacemaker, potrzebuje kilku osób jednocześnie)."""
    from .models import RoleTemplate, EventRole

    templates = RoleTemplate.query.filter_by(is_default=True).order_by(RoleTemplate.sort_order).all()
    for t in templates:
        for _ in range(t.default_slots):
            db.session.add(EventRole(event_id=event.id, role_template_id=t.id, name=t.name, sort_order=t.sort_order))
    db.session.commit()
