"""Wspólne mapowania nazw miesięcy/dni tygodnia po polsku - używane zarówno
przez filtry Jinja (pl_date, pl_weekday) jak i parser importu harmonogramu
(potrzebuje kierunku odwrotnego: tekst -> data)."""

import re
from datetime import date

MONTHS_PL = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia",
}
MONTHS_PL_TO_NUM = {name: num for num, name in MONTHS_PL.items()}

WEEKDAYS_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]

_DATE_RE = re.compile(r"^\s*(\d{1,2})\s+(\S+)\s+(\d{4})\s*$")


def format_pl_date(d):
    """Formatuje datę po polsku, np. '16 sierpnia 2026'."""
    if not d:
        return ""
    return f"{d.day} {MONTHS_PL[d.month]} {d.year}"


def format_pl_weekday(d):
    """Zwraca nazwę dnia tygodnia po polsku, np. 'sobota'."""
    if not d:
        return ""
    return WEEKDAYS_PL[d.weekday()]


def parse_pl_date(text):
    """Parsuje datę w formacie '15 sierpnia 2026' -> date(2026, 8, 15).
    Zwraca None, jeśli tekst nie pasuje do formatu (np. to nie jest data,
    tylko nagłówek kolumny) - używane przez importer harmonogramu."""
    if not text:
        return None
    m = _DATE_RE.match(text)
    if not m:
        return None
    day, month_name, year = m.groups()
    month_num = MONTHS_PL_TO_NUM.get(month_name.lower())
    if not month_num:
        return None
    try:
        return date(int(year), month_num, int(day))
    except ValueError:
        return None
