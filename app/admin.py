from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from .extensions import db
from .models import User, Role

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

    user.role = new_role
    db.session.commit()
    flash(f"Zmieniono rolę użytkownika {user.full_name} na {Role.LABELS[new_role]}.", "success")
    return render_template("admin/_user_row.html", user=user, roles=Role.CHOICES, labels=Role.LABELS)
