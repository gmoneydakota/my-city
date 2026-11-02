"""US market clock: sessions, holidays, intraday volume curve."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)


def _easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mo, da = divmod(h + l - 7 * m + 114, 31)
    return date(y, mo, da + 1)


def _nth_weekday(y, m, wd, n):
    d = date(y, m, 1)
    d += timedelta(days=(wd - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_monday(y, m):
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    return d - timedelta(days=d.weekday())


def holidays(y):
    def obs(d):  # observed on Friday if Saturday, Monday if Sunday
        return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d
    h = {
        obs(date(y, 1, 1)), _nth_weekday(y, 1, 0, 3), _nth_weekday(y, 2, 0, 3), _easter(y) - timedelta(days=2),
        _last_monday(y, 5), obs(date(y, 6, 19)), obs(date(y, 7, 4)), _nth_weekday(y, 9, 0, 1),
        _nth_weekday(y, 11, 3, 4), obs(date(y, 12, 25)),
    }
    return h


def is_session(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year) and d not in holidays(d.year + 1 if d.month == 12 and d.day > 25 else d.year)


def prev_session(d: date) -> date:
    d -= timedelta(days=1)
    while not is_session(d):
        d -= timedelta(days=1)
    return d


def phase(now: datetime):
    """('pre'|'open'|'post'|'closed', minutes_since_open)"""
    n = now.astimezone(ET)
    if not is_session(n.date()):
        return "closed", 0
    t = n.time()
    if t < OPEN:
        return "pre", 0
    if t >= CLOSE:
        return "post", 390
    return "open", int((n.hour * 60 + n.minute) - (9 * 60 + 30))


_CURVE = [(0, 0.0), (30, 0.17), (60, 0.26), (120, 0.39), (180, 0.50), (240, 0.62), (300, 0.76), (360, 0.90), (390, 1.0)]


def volume_fraction(minutes: float) -> float:
    """Typical share of the day's volume already traded after `minutes` (U-shaped day)."""
    m = max(0.0, min(390.0, minutes))
    for (m0, f0), (m1, f1) in zip(_CURVE, _CURVE[1:]):
        if m <= m1:
            return f0 + (f1 - f0) * (m - m0) / (m1 - m0)
    return 1.0
