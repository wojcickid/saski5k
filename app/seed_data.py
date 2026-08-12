"""Domyślny słownik ról wolontariackich parkrun oraz funkcje pomocnicze do seedowania."""

# (nazwa, kategoria, opis)
DEFAULT_ROLE_TEMPLATES = [
    # --- Obowiązkowe / kluczowe ---
    ("Koordynator spotkania (Run Director)", "core", "Nadzoruje przebieg całego wydarzenia"),
    ("Pomiar czasu (Timekeeper)", "core", "Mierzy czasy biegaczy na mecie"),
    ("Wydawanie tokenów (Finish Tokens)", "core", "Wydaje żetony z pozycją na mecie"),
    ("Skanowanie kodów uczestników (Barcode Scanner)", "core", "Skanuje kody kreskowe uczestników i żetony pozycji"),
    ("Biegacz zamykający (Tail Walker)", "core", "Zamyka stawkę, dba o bezpieczeństwo ostatnich uczestników"),
    ("Odprawa debiutantów (First Timers Welcome)", "core", "Wita nowych uczestników i tłumaczy zasady parkrun"),
    # --- Dodatkowe / wspierające ---
    ("Wolontariusz na trasie (Marshal)", "support", "Ubezpiecza trasę i wskazuje kierunek biegu"),
    ("Fotograf (Photographer)", "support", "Robi zdjęcia z wydarzenia"),
    ("Sortowanie tokenów (Token Sorter)", "support", "Sortuje żetony pozycji po zakończeniu biegu"),
    ("Instruktaż dla wolontariuszy / Przechowywanie sprzętu", "support", "Wprowadza nowych wolontariuszy i dba o sprzęt klubowy"),
    ("Autor raportu z biegu (Run Report Writer)", "support", "Pisze cotygodniowy raport z wydarzenia"),
    ("Parkwalker (Marszczyciel parkrun)", "support", "Pokonuje trasę spacerem na końcu stawki"),
]


def seed_role_templates(db):
    """Zasila tabelę RoleTemplate domyślnym słownikiem ról, jeśli jest pusta."""
    from .models import RoleTemplate

    if RoleTemplate.query.count() > 0:
        return

    for i, (name, category, description) in enumerate(DEFAULT_ROLE_TEMPLATES):
        db.session.add(
            RoleTemplate(name=name, category=category, description=description, sort_order=i)
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
            db.session.add(EventRole(event_id=event.id, role_template_id=t.id, name=t.name))
    db.session.commit()
