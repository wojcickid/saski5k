# 🏃 Wolontariat parkrun Ogród Saski, Lublin — MVP

Lekka aplikacja webowa do rezerwacji ról wolontariuszy na cotygodniowe soboty parkrun.
Zbudowana we Flasku (Application Factory), SQLite/SQLAlchemy, Jinja2 + Tailwind CSS (CDN) + HTMX.

## Stos technologiczny

- **Backend:** Python 3.10+ / Flask (Application Factory Pattern)
- **Baza danych:** SQLite + Flask-SQLAlchemy (ORM)
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

### 3. Inicjalizacja bazy danych + dane demonstracyjne

Baza (SQLite) i domyślny słownik 12 ról parkrun tworzą się automatycznie przy
pierwszym starcie aplikacji. Aby dodatkowo utworzyć konta demo i przykładowe
soboty do przeklikania, uruchom:

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

> **Uwaga:** projekt nie ma narzędzia do migracji bazy (np. Flask-Migrate). Jeśli
> aktualizujesz kod z gita i coś nie działa (błędy `no such column`), usuń plik
> `instance/parkrun.db` i uruchom `python seed.py` ponownie — dane demo odtworzą się
> od nowa. Dotyczy to tylko środowiska lokalnego/deweloperskiego.

### 4. Start aplikacji

```bash
python run.py
```

Aplikacja wystartuje pod adresem: **http://127.0.0.1:5000**

## Kluczowe przepływy

- **Gość (bez logowania):** strona główna pokazuje publiczny, tylko-do-odczytu
  kalendarz nadchodzących sobót — kto jest zgłoszony na jaką rolę i jakie miejsca są
  wolne (imię i nazwisko widoczne, bez kodu parkrun — tak jak na oficjalnej stronie
  parkrun.pl). Przycisk „Zaloguj się” w nagłówku prowadzi do logowania.
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
  Koordynator / Admin).

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
- Brak migracji bazy danych — zmiana modeli wymaga usunięcia `instance/parkrun.db` i
  ponownego seedowania (patrz sekcja „Inicjalizacja bazy danych” wyżej).
- Imię i nazwisko wolontariusza (zarówno zatwierdzonego, jak i oczekującego) jest
  widoczne publicznie, bez logowania — świadoma decyzja, zgodna z tym, jak działa
  oficjalna strona parkrun.pl. Kod uczestnika parkrun pozostaje widoczny wyłącznie dla
  zalogowanego koordynatora/admina.
