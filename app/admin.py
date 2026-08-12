from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from .extensions import db
from .models import User, Role
from .activity_log import log_activity

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
