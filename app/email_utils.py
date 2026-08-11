"""Asynchroniczna wysyłka e-maili transakcyjnych (Flask-Mail), w osobnym wątku."""

import threading

from flask import current_app, render_template
from flask_mail import Message

from .extensions import mail


def _send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
            app.logger.info(f"E-mail wysłany do: {', '.join(msg.recipients)} (temat: {msg.subject})")
        except Exception as exc:  # pragma: no cover - log i nie przerywaj żądania
            app.logger.error(f"Błąd wysyłki e-maila do {msg.recipients}: {exc}")


def send_email(subject, recipients, html_body):
    """Wysyła e-mail asynchronicznie w osobnym wątku, aby nie blokować żądania HTTP."""
    app = current_app._get_current_object()
    msg = Message(
        subject=subject,
        recipients=recipients,
        html=html_body,
        sender=app.config.get("MAIL_DEFAULT_SENDER"),
    )
    thread = threading.Thread(target=_send_async_email, args=(app, msg), daemon=True)
    thread.start()
    return thread


def send_signup_approved_email(signup):
    """Wysyła potwierdzenie zatwierdzenia zgłoszenia (data, rola, godzina zbiórki).

    Pomijane dla zgłoszeń wpisanych ręcznie przez koordynatora dla osoby bez
    konta w systemie (signup.is_external) - nie znamy wtedy adresu e-mail.
    """
    if signup.is_external:
        return
    event = signup.event_role.event
    user = signup.user
    html = render_template(
        "email/approved.html",
        user=user,
        role_name=signup.event_role.name,
        event=event,
        event_name=current_app.config["EVENT_NAME"],
    )
    send_email(
        subject=f"✅ Zgłoszenie zatwierdzone – {event.date.strftime('%d.%m.%Y')}",
        recipients=[user.email],
        html_body=html,
    )


def send_signup_rejected_email(signup):
    """Wysyła informację o odrzuceniu zgłoszenia. Pomijane dla zgłoszeń zewnętrznych."""
    if signup.is_external:
        return
    event = signup.event_role.event
    user = signup.user
    html = render_template(
        "email/rejected.html",
        user=user,
        role_name=signup.event_role.name,
        event=event,
        event_name=current_app.config["EVENT_NAME"],
    )
    send_email(
        subject=f"Informacja o zgłoszeniu – {event.date.strftime('%d.%m.%Y')}",
        recipients=[user.email],
        html_body=html,
    )
