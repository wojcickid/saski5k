# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Flask MVP for scheduling parkrun volunteer roles for parkrun Ogród Saski, Lublin (Poland). Server-rendered Jinja2 + Tailwind (CDN) + HTMX, SQLite via Flask-SQLAlchemy, Flask-Login auth, Flask-Mail for async transactional email. All UI copy, routes, and flash messages are in Polish.

## Commands

```bash
# setup (Windows shown; venv/Scripts on Windows, venv/bin on macOS/Linux)
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env

# reset + seed the database (drops and recreates instance/parkrun.db, adds 3 demo
# accounts — admin/koordynator/wolontariusz @parkrun-lublin.pl, password haslo123 —
# plus 6 upcoming Saturdays with the default role set)
rm -f instance/parkrun.db && python seed.py

# run the dev server (http://127.0.0.1:5000, debug=True by default via FLASK_DEBUG)
python run.py
```

There is no test suite, linter, or migration tool configured in this repo — don't assume `pytest`/`ruff`/`flask-migrate` exist.

**Any change to a model in `app/models.py` requires deleting and reseeding `instance/parkrun.db`** (see Database section below) — do this before claiming a schema change works.

### Windows dev-server gotcha

Windows allows a second process to bind the same port without erroring, so starting `python run.py` in the background again without killing the previous one leaves two servers both listening on :5000 — requests then land on whichever one the OS picks, including a stale process with old code/old DB handle. Before starting the dev server, verify nothing is already listening:

```bash
netstat -ano | grep "LISTENING.*:5000"   # must be empty (or only your intended PID) before starting
```

If in doubt, `Stop-Process -Id <pid> -Force` every python.exe process bound to :5000, *then* reset the DB and restart, and re-check `netstat` afterward to confirm exactly one listener.

## Architecture

### Application factory + blueprints

`app/__init__.py:create_app()` wires up `db`/`login_manager`/`mail` (in `extensions.py`, kept separate to avoid circular imports), registers four blueprints, and on every startup runs `db.create_all()` + `seed_role_templates()` (idempotent — inserts the 12 default `RoleTemplate` rows only if the table is empty). Two Jinja filters are registered here too: `pl_date` and `pl_weekday` (hand-rolled Polish month/weekday names — no `locale` dependency).

- `auth.py` — register/login/logout. `PARKRUN_ID_RE = ^A\d{6,8}$` lives here and is imported by `coordinator.py` too (for validating manually-entered parkrun codes).
- `main.py` — everything a logged-in volunteer does, **plus** the public (unauthenticated) routes.
- `coordinator.py` — everything gated behind `coordinator_required` (coordinator or admin).
- `admin.py` — user role management, gated behind `admin_required`.

### Data model

`SaturdayEvent` (a calendar date) → `EventRole` (one demand "slot" for a role on that date, e.g. "Timekeeper slot #1") → `Signup` (one volunteer's claim on a slot).

- **One active signup per `EventRole` at a time.** `EventRole.active_signup` returns the newest `Signup` whose status is `Oczekujące` (pending) or `Zatwierdzone` (approved); `Odrzucone` (rejected) rows are kept for history but don't block re-signup. There is no waitlist — a role reads as taken the moment someone applies, not only once approved. Don't add a second concurrent active signup path without also updating every place that reads `active_signup`.
- **`RoleTemplate` is the reusable dictionary; `EventRole` is a per-Saturday snapshot.** `EventRole.name` is copied from `RoleTemplate.name` at creation time and is the source of truth for display — editing a `RoleTemplate` name only cascades to `EventRole`s that don't yet have an `active_signup` (see `coordinator.edit_role_template`), so past/committed rosters don't silently change. Deleting a `RoleTemplate` nulls `EventRole.role_template_id` on referencing rows rather than cascading delete, for the same reason.
- **`RoleTemplate.is_default`** controls which roles `apply_default_roles_to_event()` (in `seed_data.py`) copies onto a newly-created `SaturdayEvent`. Coordinators toggle this in the collapsible "Domyślny zestaw ról" panel; `coordinator.apply_default_roles_to_upcoming` retroactively syncs already-scheduled future events to match, but skips (never deletes) any `EventRole` with an active signup.
- **`Signup` supports two kinds of volunteer:** a real `User` (via `user_id`) or a coordinator-entered walk-in with no account (`external_name`/`external_parkrun_id`, `user_id` NULL). Never read `signup.user.full_name`/`.parkrun_id` directly — always go through `signup.volunteer_name` / `signup.volunteer_parkrun_id` / `signup.is_external`, which abstract over both cases. `email_utils.py` no-ops for external signups (no email address to send to).
- **`SaturdayEvent.is_special` + `.label`** let an event exist outside the normal Saturday cadence (Polish parkrun tradition runs on 1 January and 26 December regardless of weekday). `coordinator.add_manual_saturday` only enforces the Saturday-weekday check when `is_special` is false.
- **`ActivityLog`** is a flat audit trail (`actor_id`, `action`, `details`, optional `event_id`) written via `activity_log.log_activity()` at the point of mutation (not committed by the helper — it just `db.session.add()`s, so call it before the route's own `db.session.commit()`). Entries with `event_id` set show on that Saturday's own page (`shared/_activity_history.html`, open by default, coordinator-only); entries with `event_id=None` (dictionary edits, saturday add/delete) show in the coordinator panel's global history section (collapsed by default).

### HTMX partial-render pattern

Most coordinator/volunteer actions (signup, cancel, approve, reject, manual-assign, role-template edit) are `hx-post`/`hx-get` endpoints that return a re-rendered fragment (`main/_role_row.html`, `coordinator/_default_role_item.html`, etc.) swapped in via `hx-swap="outerHTML"`, rather than a full page render.

**`flash()` messages don't reach the user on these responses** — the fragment doesn't include `base.html`'s flash block. Routes that can fail validation from an HTMX call (see `coordinator.manual_assign`) instead pass an `error` string straight into the fragment's own template and render it inline. When adding a new HTMX-only mutating endpoint, follow that pattern rather than `flash()`+redirect.

`_role_row.html` (the shared row partial for both the volunteer and coordinator views of a Saturday) branches on `current_user.is_coordinator()` / `current_user.is_authenticated`. It is **not** safe to reuse for the public, unauthenticated pages — `AnonymousUserMixin` has no `is_coordinator()` method and will throw. That's why the public views have their own parallel, button-free templates and routes (see below) instead of reusing the authenticated ones.

### Public vs. authenticated views

`main.index` (`/`) branches on `current_user.is_authenticated`: logged-in users are redirected to `/dashboard`; anonymous visitors get a read-only calendar (`main/public_calendar.html`) with the same per-Saturday counts. `main.public_saturday_detail` (`/publiczny/sobota/<id>`) mirrors `main.saturday_detail` but with `_role_row_public.html` — no action buttons, no parkrun codes ever (those stay coordinator-only even publicly), but full volunteer names for both pending and approved signups (deliberate product decision, matching the public visibility on the official parkrun.pl future-roster page). Keep the public templates free of `current_user.is_coordinator()`-style calls for the reason above.

### Config / email

`app/config.py` reads everything from env vars with defaults; `MAIL_SUPPRESS_SEND` defaults to `true` so the app runs without any SMTP setup (emails are logged, not sent). `email_utils.send_email()` fires a plain `threading.Thread` per email (no task queue) — fine for this MVP's volume, not something to scale up without revisiting.

### Database

No Flask-Migrate/Alembic — `db.create_all()` on startup only creates missing *tables*, it does not add columns to existing ones. Every model field addition so far has required deleting `instance/parkrun.db` and re-running `seed.py`. There is no data-preservation path for schema changes; don't try to hand-write an ALTER TABLE migration unless asked — the established workflow for this project is delete+reseed.
