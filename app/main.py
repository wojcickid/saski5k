from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, current_app, abort, request
from flask_login import login_required, current_user

from .extensions import db
from .models import SaturdayEvent, EventRole, Signup, SignupStatus, RoleTemplate, ActivityLog
from .activity_log import log_activity

main_bp = Blueprint("main", __name__)

HISTORY_LIMIT = 50


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    # Niezalogowani widzą publiczny, tylko-do-odczytu podgląd kalendarza
    # (kto jest zgłoszony, jakie miejsca wolne) zamiast od razu ekranu logowania.
    count = current_app.config["UPCOMING_SATURDAYS_COUNT"]
    today = date.today()
    events = (
        SaturdayEvent.query.filter(SaturdayEvent.date >= today)
        .order_by(SaturdayEvent.date)
        .limit(count)
        .all()
    )
    return render_template("main/public_calendar.html", events=events)


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
        "main/public_saturday_detail.html", event=event, prev_event=prev_event, next_event=next_event
    )


@main_bp.route("/dashboard")
@login_required
def dashboard():
    count = current_app.config["UPCOMING_SATURDAYS_COUNT"]
    today = date.today()
    events = (
        SaturdayEvent.query.filter(SaturdayEvent.date >= today)
        .order_by(SaturdayEvent.date)
        .limit(count)
        .all()
    )
    return render_template("main/dashboard.html", events=events)


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
    if event_role.event.is_past:
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
