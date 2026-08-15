from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from .extensions import db
from .models import User, Role
from .activity_log import log_activity
from .auth import PARKRUN_ID_RE

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin():
            abort(403)
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


@admin_bp.route("/uzytkownicy")
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users, roles=Role.CHOICES, labels=Role.LABELS)


@admin_bp.route("/uzytkownicy/<int:user_id>/rola", methods=["POST"])
@admin_required
def change_role(user_id):
    user = User.query.get_or_404(user_id)
    new_role = request.form.get("role")

    if new_role not in Role.CHOICES:
        abort(400)

    if user.id == current_user.id and new_role != Role.ADMIN:
        flash("Nie możesz odebrać samemu sobie roli administratora.", "error")
        return render_template("admin/_user_row.html", user=user, roles=Role.CHOICES, labels=Role.LABELS)

    old_role = user.role
    user.role = new_role
    if old_role != new_role:
        log_activity(
            "Zmieniono rolę użytkownika",
            details=f"{user.full_name}: {Role.LABELS[old_role]} → {Role.LABELS[new_role]}",
        )
    db.session.commit()
    flash(f"Zmieniono rolę użytkownika {user.full_name} na {Role.LABELS[new_role]}.", "success")
    return render_template("admin/_user_row.html", user=user, roles=Role.CHOICES, labels=Role.LABELS)


@admin_bp.route("/uzytkownicy/<int:user_id>/zablokuj", methods=["POST"])
@admin_required
def toggle_block_user(user_id):
    """Blokuje/odblokowuje logowanie danego użytkownika. Nie rusza jego
    dotychczasowych zgłoszeń - to tylko zamknięcie dostępu do konta."""
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("Nie możesz zablokować samego siebie.", "error")
        return render_template("admin/_user_row.html", user=user, roles=Role.CHOICES, labels=Role.LABELS)

    user.is_active = not user.is_active
    log_activity(
        "Zablokowano użytkownika" if not user.is_active else "Odblokowano użytkownika",
        details=user.full_name,
    )
    db.session.commit()

    flash(
        f"Użytkownik {user.full_name} został {'zablokowany' if not user.is_active else 'odblokowany'}.",
        "info",
    )
    return render_template("admin/_user_row.html", user=user, roles=Role.CHOICES, labels=Role.LABELS)


@admin_bp.route("/uzytkownicy/<int:user_id>")
@admin_required
def user_row(user_id):
    """Zwraca sam wiersz użytkownika bez zmian - używane do anulowania edycji."""
    user = User.query.get_or_404(user_id)
    return render_template("admin/_user_row.html", user=user, roles=Role.CHOICES, labels=Role.LABELS)


@admin_bp.route("/uzytkownicy/<int:user_id>/edytuj")
@admin_required
def edit_user_form(user_id):
    user = User.query.get_or_404(user_id)
    return render_template("admin/_user_row_edit.html", user=user, form={})


@admin_bp.route("/uzytkownicy/<int:user_id>/edytuj", methods=["POST"])
@admin_required
def edit_user(user_id):
    """Pozwala adminowi ręcznie poprawić dane konta i/lub ustawić nowe hasło
    wprost (bez maila/linku resetującego) - przy ~20 użytkownikach prościej
    obsłużyć zapomniane hasło ręcznie niż spinać osobny mechanizm resetu."""
    user = User.query.get_or_404(user_id)

    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    parkrun_id = request.form.get("parkrun_id", "").strip().upper()
    new_password = request.form.get("new_password", "")

    error = None
    if not first_name or not last_name:
        error = "Podaj imię i nazwisko."
    elif not email or "@" not in email:
        error = "Podaj poprawny adres e-mail."
    elif not PARKRUN_ID_RE.match(parkrun_id):
        error = "Kod Uczestnika parkrun musi mieć format np. A1234567 (litera A + 6-8 cyfr)."
    elif new_password and len(new_password) < 6:
        error = "Nowe hasło musi mieć minimum 6 znaków."
    elif User.query.filter(User.email == email, User.id != user.id).first():
        error = "Konto z tym adresem e-mail już istnieje."

    if error:
        return render_template("admin/_user_row_edit.html", user=user, form=request.form, error=error)

    user.first_name, user.last_name = first_name, last_name
    user.email, user.parkrun_id = email, parkrun_id
    details = user.full_name
    if new_password:
        user.set_password(new_password)
        details += " (w tym reset hasła)"
    log_activity("Edytowano dane użytkownika (admin)", details=details)
    db.session.commit()

    flash(f"Zapisano zmiany danych użytkownika {user.full_name}.", "success")
    return render_template("admin/_user_row.html", user=user, roles=Role.CHOICES, labels=Role.LABELS)


@admin_bp.route("/uzytkownicy/<int:user_id>/usun", methods=["POST"])
@admin_required
def delete_user(user_id):
    """Usuwa konto użytkownika. Jego dotychczasowe zgłoszenia (Signup) NIE są
    kasowane - zostają odłączone od konta i zachowane jako zgłoszenie
    "zewnętrzne" (imię, nazwisko i kod parkrun zapisane wprost na zgłoszeniu),
    dokładnie tak samo jak w przypadku wolontariusza bez konta wpisanego ręcznie
    przez koordynatora. Dzięki temu historia obsady sobót się nie gubi."""
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("Nie możesz usunąć samego siebie.", "error")
        return redirect(url_for("admin.users"))

    name = user.full_name
    for signup in list(user.signups):
        signup.external_name = user.full_name
        signup.external_parkrun_id = user.parkrun_id
        signup.user = None  # odłącza od kolekcji user.signups, żeby cascade delete-orphan go nie skasował

    db.session.delete(user)
    log_activity("Usunięto użytkownika", details=name)
    db.session.commit()

    flash(f"Użytkownik {name} został usunięty. Jego dotychczasowe zgłoszenia zostały zachowane w historii.", "info")
    return redirect(url_for("admin.users"))
