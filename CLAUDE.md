# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Flask MVP for scheduling parkrun volunteer roles for parkrun Ogród Saski, Lublin (Poland). Server-rendered Jinja2 + Tailwind (CDN) + HTMX, SQLite via Flask-SQLAlchemy, Flask-Login auth, Flask-Mail for async transactional email. All UI copy, routes, and flash messages are in Polish.

## Commands

```bash
# setup (Windows shown; venv/Scripts on Windows, venv/bin on macOS/Linux)
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # includes FLASK_APP=run.py, auto-loaded by `flask` CLI via python-dotenv

# create/update the schema, then seed demo data (3 demo accounts —
# admin/koordynator/wolontariusz @parkrun-lublin.pl, password haslo123 —
# plus 6 upcoming Saturdays with the default role set)
flask db upgrade && python seed.py

# run the dev server (http://127.0.0.1:5000, debug=True by default via FLASK_DEBUG)
python run.py
```

There is no test suite or linter configured in this repo — don't assume `pytest`/`ruff` exist.

**Any change to a model in `app/models.py` requires a migration** (see Database section below) — run `flask db migrate -m "..."`, review the generated file, then `flask db upgrade`. Do this before claiming a schema change works; a bare model edit with no migration is a no-op against the actual DB.

### Windows dev-server gotcha

Windows allows a second process to bind the same port without erroring, so starting `python run.py` in the background again without killing the previous one leaves two servers both listening on :5000 — requests then land on whichever one the OS picks, including a stale process with old code/old DB handle. Before starting the dev server, verify nothing is already listening:

```bash
netstat -ano | grep "LISTENING.*:5000"   # must be empty (or only your intended PID) before starting
```

If in doubt, `Stop-Process -Id <pid> -Force` every python.exe process bound to :5000, *then* reset the DB and restart, and re-check `netstat` afterward to confirm exactly one listener.

## Architecture

### Application factory + blueprints

`app/__init__.py:create_app()` wires up `db`/`login_manager`/`mail`/`migrate` (in `extensions.py`, kept separate to avoid circular imports), registers four blueprints, and on every startup runs `seed_role_templates()` (idempotent — inserts the 12 default `RoleTemplate` rows only if the table is empty), wrapped in a `try/except OperationalError` that just logs a warning telling you to run `flask db upgrade` — schema creation is Alembic's job now, not the app factory's. Two Jinja filters are registered here too: `pl_date` and `pl_weekday` (hand-rolled Polish month/weekday names — no `locale` dependency).

- `auth.py` — register/login/logout. `PARKRUN_ID_RE = ^A\d{6,8}$` lives here and is imported by `coordinator.py` too (for validating manually-entered parkrun codes).
- `main.py` — everything a logged-in volunteer does, **plus** the public (unauthenticated) routes.
- `coordinator.py` — everything gated behind `coordinator_required` (coordinator or admin).
- `admin.py` — user role management, gated behind `admin_required`.

### Data model

`SaturdayEvent` (a calendar date) → `EventRole` (one demand "slot" for a role on that date, e.g. "Timekeeper slot #1") → `Signup` (one volunteer's claim on a slot).

- **One active signup per `EventRole` at a time.** `EventRole.active_signup` returns the newest `Signup` whose status is `Oczekujące` (pending) or `Zatwierdzone` (approved); `Odrzucone` (rejected) rows are kept for history but don't block re-signup. There is no waitlist — a role reads as taken the moment someone applies, not only once approved. Don't add a second concurrent active signup path without also updating every place that reads `active_signup`.
- **`RoleTemplate` is the reusable dictionary; `EventRole` is a per-Saturday snapshot.** `EventRole.name` is copied from `RoleTemplate.name` at creation time and is the source of truth for display — editing a `RoleTemplate` name only cascades to `EventRole`s that don't yet have an `active_signup` (see `coordinator.edit_role_template`), so past/committed rosters don't silently change. Deleting a `RoleTemplate` nulls `EventRole.role_template_id` on referencing rows rather than cascading delete, for the same reason.
- **`RoleTemplate.is_default` + `.default_slots`** control which roles, and how many independent slots of each, `apply_default_roles_to_event()` (in `seed_data.py`) copies onto a newly-created `SaturdayEvent`. Coordinators edit both in the collapsible "Domyślny zestaw ról" panel; `coordinator.apply_default_roles_to_upcoming` retroactively syncs already-scheduled future events to match by *count* (not just presence/absence) — it tops up short counts and trims excess free slots, but never touches an `EventRole` with an active signup. Role names are **not unique** at the `EventRole` level — the same `RoleTemplate` can and does produce multiple sibling `EventRole` rows on one Saturday (e.g. 4× Parkwalker), each independently claimable.
- **`RoleTemplate` names match parkrun.pl's own roster terminology verbatim** (`Mierząc(a)y czas`, `parkwalker`, etc. — see `seed_data.DEFAULT_ROLE_TEMPLATES`) specifically so `coordinator.import_roster` can match imported role names against the dictionary with a plain `RoleTemplate.query.filter_by(name=...)` — no fuzzy matching. If you rename a default role, existing imports/exports that reference the old name will silently start creating new duplicate dictionary entries instead of matching.
- **`EventRole.sort_order`** is a snapshot of `RoleTemplate.sort_order` (or `CUSTOM_ROLE_SORT_ORDER` for un-templated custom-name roles) taken at creation time, set at every `EventRole(...)` call site — `seed_data.apply_default_roles_to_event`, `coordinator.add_role`, `coordinator.apply_default_roles_to_upcoming`, `coordinator.import_roster`. `SaturdayEvent.event_roles`' declarative `order_by` is `(sort_order, name, id)`, which is what makes multiple slots of the same role display adjacently even when added at different times (e.g. a second Timekeeper slot added weeks after the first one still renders next to it, not at the bottom) — if you add a new `EventRole` creation path, set `sort_order` there too or it'll sort to the top (default 0) instead of grouping correctly.
- **Per-slot labels are baked directly into `EventRole.name`, not a separate column.** `coordinator.add_role`'s optional "labels" field (comma/newline-separated) creates one `EventRole` per label with `name = f"{base_name} · {label}"` (e.g. `"Wyznaczanie tempa · 25 min"` for pace-setting slots that each need a different target time). This was a deliberate choice over adding a `slot_label` column: it needed zero migration, and every existing name-keyed mechanism (`_role_row.html` display, EMS export text, `import_roster`'s free-slot-by-name reuse) works on it unchanged since each labeled slot already has a distinct `name`.
- **`Signup` supports two kinds of volunteer:** a real `User` (via `user_id`) or a walk-in with no account (`external_name`/`external_parkrun_id`, `user_id` NULL) — either coordinator-entered (`coordinator.manual_assign`) or produced by `admin.delete_user` snapshotting a deleted account's name/parkrun_id onto their signups before removing the `User` row. Never read `signup.user.full_name`/`.parkrun_id` directly — always go through `signup.volunteer_name` / `signup.volunteer_parkrun_id` / `signup.is_external`, which abstract over both cases. `email_utils.py` no-ops for external signups (no email address to send to).
- **`User.signups` cascade is `"save-update, merge"` only — deliberately no `"delete"`/`"delete-orphan"`.** `admin.delete_user` relies on this: it sets `signup.user = None` (snapshotting the name first) to detach each signup before deleting the `User` row. With `delete-orphan` on that relationship, that exact detach line is (wrongly) interpreted as "orphaned" and Alembic/SQLAlchemy deletes the `Signup` row instead of preserving it — this was a real bug caught during testing. If you ever need to re-add cascading behavior to `User.signups`, re-verify `admin.delete_user` still preserves history (register a throwaway account, sign it up, delete it, and confirm the `Signup` row survives with `user_id=NULL`).
- **`User.is_active`** (default `True`) is deliberately named to match `UserMixin.is_active` — defining a same-named column on the model overrides Flask-Login's property, so `login_user()`'s built-in active check "just works". Blocking someone (`admin.toggle_block_user`) also relies on `load_user()` in `app/__init__.py` returning `None` for inactive users, which forces Flask-Login to treat any of their still-live sessions as logged out on the very next request — don't remove that check thinking `is_active` alone is enough.
- **`SaturdayEvent.is_special` + `.label`** let an event exist outside the normal Saturday cadence (Polish parkrun tradition runs on 1 January and 26 December regardless of weekday). `coordinator.add_manual_saturday` only enforces the Saturday-weekday check when `is_special` is false.
- **`ActivityLog`** is a flat audit trail (`actor_id`, `action`, `details`, optional `event_id`) written via `activity_log.log_activity()` at the point of mutation (not committed by the helper — it just `db.session.add()`s, so call it before the route's own `db.session.commit()`). Entries with `event_id` set show on that Saturday's own page (`shared/_activity_history.html`, open by default, coordinator-only); entries with `event_id=None` (dictionary edits, saturday add/delete) show in the coordinator panel's global history section (collapsed by default).

### HTMX partial-render pattern

Most coordinator/volunteer actions (signup, cancel, approve, reject, manual-assign, role-template edit) are `hx-post`/`hx-get` endpoints that return a re-rendered fragment (`main/_role_row.html`, `coordinator/_default_role_item.html`, etc.) swapped in via `hx-swap="outerHTML"`, rather than a full page render.

**`flash()` messages don't reach the user on these responses** — the fragment doesn't include `base.html`'s flash block. Routes that can fail validation from an HTMX call (see `coordinator.manual_assign`) instead pass an `error` string straight into the fragment's own template and render it inline. When adding a new HTMX-only mutating endpoint, follow that pattern rather than `flash()`+redirect.

`_role_row.html` (the shared row partial for both the volunteer and coordinator views of a Saturday) branches on `current_user.is_coordinator()` / `current_user.is_authenticated`. It is **not** safe to reuse for the public, unauthenticated pages — `AnonymousUserMixin` has no `is_coordinator()` method and will throw. That's why the public views have their own parallel, button-free templates and routes (see below) instead of reusing the authenticated ones.

### Homepage vs. calendar vs. authenticated/public detail views

`main.index` (`/`) is a static navigation hub (`main/home.html`) — the **same route and template for everyone**, not an auth-branching redirect. It renders a grid of cards (Kalendarz always; Moje zgłoszenia/Profil/Panel koordynatora/Użytkownicy conditionally) gated by `current_user.is_authenticated`, `.is_coordinator()`, `.is_admin()` in the template. This replaced an earlier design where `/` immediately redirected authenticated users to `/dashboard` and rendered the calendar directly for anonymous ones — the hub exists so that future features unrelated to role-booking have somewhere to link from without further restructuring `/`. `/dashboard` still resolves (301 redirect to `/calendar`) for old bookmarks/links.

`main.calendar` (`/calendar`) is a **single route for both anonymous and authenticated** visitors (`main/calendar.html`) — no more separate `dashboard.html`/`public_calendar.html` templates. It queries the same upcoming-events list for everyone; the template branches per-card only on which detail route to link to (`main.saturday_detail` vs `main.public_saturday_detail`) and whether to show a login/register prompt. `main.public_saturday_detail` (`/publiczny/sobota/<id>`) still mirrors `main.saturday_detail` separately (not merged) — it uses `_role_row_public.html`: no action buttons, no parkrun codes ever (those stay coordinator-only even publicly), but full volunteer names for both pending and approved signups (deliberate product decision, matching the public visibility on the official parkrun.pl future-roster page). Keep `main/home.html` and the public templates free of unguarded `current_user.is_coordinator()`-style calls — `AnonymousUserMixin` has no such method and will throw; `main/calendar.html` guards every one with `current_user.is_authenticated and ...`.

### Roster import (`coordinator.import_roster`)

Bulk-loads an already-decided Saturday roster pasted as tab-separated `role\tvolunteer name` lines (the format parkrun.pl's own roster export uses) instead of clicking through the UI role-by-role. Key behaviors to preserve if you touch this:
- Date comes from an explicit form field **or** gets parsed out of a `rola\t15 sierpnia 2026`-style header row via `pl_dates.parse_pl_date`; the explicit field wins if both are present.
- It **reuses existing free `EventRole`s matching by name before creating new ones** (tracked per-name in `free_by_name`, popped off as consumed) — this matters because a Saturday typically already has its default role set pre-generated by the time a real roster is imported, so blindly creating new rows would double every role. Only once a name's free-slot pool is exhausted does it fall back to creating a fresh `EventRole`.
- Every imported name becomes an **external, pre-approved** `Signup` (`status=APPROVED`, no `user_id`, no parkrun_id) — this is historical/already-confirmed data, not a new request awaiting review, and parkrun IDs aren't in the source data. Names get run through `_titlecase_name()` (handles `ALL CAPS` and `DOUBLE-BARRELED` surnames) since the export is typically all-uppercase surnames.
- Any role name with no matching `RoleTemplate` gets auto-created (`is_default=False`, `default_slots=1`) rather than rejected — the dictionary grows to match reality instead of requiring the roster to be pre-massaged into existing names first.

Post-login/register redirects (`auth.py`) go to `main.index` (the hub), not straight to the calendar — consistent with treating `/` as the actual landing point users navigate on from now on. The `next` query param (set by `@login_required` bouncing an anonymous visitor to the login page) still takes priority over that default when present.

### Config / email

`app/config.py` reads everything from env vars with defaults; `MAIL_SUPPRESS_SEND` defaults to `true` so the app runs without any SMTP setup (emails are logged, not sent). `email_utils.send_email()` fires a plain `threading.Thread` per email (no task queue) — fine for this MVP's volume, not something to scale up without revisiting.

### Database / migrations

Schema is managed by **Flask-Migrate/Alembic** (`migrations/`, committed to the repo — never gitignore or delete it). `db.create_all()` is **not called anywhere** in the app; the app factory only seeds `RoleTemplate` rows into whatever schema already exists. This replaced an earlier delete-and-reseed workflow (visible in old commit history) after a real-world prompt: the project had just been pushed to a public host for testing, and the user asked how to avoid destroying data on every future schema change.

Workflow for any `app/models.py` change:

```bash
flask db migrate -m "short description"   # autogenerate a revision by diffing models.py against the live DB
# review migrations/versions/<hash>_*.py before applying — autogenerate can miss
# things it can't infer intent for (e.g. a column rename looks like drop+add,
# which silently loses that column's data unless you hand-edit the migration)
flask db upgrade
```

`flask db downgrade` reverts the most recent revision. `FLASK_APP=run.py` must be set in the environment for any `flask db ...` command to find the app (see Commands above) — `run.py` calls `load_dotenv()` before `create_app()`, so `.env` is honored under the `flask` CLI too.

This was verified end-to-end while wiring it up: added a throwaway nullable column, `flask db migrate` + `flask db upgrade`, confirmed via raw SQL that pre-existing rows survived untouched, then `flask db downgrade` + deleted the throwaway migration file + reverted the model change, and confirmed `flask db check` reports no drift. Deploying to any host (the project has been tested on a throwaway free-tier host) must run `flask db upgrade` as part of the deploy step, before the app starts serving — otherwise the host's DB schema falls behind `models.py` the first time a migration is added.

For truly local/throwaway environments, `rm -f instance/parkrun.db && flask db upgrade && python seed.py` still works to get a fully fresh DB — but it is no longer the *required* path for a schema change, only an option.
