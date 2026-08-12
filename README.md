# 🏃 Wolontariat parkrun Ogród Saski, Lublin — MVP

Lekka aplikacja webowa do rezerwacji ról wolontariuszy na cotygodniowe soboty parkrun.
Zbudowana we Flasku (Application Factory), SQLite/SQLAlchemy, Jinja2 + Tailwind CSS (CDN) + HTMX.

## Stos technologiczny

- **Backend:** Python 3.10+ / Flask (Application Factory Pattern)
- **Baza danych:** SQLite + Flask-SQLAlchemy (ORM) + Flask-Migrate/Alembic (migracje schematu)
- **Frontend:** Jinja2 + Tailwind CSS (CDN) + HTMX (dynamiczne akcje bez przeładowania strony)
- **Autoryzacja:** Flask-Login
- **E-mail:** Flask-Mail, wysyłka asynchroniczna w osobnym wątku

## Struktura projektu

```
volo_parkrun/
├── app/
│   ├── __init__.py          # application factory (create_app), filtry Jinja (pl_date, pl_weekday)
│   ├── config.py             # konfiguracja (zmienne środowiskowe)
│   ├── extensions.py         # instancje db / login_manager / mail
│   ├── models.py             # modele SQLAlchemy (User, SaturdayEvent, EventRole, Signup, RoleTemplate, ActivityLog)
│   ├── seed_data.py          # domyślny słownik ról parkrun + funkcje seedujące
│   ├── email_utils.py        # asynchroniczna wysyłka e-maili (Flask-Mail w wątku)
│   ├── activity_log.py       # helper do zapisywania historii modyfikacji
│   ├── auth.py                # blueprint: rejestracja / logowanie / wylogowanie
│   ├── main.py                # blueprint: kalendarz (publiczny + wewnętrzny), szczegóły soboty, zgłoszenia
│   ├── coordinator.py         # blueprint: panel koordynatora (soboty, słownik ról, akceptacje, historia)
│   ├── admin.py               # blueprint: zarządzanie użytkownikami/rolami systemowymi
│   └── templates/             # szablony Jinja2 (base, auth, main, coordinator, admin, email, shared)
├── migrations/                 # historia migracji Alembic/Flask-Migrate — CZĘŚĆ REPO, nie usuwać
├── instance/                  # tu tworzy się plik parkrun.db (SQLite) — poza repo
├── run.py                     # punkt wejścia: python run.py
├── seed.py                    # skrypt seedujący konta demo + przykładowe soboty
├── requirements.txt
├── .env.example
├── CLAUDE.md                  # notatki architektoniczne dla AI/Claude Code
└── README.md
```

## Uruchomienie lokalne

### 1. Środowisko wirtualne i zależności

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Konfiguracja

Skopiuj `.env.example` do `.env` i (opcjonalnie) uzupełnij dane SMTP. Domyślnie
`MAIL_SUPPRESS_SEND=true`, więc aplikacja **działa od razu bez konfiguracji poczty** —
e-maile są tylko logowane w konsoli zamiast wysyłane.

```bash
copy .env.example .env      # Windows
cp .env.example .env        # macOS/Linux
```

### 3. Baza danych: migracje + dane demonstracyjne

Schemat bazy jest zarządzany przez **Flask-Migrate/Alembic** (katalog `migrations/`,
wersjonowany w repo) — `db.create_all()` **nie jest już używane**. Polecenia
`flask db ...` potrzebują zmiennej `FLASK_APP=run.py` — jest już w `.env.example`
(a `flask` CLI wczytuje `.env` automatycznie), więc jeśli skopiowałeś `.env` w kroku
2, nic więcej nie musisz robić.

Utwórz schemat (za pierwszym razem oraz po każdym `git pull`, który dodał nowe
pliki w `migrations/versions/`):

```bash
flask db upgrade
```

Następnie (opcjonalnie) załaduj dane demonstracyjne — konta i przykładowe soboty:

```bash
python seed.py
```

Utworzy to 3 konta (hasło dla wszystkich: `haslo123`):

| Rola         | E-mail                              |
|--------------|--------------------------------------|
| Admin        | admin@parkrun-lublin.pl              |
| Koordynator  | koordynator@parkrun-lublin.pl        |
| Wolontariusz | wolontariusz@parkrun-lublin.pl       |

oraz 6 nadchodzących sobót z domyślnym zestawem ról.

**Jak dodać nowe pole/model w przyszłości, bez utraty danych** (patrz sekcja
„Znane ograniczenia" niżej — to był kiedyś duży problem, teraz nie jest):

```bash
# 1. Zmień model(e) w app/models.py
# 2. Wygeneruj migrację (Alembic porówna modele z aktualnym stanem bazy):
flask db migrate -m "krótki opis zmiany"
# 3. PRZEJRZYJ wygenerowany plik w migrations/versions/ - autogenerate bywa
#    niedoskonały (np. nie wykrywa zmiany nazwy kolumny - widzi to jako
#    usunięcie + dodanie, co skasowałoby dane w tej kolumnie).
# 4. Zastosuj migrację:
flask db upgrade
```

Migrację można też cofnąć: `flask db downgrade`. Plik migracji commituje się do
repo razem ze zmianą modelu — to on jest teraz źródłem prawdy o schemacie, nie
`db.create_all()`.

### 4. Start aplikacji

```bash
python run.py
```

Aplikacja wystartuje pod adresem: **http://127.0.0.1:5000**

## Wdrożenie na hosting

Przy wdrażaniu (np. po `git push` na hosting podpięty pod GitHuba) upewnij się, że
krok budowania/startu uruchamia `flask db upgrade` **przed** startem serwera
aplikacji (`FLASK_APP=run.py` musi być ustawione w środowisku) — to on tworzy/aktualizuje
schemat bazy na hostingu, tak samo jak lokalnie. Bez tego kroku baza na hostingu
zostanie z pustym/starym schematem po każdej zmianie modeli.

## Nawigacja: strona główna i kalendarz

Strona główna (`/`) to **rozdzielacz nawigacyjny (hub)** — ten sam dla gościa i
zalogowanego, tylko dostępne karty się różnią (Kalendarz zawsze; Moje zgłoszenia/
Profil/Panel koordynatora/Użytkownicy w zależności od tego, kim jesteś). To
świadoma decyzja pod kątem rozwoju: gdy w przyszłości dojdzie coś poza samym
systemem rezerwacji ról, będzie już gdzie podpiąć kolejną kartę bez przebudowy `/`.

Sam kalendarz nadchodzących sobót przeniósł się pod **`/calendar`** (stary URL
`/dashboard` nadal działa — przekierowuje na `/calendar`) i jest jednym, wspólnym
widokiem dla gościa i zalogowanego: gość widzi wersję tylko-do-odczytu (kto jest
zgłoszony, jakie miejsca wolne — imię i nazwisko widoczne, bez kodu parkrun, tak
jak na oficjalnej stronie parkrun.pl), zalogowany dodatkowo może się zgłaszać.

## Kluczowe przepływy

- **Wolontariusz:** rejestracja (imię, nazwisko, e-mail, hasło, kod parkrun w formacie
  `A1234567`) → kalendarz najbliższych sobót → wybór roli → zgłoszenie (status *Oczekujące*)
  → historia zgłoszeń w „Moje zgłoszenia” → możliwość odwołania, dopóki status jest *Oczekujące*.
  Na stronie danej soboty można przechodzić do poprzedniej/następnej soboty strzałkami.
- **Koordynator:** panel → generowanie kolejnych sobót (automatycznie lub ręcznie, z domyślnym
  zestawem ról) → dodawanie/usuwanie ról na daną sobotę → akceptacja/odrzucenie zgłoszeń
  jednym kliknięciem (HTMX, bez przeładowania strony) → e-mail do wolontariusza wysyłany
  automatycznie w tle → przycisk „Kopiuj listę zatwierdzonych” generujący tekst w formacie
  `[Rola] - [Imię Nazwisko] - [Kod Uczestnika]` gotowy do wklejenia do panelu EMS.
  Koordynator może też **ręcznie zablokować rolę** dla osoby, która zgłosiła się innym
  kanałem (telefon, Facebook) — wybierając zarejestrowanego użytkownika albo wpisując
  imię i nazwisko osoby bez konta. Na stronie każdej soboty widoczna jest **historia
  modyfikacji** (kto, kiedy, co zrobił).
- **Admin:** `/admin/uzytkownicy` → zmiana roli dowolnego użytkownika (Wolontariusz /
  Koordynator / Admin), **blokowanie/odblokowanie konta** (zablokowany nie może się
  zalogować, a jeśli akurat miał aktywną sesję, zostaje z niej wylogowany), oraz
  **usuwanie konta** — dotychczasowe zgłoszenia usuniętej osoby nie znikają, tylko
  zostają zapisane jako „zewnętrzne” (imię, nazwisko, kod parkrun na sztywno na
  zgłoszeniu), żeby nie gubić historii obsady sobót. Admin nie może zablokować ani
  usunąć samego siebie.
- **Profil (`/profil`, każdy zalogowany):** edycja własnych danych (imię, nazwisko,
  e-mail, kod parkrun) oraz zmiana hasła (wymaga podania obecnego hasła).

## Domyślny słownik ról (seedowany automatycznie)

**Obowiązkowe:** Koordynator spotkania (Run Director), Pomiar czasu (Timekeeper),
Wydawanie tokenów (Finish Tokens), Skanowanie kodów uczestników (Barcode Scanner),
Biegacz zamykający (Tail Walker), Odprawa debiutantów (First Timers Welcome).

**Dodatkowe:** Wolontariusz na trasie (Marshal), Fotograf, Sortowanie tokenów,
Instruktaż/Przechowywanie sprzętu, Autor raportu z biegu, Parkwalker.

Przy tworzeniu nowej soboty system automatycznie tworzy po jednym „slocie” dla
każdej roli oznaczonej jako domyślna — koordynator może dowolnie dodać kolejne sloty
tej samej roli (np. drugiego skanera) lub usunąć niepotrzebne (o ile nie mają
aktywnego zgłoszenia).

W panelu koordynatora, w zwijanej sekcji **„Domyślny zestaw ról na nowe soboty”**
(domyślnie schowanej — to ustawienie na rzadko), można:
- zaznaczać/odznaczać, które role z powyższego słownika mają trafiać automatycznie do
  nowo tworzonych sobót,
- **dodawać własne role do słownika**, edytować istniejące (nazwa, kategoria, opis) lub
  je usuwać,
- kliknięciem „Zastosuj do nadchodzących sobót” zsynchronizować już zaplanowane soboty
  z aktualnym wyborem (role z aktywnym zgłoszeniem nigdy nie są automatycznie usuwane).

## Edycje specjalne (poza standardową sobotą)

Poza cotygodniowymi sobotami polska tradycja parkrun obejmuje dwie dodatkowe edycje w
roku, niezależnie od dnia tygodnia: **1 stycznia** (Bieg Noworoczny) i **26 grudnia**
(Bieg Świętego Szczepana). W formularzu „Dodaj ręcznie” w panelu koordynatora można
zaznaczyć „To edycja specjalna”, żeby ominąć wymóg soboty i nadać wydarzeniu własną
nazwę — dostępne są też przyciski szybkiego dodania dla obu tych dat. Edycje specjalne
są oznaczone gwiazdką ⭐ w kalendarzu i na liście sobót.

## Znane ograniczenia MVP (świadome uproszczenia)

- Brak ochrony CSRF na formularzach (Flask-WTF) — do dodania przed produkcją.
- Brak resetu hasła / weryfikacji e-mail.
- Jedna aktywna (oczekująca/zatwierdzona) rezerwacja na rolę jednocześnie — kolejne
  zgłoszenia są możliwe dopiero po zwolnieniu roli.
- Wysyłka e-mail przez `MAIL_SUPPRESS_SEND=true` domyślnie tylko loguje wiadomość w
  konsoli; do realnej wysyłki skonfiguruj dane SMTP (np. Gmail App Password, Resend
  SMTP, SendGrid) w `.env` i ustaw `MAIL_SUPPRESS_SEND=false`.
- Imię i nazwisko wolontariusza (zarówno zatwierdzonego, jak i oczekującego) jest
  widoczne publicznie, bez logowania — świadoma decyzja, zgodna z tym, jak działa
  oficjalna strona parkrun.pl. Kod uczestnika parkrun pozostaje widoczny wyłącznie dla
  zalogowanego koordynatora/admina.
