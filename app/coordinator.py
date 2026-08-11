from datetime import date, timedelta
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from .extensions import db
from .models import SaturdayEvent, EventRole, RoleTemplate, Signup, SignupStatus, User, ActivityLog
from .seed_data import apply_default_roles_to_event
from .email_utils import send_signup_approved_email, send_signup_rejected_email
from .auth import PARKRUN_ID_RE
from .activity_log import log_activity

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


@coordinator_bp.route("/role-domyslne/dodaj", methods=["POST"])
@coordinator_required
def add_role_template():
    """Dodaje nową rolę do słownika (dostępną też do jednorazowego dodania na sobotę)."""
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "support")
    description = request.form.get("description", "").strip() or None

    if not name:
        flash("Podaj nazwę roli.", "error")
        return redirect(url_for("coordinator.panel"))
    if category not in ("core", "support"):
        category = "support"
    if RoleTemplate.query.filter_by(name=name).first():
        flash("Rola o takiej nazwie już istnieje w słowniku.", "error")
        return redirect(url_for("coordinator.panel"))

    max_sort = db.session.query(db.func.max(RoleTemplate.sort_order)).scalar() or 0
    t = RoleTemplate(name=name, category=category, description=description, sort_order=max_sort + 1)
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
    t.name, t.category, t.description = name, category, description
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
    (jeszcze nieodbytych) sobotach z aktualnie zaznaczonym domyślnym zestawem:
    dodaje brakujące domyślne role i usuwa odznaczone - o ile nie mają
    aktywnego zgłoszenia (te są pomijane, żeby nie gubić danych)."""
    default_ids = {t.id for t in RoleTemplate.query.filter_by(is_default=True).all()}
    all_template_ids = {t.id for t in RoleTemplate.query.all()}

    added, removed, skipped = 0, 0, 0
    upcoming = SaturdayEvent.query.filter(SaturdayEvent.date >= date.today()).all()

    for event in upcoming:
        existing_by_template = {
            er.role_template_id: er for er in event.event_roles if er.role_template_id in all_template_ids
        }

        for tid in default_ids - existing_by_template.keys():
            t = RoleTemplate.query.get(tid)
            db.session.add(EventRole(event_id=event.id, role_template_id=t.id, name=t.name))
            added += 1

        for tid in existing_by_template.keys() - default_ids:
            er = existing_by_template[tid]
            if er.active_signup is None:
                db.session.delete(er)
                removed += 1
            else:
                skipped += 1

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


@coordinator_bp.route("/sobota/<int:event_id>/role/dodaj", methods=["POST"])
@coordinator_required
def add_role(event_id):
    event = SaturdayEvent.query.get_or_404(event_id)
    template_id = request.form.get("role_template_id", "")
    custom_name = request.form.get("custom_name", "").strip()

    if custom_name:
        name, role_template_id = custom_name, None
    elif template_id.isdigit():
        t = RoleTemplate.query.get(int(template_id))
        if not t:
            abort(404)
        name, role_template_id = t.name, t.id
    else:
        flash("Wybierz rolę z listy lub podaj własną nazwę.", "error")
        return redirect(url_for("main.saturday_detail", event_id=event.id))

    db.session.add(EventRole(event_id=event.id, role_template_id=role_template_id, name=name))
    log_activity("Dodano rolę do soboty", details=name, event=event)
    db.session.commit()
    flash(f"Dodano rolę: {name}", "success")
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
    if event_role.active_signup is not None:
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

    if event_role.active_signup is not None:
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
