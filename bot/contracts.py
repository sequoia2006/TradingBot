"""Futures contract helpers: resolve the MNQ front-month symbol (e.g. MNQZ6)."""
from __future__ import annotations

from datetime import date, timedelta

QUARTERLY = {3: "H", 6: "M", 9: "U", 12: "Z"}


def third_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)  # first Friday
    return d + timedelta(weeks=2)


def front_month(root: str, today: date, roll_days: int = 8) -> str:
    """Quarterly front month, rolling `roll_days` before the 3rd-Friday expiry.

    CME equity-index volume typically moves to the next contract ~8 days
    before expiry (the Thursday of the prior week).
    """
    year, month = today.year, today.month
    while True:
        q = next(m for m in sorted(QUARTERLY) if m >= month)
        expiry = third_friday(year, q)
        if today < expiry - timedelta(days=roll_days):
            return f"{root}{QUARTERLY[q]}{year % 10}"
        month = q + 1
        if month > 12:
            month, year = 1, year + 1
