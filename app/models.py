from datetime import datetime, date

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db


class Role:
    """Role użytkownika w systemie."""

    VOLUNTEER = "wolontariusz"
    COORDINATOR = "koordynator"
    ADMIN = "admin"

    CHOICES = [VOLUNTEER, COORDINATOR, ADMIN]

    LABELS = {
        VOLUNTEER: "Wolontariusz",
        COORDINATOR: "Koordynator",
        ADMIN: "Admin",
    }


class SignupStatus:
    """Status zgłoszenia wolontariusza do roli."""

    PENDING = "Oczekujące"
    APPROVED = "Zatwierdzone"
    REJECTED = "Odrzucone"

    CHOICES = [PENDING, APPROVED, REJECTED]


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    parkrun_id = db.Column(db.String(10), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=Role.VOLUNTEER)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    signups = db.relationship(
        "Signup", back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def is_coordinator(self):
        return self.role in (Role.COORDINATOR, Role.ADMIN)

    def is_admin(self):
        return self.role == Role.ADMIN

    def __repr__(self):
        return f"<User {self.email}>"


class RoleTemplate(db.Model):
    """Słownik domyślnych ról wolontariackich parkrun (szablony)."""

    __tablename__ = "role_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    category = db.Column(db.String(20), nullable=False, default="core")  # core / support
    description = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, default=0)
    # Czy ta rola ma być automatycznie dodawana przy tworzeniu nowej soboty.
    # Koordynator zarządza tym w panelu "Domyślny zestaw ról na nowe soboty".
    is_default = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<RoleTemplate {self.name}>"


class SaturdayEvent(db.Model):
    """Pojedyncza sobota (wydarzenie parkrun)."""

    __tablename__ = "saturday_events"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    meeting_time = db.Column(db.String(5), default="08:40")
    run_time = db.Column(db.String(5), default="09:00")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Edycja specjalna: pozwala dodać wydarzenie poza standardową sobotą
    # (polska tradycja parkrun: 1 stycznia i 26 grudnia). `label` to opcjonalna
    # nazwa własna wyświetlana zamiast/obok dnia tygodnia, np. "Bieg Noworoczny".
    is_special = db.Column(db.Boolean, default=False, nullable=False)
    label = db.Column(db.String(120), nullable=True)

    event_roles = db.relationship(
        "EventRole",
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="EventRole.id",
    )

    @property
    def is_past(self):
        return self.date < date.today()

    @property
    def approved_count(self):
        return sum(1 for er in self.event_roles if er.active_signup and er.active_signup.status == SignupStatus.APPROVED)

    @property
    def pending_count(self):
        return sum(1 for er in self.event_roles if er.active_signup and er.active_signup.status == SignupStatus.PENDING)

    @property
    def free_count(self):
        return sum(1 for er in self.event_roles if er.active_signup is None)

    def __repr__(self):
        return f"<SaturdayEvent {self.date}>"


class EventRole(db.Model):
    """Konkretne zapotrzebowanie na rolę w danej sobocie (jeden 'slot')."""

    __tablename__ = "event_roles"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("saturday_events.id"), nullable=False)
    role_template_id = db.Column(db.Integer, db.ForeignKey("role_templates.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False)

    event = db.relationship("SaturdayEvent", back_populates="event_roles")
    role_template = db.relationship("RoleTemplate")
    signups = db.relationship(
        "Signup",
        back_populates="event_role",
        cascade="all, delete-orphan",
        order_by="Signup.created_at",
    )

    @property
    def active_signup(self):
        """Zwraca aktywne zgłoszenie (Oczekujące lub Zatwierdzone), jeśli istnieje."""
        for s in sorted(self.signups, key=lambda s: s.created_at, reverse=True):
            if s.status in (SignupStatus.PENDING, SignupStatus.APPROVED):
                return s
        return None

    def __repr__(self):
        return f"<EventRole {self.name} @ {self.event_id}>"


class Signup(db.Model):
    """Zgłoszenie wolontariusza na daną rolę."""

    __tablename__ = "signups"

    id = db.Column(db.Integer, primary_key=True)
    event_role_id = db.Column(db.Integer, db.ForeignKey("event_roles.id"), nullable=False)
    # user_id jest opcjonalne - zgłoszenie może pochodzić od zarejestrowanego
    # użytkownika (user_id ustawiony) albo zostać wpisane ręcznie przez
    # koordynatora dla osoby zgłoszonej innym kanałem (external_name/-parkrun_id).
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    external_name = db.Column(db.String(160), nullable=True)
    external_parkrun_id = db.Column(db.String(10), nullable=True)
    assigned_by_coordinator = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=SignupStatus.PENDING)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    event_role = db.relationship("EventRole", back_populates="signups")
    user = db.relationship("User", back_populates="signups")

    @property
    def is_external(self):
        """True, jeśli zgłoszenie zostało ręcznie wpisane przez koordynatora
        dla osoby bez konta w systemie (zgłosiła się innym kanałem)."""
        return self.user_id is None

    @property
    def volunteer_name(self):
        return self.user.full_name if self.user else self.external_name

    @property
    def volunteer_parkrun_id(self):
        return self.user.parkrun_id if self.user else self.external_parkrun_id

    @property
    def volunteer_email(self):
        return self.user.email if self.user else None

    def __repr__(self):
        return f"<Signup user={self.user_id} role={self.event_role_id} status={self.status}>"


class ActivityLog(db.Model):
    """Historia modyfikacji (kto, kiedy, co) - role, zgłoszenia, soboty, słownik ról.
    event_id jest opcjonalne: puste dla akcji globalnych (np. zmiany w słowniku ról)."""

    __tablename__ = "activity_log"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    details = db.Column(db.String(500))
    event_id = db.Column(db.Integer, db.ForeignKey("saturday_events.id"), nullable=True)

    actor = db.relationship("User")
    event = db.relationship("SaturdayEvent")

    @property
    def actor_label(self):
        return self.actor.full_name if self.actor else "System"

    def __repr__(self):
        return f"<ActivityLog {self.action} @ {self.created_at}>"
