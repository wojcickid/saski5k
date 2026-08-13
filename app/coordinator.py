import re
from datetime import date, timedelta
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from .extensions import db
from .models import SaturdayEvent, EventRole, RoleTemplate, Signup, SignupStatus, User, ActivityLog, CUSTOM_ROLE_SORT_ORDER
from .seed_data import apply_default_roles_to_event
from .email_utils import send_signup_approved_email, send_signup_rejected_email
from .auth import PARKRUN_ID_RE
from .activity_log import log_activity
from .pl_dates import parse_pl_date

HISTORY_LIMIT = 50

coordinator_bp = Blueprint("coordinator", __name__, url_prefix="/koordynator")

SATURDAY_WEEKDAY = 5  # poniedziałek=0 ... sobota=5


def coordinator_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_coordinator():
            abort(403)
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


def _next_saturday_after(d):
    days_ahead = (SATURDAY_WEEKDAY - d.weekday()) % 7
    days_ahead = days_ahead or 7
    return d + timedelta(days=days_ahead)


@coordinator_bp.route("/")
@coordinator_required
def panel():
    events = SaturdayEvent.query.order_by(SaturdayEvent.date).all()
    role_templates = RoleTemplate.query.order_by(RoleTemplate.sort_order).all()
    # Historia globalna: akcje niezwiązane z konkretną sobotą (słownik ról, dodanie/usunięcie soboty).
    global_history = (
        ActivityLog.query.filter_by(event_id=None)
        .order_by(ActivityLog.created_at.desc())
        .limit(HISTORY_LIMIT)
        .all()
    )
    return render_template(
        "coordinator/panel.html", events=events, role_templates=role_templates, history=global_history
    )


@coordinator_bp.route("/role-domyslne/<int:template_id>/przelacz", methods=["POST"])
@coordinator_required
def toggle_default_role(template_id):
    """Włącza/wyłącza rolę w domyślnym zestawie dodawanym do nowych sobót."""
    t = RoleTemplate.query.get_or_404(template_id)
    t.is_default = not t.is_default
    log_activity(
        "Włączono rolę domyślną" if t.is_default else "Wyłączono rolę domyślną",
        details=t.name,
    )
    db.session.commit()
    return render_template("coordinator/_default_role_item.html", t=t)


def _parse_slots(raw, default=1):
    """Parsuje liczbę slotów z formularza, z bezpiecznym fallbackiem 1-20."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, 20))


@coordinator_bp.route("/role-domyslne/dodaj", methods=["POST"])
@coordinator_required
def add_role_template():
    """Dodaje nową rolę do słownika (dostępną też do jednorazowego dodania na sobotę)."""
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "support")
    description = request.form.get("description", "").strip() or None
    default_slots = _parse_slots(request.form.get("default_slots"))

    if not name:
        flash("Podaj nazwę roli.", "error")
        return redirect(url_for("coordinator.panel"))
    if category not in ("core", "support"):
        category = "support"
    if RoleTemplate.query.filter_by(name=name).first():
        flash("Rola o takiej nazwie już istnieje w słowniku.", "error")
        return redirect(url_for("coordinator.panel"))

    max_sort = db.session.query(db.func.max(RoleTemplate.sort_order)).scalar() or 0
    t = RoleTemplate(
        name=name, category=category, description=description,
        sort_order=max_sort + 1, default_slots=default_slots,
    )
    db.session.add(t)
    log_activity("Dodano rolę do słownika", details=name)
    db.session.commit()

    flash(f"Dodano rolę „{name}” do słownika.", "success")
    return redirect(url_for("coordinator.panel"))


@coordinator_bp.route("/role-domyslne/<int:template_id>/wiersz")
@coordinator_required
def role_template_item(template_id):
    """Zwraca sam wiersz roli (bez zmian) - używane do anulowania edycji."""
    t = RoleTemplate.query.get_or_404(template_id)
    return render_template("coordinator/_default_role_item.html", t=t)


@coordinator_bp.route("/role-domyslne/<int:template_id>/edytuj")
@coordinator_required
def edit_role_template_form(template_id):
    t = RoleTemplate.query.get_or_404(template_id)
    return render_template("coordinator/_default_role_item_edit.html", t=t)


@coordinator_bp.route("/role-domyslne/<int:template_id>/edytuj", methods=["POST"])
@coordinator_required
def edit_role_template(template_id):
    t = RoleTemplate.query.get_or_404(template_id)
    name = request.form.get("name", "").strip()
    category = request.form.get("category", t.category)
    description = request.form.get("description", "").strip() or None
    default_slots = _parse_slots(request.form.get("default_slots"), default=t.default_slots)

    if not name:
        return render_template("coordinator/_default_role_item_edit.html", t=t, error="Podaj nazwę roli.")
    if category not in ("core", "support"):
        category = "support"
    duplicate = RoleTemplate.query.filter(RoleTemplate.name == name, RoleTemplate.id != t.id).first()
    if duplicate:
        return render_template(
            "coordinator/_default_role_item_edit.html", t=t, error="Rola o takiej nazwie już istnieje."
        )

    old_name = t.name
    t.name, t.category, t.description, t.default_slots = name, category, description, default_slots
    # EventRole trzyma własną kopię nazwy (snapshot) - aktualizujemy ją tylko
    # tam, gdzie jeszcze nie ma zgłoszenia, żeby nie zmieniać historycznych zapisów.
    for er in EventRole.query.filter_by(role_template_id=t.id).all():
        if er.active_signup is None:
            er.name = name

    log_activity("Edytowano rolę w słowniku", details=f"{old_name} → {name}" if old_name != name else name)
    db.session.commit()
    return render_template("coordinator/_default_role_item.html", t=t)


@coordinator_bp.route("/role-domyslne/<int:template_id>/usun", methods=["POST"])
@coordinator_required
def delete_role_template(template_id):
    t = RoleTemplate.query.get_or_404(template_id)
    name = t.name

    # Nie usuwamy w kaskadzie ról już przypisanych do sobót - EventRole ma
    # własną kopię nazwy, więc odłączamy je od słownika (stają się "custom").
    EventRole.query.filter_by(role_template_id=t.id).update({"role_template_id": None})
    db.session.delete(t)
    log_activity("Usunięto rolę ze słownika", details=name)
    db.session.commit()

    flash(f"Usunięto rolę „{name}” ze słownika.", "info")
    return redirect(url_for("coordinator.panel"))


@coordinator_bp.route("/role-domyslne/zastosuj", methods=["POST"])
@coordinator_required
def apply_default_roles_to_upcoming():
    """Synchronizuje zapotrzebowanie na role we wszystkich nadchodzących
    (jeszcze nieodbytych) sobotach z aktualnie zaznaczonym domyślnym zestawem
    (uwzględniając liczbę slotów na rolę - RoleTemplate.default_slots): dodaje
    brakujące sloty i usuwa nadwyżkę odznaczonych/zmniejszonych ról - o ile nie
    mają aktywnego zgłoszenia (te są pomijane, żeby nie gubić danych)."""
    default_slots_by_template = {t.id: t.default_slots for t in RoleTemplate.query.filter_by(is_default=True).all()}
    all_template_ids = {t.id for t in RoleTemplate.query.all()}

    added, removed, skipped = 0, 0, 0
    # Odwołane edycje pomijamy - nie ma sensu zarządzać zapotrzebowaniem na role,
    # skoro i tak nie przyjmują nowych zgłoszeń.
    upcoming = SaturdayEvent.query.filter(
        SaturdayEvent.date >= date.today(), SaturdayEvent.is_cancelled == False  # noqa: E712
    ).all()

    for event in upcoming:
        existing_by_template = {}
        for er in event.event_roles:
            if er.role_template_id in all_template_ids:
                existing_by_template.setdefault(er.role_template_id, []).append(er)

        relevant_ids = set(default_slots_by_template) | set(existing_by_template)
        for tid in relevant_ids:
            target = default_slots_by_template.get(tid, 0)  # 0 = rola odznaczona z domyślnych
            current = existing_by_template.get(tid, [])

            if len(current) < target:
                t = RoleTemplate.query.get(tid)
                for _ in range(target - len(current)):
                    db.session.add(EventRole(event_id=event.id, role_template_id=t.id, name=t.name, sort_order=t.sort_order))
                    added += 1
            elif len(current) > target:
                free_slots = [er for er in current if er.active_signup is None]
                to_remove = len(current) - target
                for er in free_slots[:to_remove]:
                    db.session.delete(er)
                    removed += 1
                skipped += max(0, to_remove - len(free_slots))

    message = f"Zsynchronizowano {len(upcoming)} nadchodzących sobót: dodano {added}, usunięto {removed} wolnych ról."
    if skipped:
        message += f" Pominięto {skipped} ról z aktywnym zgłoszeniem - usuń je ręcznie po odrzuceniu zgłoszenia."
    log_activity("Zsynchronizowano domyślny zestaw ról", details=message)
    db.session.commit()

    flash(message, "info" if skipped else "success")
    return redirect(url_for("coordinator.panel"))


@coordinator_bp.route("/soboty/dodaj-kolejna", methods=["POST"])
@coordinator_required
def add_next_saturday():
    last = SaturdayEvent.query.order_by(SaturdayEvent.date.desc()).first()
    base_date = last.date if last else date.today() - timedelta(days=1)
    next_date = _next_saturday_after(base_date)

    event = SaturdayEvent(date=next_date)
    db.session.add(event)
    db.session.commit()
    apply_default_roles_to_event(db, event)
    log_activity("Dodano sobotę", event=event)
    db.session.commit()

    flash(f"Dodano sobotę {next_date.strftime('%d.%m.%Y')} wraz z domyślnym zestawem ról.", "success")
    return redirect(url_for("coordinator.panel"))


@coordinator_bp.route("/soboty/dodaj-recznie", methods=["POST"])
@coordinator_required
def add_manual_saturday():
    date_str = request.form.get("date", "")
    is_special = bool(request.form.get("is_special"))
    label = request.form.get("label", "").strip() or None

    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        flash("Podaj poprawną datę.", "error")
        return redirect(url_for("coordinator.panel"))

    # Edycje specjalne (np. Bieg Noworoczny 1 stycznia, Bieg Świętego Szczepana
    # 26 grudnia) mogą wypadać w dowolny dzień tygodnia - zwykłe soboty nadal
    # muszą przypadać w sobotę.
    if not is_special and d.weekday() != SATURDAY_WEEKDAY:
        flash("Wybrana data musi przypadać w sobotę. Jeśli to edycja specjalna (np. 1 stycznia, 26 grudnia), zaznacz odpowiednią opcję.", "error")
        return redirect(url_for("coordinator.panel"))

    if SaturdayEvent.query.filter_by(date=d).first():
        flash("To wydarzenie już istnieje w kalendarzu.", "error")
        return redirect(url_for("coordinator.panel"))

    event = SaturdayEvent(date=d, is_special=is_special, label=label if is_special else None)
    db.session.add(event)
    db.session.commit()
    apply_default_roles_to_event(db, event)
    log_activity(
        "Dodano edycję specjalną" if is_special else "Dodano sobotę",
        details=label,
        event=event,
    )
    db.session.commit()

    what = f"edycję specjalną „{label}”" if (is_special and label) else ("edycję specjalną" if is_special else "sobotę")
    flash(f"Dodano {what} ({d.strftime('%d.%m.%Y')}) wraz z domyślnym zestawem ról.", "success")
    return redirect(url_for("coordinator.panel"))


@coordinator_bp.route("/soboty/<int:event_id>/usun", methods=["POST"])
@coordinator_required
def delete_saturday(event_id):
    event = SaturdayEvent.query.get_or_404(event_id)
    date_label = event.date.strftime("%d.%m.%Y")
    db.session.delete(event)
    # event_id=None, bo sobota (i jej id) za chwilę przestanie istnieć
    log_activity("Usunięto sobotę", details=date_label)
    db.session.commit()
    flash("Sobota została usunięta z kalendarza.", "info")
    return redirect(url_for("coordinator.panel"))


@coordinator_bp.route("/soboty/<int:event_id>/odwolaj", methods=["POST"])
@coordinator_required
def cancel_saturday(event_id):
    """Oznacza edycję jako odwołaną (np. edycja odwołana z powodu pogody) -
    blokuje nowe zgłoszenia, ale niczego nie usuwa. Odwrotność: restore_saturday."""
    event = SaturdayEvent.query.get_or_404(event_id)

    if event.is_cancelled:
        flash("Ta edycja jest już odwołana.", "error")
        return redirect(request.referrer or url_for("coordinator.panel"))

    reason = request.form.get("reason", "").strip() or None
    event.is_cancelled = True
    event.cancel_reason = reason
    log_activity("Odwołano edycję", details=reason, event=event)
    db.session.commit()

    flash(f"Sobota {event.date.strftime('%d.%m.%Y')} została oznaczona jako odwołana. Nowe zgłoszenia są zablokowane.", "info")
    return redirect(request.referrer or url_for("coordinator.panel"))


@coordinator_bp.route("/soboty/<int:event_id>/przywroc", methods=["POST"])
@coordinator_required
def restore_saturday(event_id):
    """Cofa oznaczenie edycji jako odwołanej."""
    event = SaturdayEvent.query.get_or_404(event_id)
    event.is_cancelled = False
    event.cancel_reason = None
    log_activity("Przywrócono edycję", event=event)
    db.session.commit()

    flash(f"Sobota {event.date.strftime('%d.%m.%Y')} została przywrócona - zgłoszenia znów są możliwe.", "success")
    return redirect(request.referrer or url_for("coordinator.panel"))


def _parse_labels(raw):
    """Zamienia 'A, B\\nC' na ['A', 'B', 'C'] - etykiety slotów rozdzielone
    przecinkiem i/lub nowymi liniami, np. czasy przy Wyznaczaniu tempa
    (20 min, 25 min, 30 min...)."""
    return [part.strip() for part in re.split(r"[,\n]", raw) if part.strip()]


@coordinator_bp.route("/sobota/<int:event_id>/role/dodaj", methods=["POST"])
@coordinator_required
def add_role(event_id):
    event = SaturdayEvent.query.get_or_404(event_id)
    if event.is_cancelled:
        flash("Ta edycja jest odwołana - nie można dodawać do niej ról.", "error")
        return redirect(url_for("main.saturday_detail", event_id=event.id))

    template_id = request.form.get("role_template_id", "")
    custom_name = request.form.get("custom_name", "").strip()
    quantity = _parse_slots(request.form.get("quantity"))
    labels = _parse_labels(request.form.get("labels", ""))

    if custom_name:
        name, role_template_id, role_sort_order = custom_name, None, CUSTOM_ROLE_SORT_ORDER
    elif template_id.isdigit():
        t = RoleTemplate.query.get(int(template_id))
        if not t:
            abort(404)
        name, role_template_id, role_sort_order = t.name, t.id, t.sort_order
    else:
        flash("Wybierz rolę z listy lub podaj własną nazwę.", "error")
        return redirect(url_for("main.saturday_detail", event_id=event.id))

    # Etykiety (np. "20 min, 25 min, 30 min") -> osobny slot na każdą, z etykietą
    # wbudowaną w nazwę (żeby export/wyświetlanie/import działały bez zmian).
    # Gdy podane, ignorują pole "ile miejsc" - liczbę slotów wyznacza liczba etykiet.
    slot_names = [f"{name} · {label}" for label in labels] if labels else [name] * quantity

    for slot_name in slot_names:
        db.session.add(EventRole(
            event_id=event.id, role_template_id=role_template_id, name=slot_name, sort_order=role_sort_order,
        ))
    log_activity(
        "Dodano rolę do soboty" if len(slot_names) == 1 else "Dodano role do soboty",
        details=", ".join(slot_names) if labels else (name if len(slot_names) == 1 else f"{name} ×{len(slot_names)}"),
        event=event,
    )
    db.session.commit()
    flash(
        f"Dodano rolę: {slot_names[0]}" if len(slot_names) == 1
        else f"Dodano {len(slot_names)} miejsc: {name}" + (" (z etykietami)" if labels else ""),
        "success",
    )
    return redirect(url_for("main.saturday_detail", event_id=event.id))


@coordinator_bp.route("/role/<int:event_role_id>/usun", methods=["POST"])
@coordinator_required
def remove_role(event_role_id):
    event_role = EventRole.query.get_or_404(event_role_id)
    event_id = event_role.event_id

    if event_role.active_signup is not None:
        flash("Nie można usunąć roli z aktywnym zgłoszeniem. Najpierw odrzuć zgłoszenie.", "error")
    else:
        log_activity("Usunięto rolę z soboty", details=event_role.name, event=event_role.event)
        db.session.delete(event_role)
        db.session.commit()
        flash("Rola została usunięta.", "info")

    return redirect(url_for("main.saturday_detail", event_id=event_id))


@coordinator_bp.route("/role/<int:event_role_id>/przypisz")
@coordinator_required
def manual_assign_form(event_role_id):
    """Formularz ręcznego zablokowania wolnej roli dla osoby, która zgłosiła
    się innym kanałem niż przez panel (telefon, w innej grupie itp.)."""
    event_role = EventRole.query.get_or_404(event_role_id)
    if event_role.active_signup is not None or event_role.event.is_cancelled:
        return render_template("main/_role_row.html", event_role=event_role)

    users = User.query.order_by(User.first_name, User.last_name).all()
    return render_template("main/_manual_assign_form.html", event_role=event_role, users=users, mode="existing", form={})


@coordinator_bp.route("/role/<int:event_role_id>/przypisz", methods=["POST"])
@coordinator_required
def manual_assign(event_role_id):
    event_role = EventRole.query.get_or_404(event_role_id)

    def _form_with_error(message):
        # Odpowiedź na ten endpoint to fragment HTML wstawiany przez HTMX
        # (bez layoutu base.html), więc flash() tu się nie wyświetli -
        # błąd przekazujemy wprost do szablonu formularza.
        users = User.query.order_by(User.first_name, User.last_name).all()
        return render_template(
            "main/_manual_assign_form.html",
            event_role=event_role, users=users, error=message, mode=mode, form=request.form,
        )

    if event_role.active_signup is not None or event_role.event.is_cancelled:
        return render_template("main/_role_row.html", event_role=event_role)

    mode = request.form.get("mode", "existing")

    if mode == "existing":
        user_id = request.form.get("user_id", "")
        user = User.query.get(int(user_id)) if user_id.isdigit() else None
        if not user:
            return _form_with_error("Wybierz zarejestrowanego użytkownika z listy.")
        signup = Signup(
            event_role_id=event_role.id,
            user_id=user.id,
            status=SignupStatus.APPROVED,
            assigned_by_coordinator=True,
        )
    else:
        external_name = request.form.get("external_name", "").strip()
        external_parkrun_id = request.form.get("external_parkrun_id", "").strip().upper()
        if not external_name:
            return _form_with_error("Podaj imię i nazwisko osoby.")
        if external_parkrun_id and not PARKRUN_ID_RE.match(external_parkrun_id):
            return _form_with_error(
                "Kod Uczestnika parkrun musi mieć format np. A1234567 (możesz też zostawić puste pole)."
            )
        signup = Signup(
            event_role_id=event_role.id,
            external_name=external_name,
            external_parkrun_id=external_parkrun_id or None,
            status=SignupStatus.APPROVED,
            assigned_by_coordinator=True,
        )

    db.session.add(signup)
    db.session.flush()  # żeby signup.volunteer_name miało dostęp do zapisanego użytkownika/danych
    log_activity(
        "Zablokowano rolę ręcznie",
        details=f"{event_role.name} - {signup.volunteer_name}",
        event=event_role.event,
    )
    db.session.commit()
    send_signup_approved_email(signup)  # no-op dla zgłoszeń zewnętrznych

    db.session.refresh(event_role)
    return render_template("main/_role_row.html", event_role=event_role)


@coordinator_bp.route("/zgloszenia/<int:signup_id>/zatwierdz", methods=["POST"])
@coordinator_required
def approve_signup(signup_id):
    signup = Signup.query.get_or_404(signup_id)
    signup.status = SignupStatus.APPROVED
    log_activity(
        "Zatwierdzono zgłoszenie",
        details=f"{signup.event_role.name} - {signup.volunteer_name}",
        event=signup.event_role.event,
    )
    db.session.commit()
    send_signup_approved_email(signup)
    return render_template("main/_role_row.html", event_role=signup.event_role)


@coordinator_bp.route("/zgloszenia/<int:signup_id>/odrzuc", methods=["POST"])
@coordinator_required
def reject_signup(signup_id):
    signup = Signup.query.get_or_404(signup_id)
    was_approved = signup.status == SignupStatus.APPROVED
    signup.status = SignupStatus.REJECTED
    log_activity(
        "Cofnięto zatwierdzenie zgłoszenia" if was_approved else "Odrzucono zgłoszenie",
        details=f"{signup.event_role.name} - {signup.volunteer_name}",
        event=signup.event_role.event,
    )
    db.session.commit()
    send_signup_rejected_email(signup)
    return render_template("main/_role_row.html", event_role=signup.event_role)


def _split_row(line):
    """Dzieli wiersz na komórki: najpierw po tabulatorze (standard przy
    wklejaniu z arkusza), a jeśli nie ma tabulatora - po >=2 spacjach
    (na wypadek wklejenia z tabeli renderowanej jako zwykły tekst)."""
    parts = line.split("\t")
    if len(parts) < 2:
        parts = re.split(r" {2,}", line)
    return [p.strip() for p in parts]


def _titlecase_name(name):
    """'Ewa IWASZKO' -> 'Ewa Iwaszko', 'MARCINIAK-SZNAJDER' -> 'Marciniak-Sznajder'
    - kosmetyczna normalizacja imion i nazwisk wklejonych z eksportu (często
    w całości wielkimi literami), z uwzględnieniem nazwisk dwuczłonowych."""
    def cap_word(word):
        return "-".join(part.capitalize() for part in word.split("-"))

    return " ".join(cap_word(part) for part in name.split())


@coordinator_bp.route("/import", methods=["GET", "POST"])
@coordinator_required
def import_roster():
    """Import obsady soboty wklejonej wprost z arkusza/eksportu (dwie kolumny:
    rola, imię i nazwisko wolontariusza - rozdzielone tabulatorem). To już
    potwierdzona, historyczna obsada, więc importowane zgłoszenia trafiają od
    razu jako Zatwierdzone i zewnętrzne (bez kodu parkrun - nie jest tu
    potrzebny). Role, których nie ma jeszcze w słowniku, dopisują się do niego
    automatycznie (jako dodatkowe, nie domyślne)."""
    if request.method == "POST":
        raw = request.form.get("data", "")
        date_str = request.form.get("date", "").strip()

        lines = [line for line in raw.splitlines() if line.strip()]
        if not lines:
            flash("Wklej dane do zaimportowania.", "error")
            return render_template("coordinator/import_roster.html", raw=raw, date_str=date_str)

        event_date = None
        if date_str:
            try:
                event_date = date.fromisoformat(date_str)
            except ValueError:
                flash("Nieprawidłowa data.", "error")
                return render_template("coordinator/import_roster.html", raw=raw, date_str=date_str)

        # Spróbuj rozpoznać nagłówek w pierwszym wierszu, np. "rola\t15 sierpnia 2026".
        first_cells = _split_row(lines[0])
        header_date = parse_pl_date(first_cells[1]) if len(first_cells) > 1 else None
        looks_like_header = first_cells[0].lower() == "rola" or header_date is not None
        data_lines = lines[1:] if looks_like_header else lines
        if event_date is None:
            event_date = header_date

        if event_date is None:
            flash(
                "Nie udało się rozpoznać daty. Podaj ją w polu powyżej albo zostaw w danych "
                "nagłówek w formacie „rola [TAB] 15 sierpnia 2026”.",
                "error",
            )
            return render_template("coordinator/import_roster.html", raw=raw, date_str=date_str)

        rows = []
        for line in data_lines:
            cells = _split_row(line)
            role_name = cells[0].strip() if cells else ""
            volunteer_name = cells[1].strip() if len(cells) > 1 else ""
            if role_name:
                rows.append((role_name, volunteer_name))

        if not rows:
            flash("Brak wierszy z rolami do zaimportowania.", "error")
            return render_template("coordinator/import_roster.html", raw=raw, date_str=date_str)

        event = SaturdayEvent.query.filter_by(date=event_date).first()
        created_event = False
        if not event:
            event = SaturdayEvent(date=event_date, is_special=(event_date.weekday() != SATURDAY_WEEKDAY))
            db.session.add(event)
            db.session.flush()
            created_event = True

        # Wolne (bez aktywnego zgłoszenia) role już istniejące na tej sobocie -
        # importer najpierw je wykorzystuje zamiast tworzyć duplikaty, np. gdy
        # sobota ma już domyślnie wygenerowany, pusty zestaw ról i teraz
        # importujemy do niej faktyczną, potwierdzoną obsadę.
        free_by_name = {}
        for er in event.event_roles:
            if er.active_signup is None:
                free_by_name.setdefault(er.name, []).append(er)

        new_templates = new_roles = reused_roles = new_signups = 0

        for role_name, volunteer_name in rows:
            template = RoleTemplate.query.filter_by(name=role_name).first()
            if not template:
                max_sort = db.session.query(db.func.max(RoleTemplate.sort_order)).scalar() or 0
                template = RoleTemplate(
                    name=role_name, category="support", sort_order=max_sort + 1,
                    is_default=False, default_slots=1,
                )
                db.session.add(template)
                db.session.flush()
                new_templates += 1

            reusable = free_by_name.get(template.name)
            if reusable:
                event_role = reusable.pop(0)
                reused_roles += 1
            else:
                event_role = EventRole(
                    event_id=event.id, role_template_id=template.id, name=template.name,
                    sort_order=template.sort_order,
                )
                db.session.add(event_role)
                db.session.flush()
                new_roles += 1

            if volunteer_name:
                db.session.add(Signup(
                    event_role_id=event_role.id,
                    external_name=_titlecase_name(volunteer_name),
                    status=SignupStatus.APPROVED,
                    assigned_by_coordinator=True,
                ))
                new_signups += 1

        log_activity(
            "Zaimportowano harmonogram",
            details=f"{new_roles} nowych ról, {reused_roles} uzupełnionych, {new_signups} zgłoszeń, {new_templates} nowych ról w słowniku",
            event=event,
        )
        db.session.commit()

        message = (
            f"Zaimportowano sobotę {event.date.strftime('%d.%m.%Y')}"
            f"{' (nowa sobota)' if created_event else ''}: "
            f"{new_roles + reused_roles} ról ({reused_roles} uzupełniło istniejące wolne miejsca), "
            f"{new_signups} przypisanych osób"
        )
        if new_templates:
            message += f", {new_templates} nowych ról dodanych do słownika"
        flash(message + ".", "success")
        return redirect(url_for("main.saturday_detail", event_id=event.id))

    return render_template("coordinator/import_roster.html", raw="", date_str="")
