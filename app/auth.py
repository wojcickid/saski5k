import re

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from .extensions import db
from .models import User, Role

auth_bp = Blueprint("auth", __name__)

PARKRUN_ID_RE = re.compile(r"^A\d{6,8}$")


@auth_bp.route("/rejestracja", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        parkrun_id = request.form.get("parkrun_id", "").strip().upper()

        errors = []
        if not first_name or not last_name:
            errors.append("Podaj imię i nazwisko.")
        if not email or "@" not in email:
            errors.append("Podaj poprawny adres e-mail.")
        if not PARKRUN_ID_RE.match(parkrun_id):
            errors.append(
                "Kod Uczestnika parkrun musi mieć format np. A1234567 (litera A + 6-8 cyfr)."
            )
        if len(password) < 6:
            errors.append("Hasło musi mieć minimum 6 znaków.")
        if password != password2:
            errors.append("Hasła nie są identyczne.")
        if email and User.query.filter_by(email=email).first():
            errors.append("Konto z tym adresem e-mail już istnieje.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("auth/register.html", form=request.form), 400

        user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            parkrun_id=parkrun_id,
            role=Role.VOLUNTEER,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash(f"Witaj, {user.first_name}! Twoje konto zostało utworzone.", "success")
        return redirect(url_for("main.index"))

    return render_template("auth/register.html", form={})


@auth_bp.route("/logowanie", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.is_active:
                flash("To konto zostało zablokowane. Skontaktuj się z administratorem.", "error")
                return render_template("auth/login.html"), 403
            login_user(user)
            flash(f"Witaj ponownie, {user.first_name}!", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("main.index"))
        flash("Nieprawidłowy e-mail lub hasło.", "error")
        return render_template("auth/login.html"), 401

    return render_template("auth/login.html")


@auth_bp.route("/wyloguj")
@login_required
def logout():
    logout_user()
    flash("Zostałeś wylogowany.", "info")
    return redirect(url_for("auth.login"))
