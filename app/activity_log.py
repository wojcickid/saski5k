"""Pomocnicza funkcja do zapisywania wpisów w historii modyfikacji (ActivityLog)."""

from flask_login import current_user

from .extensions import db
from .models import ActivityLog


def log_activity(action, details="", event=None):
    """Dodaje wpis do historii modyfikacji (nie commituje - dołącza się do
    najbliższego db.session.commit() wywołanego przez wywołujący route)."""
    entry = ActivityLog(
        actor_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        details=details,
        event_id=event.id if event is not None else None,
    )
    db.session.add(entry)
    return entry
