from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, current_app, abort, request
from flask_login import login_required, current_user

from .extensions import db
from .models import SaturdayEvent, EventRole, Signup, SignupStatus, RoleTemplate, ActivityLog, User
from .activity_log import log_activity
from .auth import PARKRUN_ID_RE

main_bp = Blueprint("main", __name__)

HISTORY_LIMIT = 50


def _role_base_names(event):
    """Unikalne 'bazowe' nazwy ról na tej sobocie (bez etykiet slotów, np. bez
    '· 25 min' przy Wyznaczaniu tempa), w kolejności wyświetlania - do filtra
    'Rola' na stronie soboty (main/saturday_detail.html, public_saturday_detail.html)."""
    seen = set()
    names = []
    for er in event.event_roles:
        base = er.role_template.name if er.role_template else er.name
        if base not in seen:
            seen.add(base)
            names.append(base)
    return names


@main_bp.route("/")
def index():
    """Strona główna: rozdzielacz nawigacyjny (hub), ten sam dla gościa i
    zalogowanego - tylko dostępne karty się różnią. Docelowo, gdy dojdzie coś
    poza samym systemem rezerwacji ról, tu będą kolejne karty."""
    return render_template("main/home.html")


@main_bp.route("/calendar")
def calendar():
    """Kalendarz nadchodzących sobót - jeden URL dla wszystkich. Niezalogowani
    widzą publiczny, tylko-do-odczytu podgląd (kto zgłoszony, co wolne);
    zalogowani widzą tę samą listę z linkami do zgłaszania się."""
    count = current_app.config["UPCOMING_SATURDAYS_COUNT"]
    today = date.today()
    events = (
        SaturdayEvent.query.filter(SaturdayEvent.date >= today)
        .order_by(SaturdayEvent.date)
        .limit(count)
        .all()
    )
    return render_template("main/calendar.html", events=events)


@main_bp.route("/dashboard")
def dashboard_redirect():
    """Stary URL sprzed przeniesienia kalendarza pod /calendar - przekierowanie
    dla wygody (zakładki, przyzwyczajenie)."""
    return redirect(url_for("main.calendar"), code=301)


@main_bp.route("/publiczny/sobota/<int:event_id>")
def public_saturday_detail(event_id):
    """Publiczny, tylko-do-odczytu podgląd obsady na daną sobotę - bez logowania."""
    event = SaturdayEvent.query.get_or_404(event_id)

    prev_event = (
        SaturdayEvent.query.filter(SaturdayEvent.date < event.date)
        .order_by(SaturdayEvent.date.desc())
        .first()
    )
    next_event = (
        SaturdayEvent.query.filter(SaturdayEvent.date > event.date)
        .order_by(SaturdayEvent.date.asc())
        .first()
    )

    return render_template(
        "main/public_saturday_detail.html", event=event, prev_event=prev_event, next_event=next_event,
        role_base_names=_role_base_names(event)
    )


@main_bp.route("/sobota/<int:event_id>")
@login_required
def saturday_detail(event_id):
    event = SaturdayEvent.query.get_or_404(event_id)

    export_lines = []
    for er in event.event_roles:
        s = er.active_signup
        if s and s.status == SignupStatus.APPROVED:
            export_lines.append(f"{er.name} - {s.volunteer_name} - {s.volunteer_parkrun_id}")
    export_text = "\n".join(export_lines)

    role_templates = RoleTemplate.query.order_by(RoleTemplate.sort_order).all()

    history = (
        ActivityLog.query.filter_by(event_id=event.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(HISTORY_LIMIT)
        .all()
    )

    prev_event = (
        SaturdayEvent.query.filter(SaturdayEvent.date < event.date)
        .order_by(SaturdayEvent.date.desc())
        .first()
    )
    next_event = (
        SaturdayEvent.query.filter(SaturdayEvent.date > event.date)
        .order_by(SaturdayEvent.date.asc())
        .first()
    )

    return render_template(
        "main/saturday_detail.html",
        event=event,
        export_text=export_text,
        role_templates=role_templates,
        role_base_names=_role_base_names(event),
        prev_event=prev_event,
        next_event=next_event,
        history=history,
    )


@main_bp.route("/rola/<int:event_role_id>/wiersz")
@login_required
def role_row(event_role_id):
    """Zwraca sam wiersz roli (bez zmian) - używane m.in. do anulowania
    formularza ręcznego przypisania przez koordynatora."""
    event_role = EventRole.query.get_or_404(event_role_id)
    return render_template("main/_role_row.html", event_role=event_role)


@main_bp.route("/zgloszenia/<int:event_role_id>/zglos", methods=["POST"])
@login_required
def signup_role(event_role_id):
    event_role = EventRole.query.get_or_404(event_role_id)
    if event_role.event.is_past or event_role.event.is_cancelled:
        abort(400)

    if event_role.active_signup is not None:
        flash("Ta rola nie jest już wolna.", "error")
    else:
        signup = Signup(event_role_id=event_role.id, user_id=current_user.id, status=SignupStatus.PENDING)
        db.session.add(signup)
        log_activity("Zgłoszono się", details=f"{event_role.name} - {current_user.full_name}", event=event_role.event)
        db.session.commit()
        db.session.refresh(event_role)

    return render_template("main/_role_row.html", event_role=event_role)


@main_bp.route("/zgloszenia/<int:signup_id>/odwolaj", methods=["POST"])
@login_required
def cancel_signup(signup_id):
    signup = Signup.query.get_or_404(signup_id)
    if signup.user_id != current_user.id or signup.status != SignupStatus.PENDING:
        abort(403)

    event_role = signup.event_role
    log_activity("Odwołano zgłoszenie", details=f"{event_role.name} - {current_user.full_name}", event=event_role.event)
    db.session.delete(signup)
    db.session.commit()

    if request.headers.get("HX-Request"):
        db.session.refresh(event_role)
        return render_template("main/_role_row.html", event_role=event_role)

    flash("Zgłoszenie zostało odwołane.", "info")
    return redirect(url_for("main.my_signups"))


@main_bp.route("/moje-zgloszenia")
@login_required
def my_signups():
    signups = (
        Signup.query.filter_by(user_id=current_user.id)
        .join(Signup.event_role)
        .join(EventRole.event)
        .order_by(SaturdayEvent.date.desc())
        .all()
    )
    return render_template("main/my_signups.html", signups=signups)


@main_bp.route("/profil", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        form_type = request.form.get("form_type")

        if form_type == "profile":
            first_name = request.form.get("first_name", "").strip()
            last_name = request.form.get("last_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            parkrun_id = request.form.get("parkrun_id", "").strip().upper()

            errors = []
            if not first_name or not last_name:
                errors.append("Podaj imię i nazwisko.")
            if not email or "@" not in email:
                errors.append("Podaj poprawny adres e-mail.")
            if not PARKRUN_ID_RE.match(parkrun_id):
                errors.append("Kod Uczestnika parkrun musi mieć format np. A1234567 (litera A + 6-8 cyfr).")
            if email and User.query.filter(User.email == email, User.id != current_user.id).first():
                errors.append("Ten adres e-mail jest już używany przez inne konto.")

            if errors:
                for e in errors:
                    flash(e, "error")
            else:
                current_user.first_name = first_name
                current_user.last_name = last_name
                current_user.email = email
                current_user.parkrun_id = parkrun_id
                db.session.commit()
                flash("Dane profilu zostały zaktualizowane.", "success")
            return redirect(url_for("main.profile"))

        elif form_type == "password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            new_password2 = request.form.get("new_password2", "")

            errors = []
            if not current_user.check_password(current_password):
                errors.append("Obecne hasło jest nieprawidłowe.")
            if len(new_password) < 6:
                errors.append("Nowe hasło musi mieć minimum 6 znaków.")
            if new_password != new_password2:
                errors.append("Nowe hasła nie są identyczne.")

            if errors:
                for e in errors:
                    flash(e, "error")
            else:
                current_user.set_password(new_password)
                db.session.commit()
                flash("Hasło zostało zmienione.", "success")
            return redirect(url_for("main.profile"))

        abort(400)

    return render_template("main/profile.html")
