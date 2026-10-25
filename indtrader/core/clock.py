"""The NSE clock: India Standard Time, sessions, holidays and expiries.

IST is UTC+05:30 all year (India has no daylight saving).
Normal session: pre-open 09:00-09:15 (orders 09:00-09:08), trading 09:15-15:30.

Holidays come from NSE's holiday master (``it.py refresh``), cached in
``workspace/cache/holidays.json``; the 2026 list is built in as a fallback.
Special sessions (Muhurat trading on Diwali) are not modelled.
"""

import datetime as dt
import logging
from typing import Dict, Optional

from indtrader.core import settings
from indtrader.core.errors import DataError, ValidationError
from indtrader.core.storage import read_json, write_json

log = logging.getLogger(__name__)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
PREOPEN = dt.time(9, 0)
OPEN = dt.time(9, 15)
CLOSE = dt.time(15, 30)
SESSION_MINUTES = 375

# NSE F&O / capital-market trading holidays 2026 (NSE holiday master).
HOLIDAYS_2026: Dict[str, str] = {
    "2026-01-15": "Municipal Corporation Election - Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-02-15": "Mahashivratri",
    "2026-03-03": "Holi",
    "2026-03-21": "Id-Ul-Fitr (Ramadan Eid)",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-08-15": "Independence Day",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-08": "Diwali Laxmi Pujan",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}

_holidays: Optional[Dict[str, str]] = None


def holidays() -> Dict[str, str]:
    """``{'YYYY-MM-DD': description}`` from the cache, else the built-in list."""
    global _holidays
    if _holidays is None:
        cached = read_json(settings.path("cache", "holidays.json"), {}) or {}
        merged = dict(HOLIDAYS_2026)
        merged.update(cached.get("holidays", {}))
        _holidays = merged
    return _holidays


def set_holidays(table: Optional[Dict[str, str]]) -> None:
    """Pin the calendar (tests), or ``None`` to reload from the cache."""
    global _holidays
    _holidays = dict(table) if table is not None else None


def parse_nse_holidays(payload: dict, segment: str = "FO") -> Dict[str, str]:
    """NSE's holiday-master JSON -> ``{'YYYY-MM-DD': description}``."""
    out: Dict[str, str] = {}
    for row in payload.get(segment) or payload.get("CM") or []:
        try:
            day = dt.datetime.strptime(row["tradingDate"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            log.warning("skipping unreadable holiday row %r", row)
            continue
        out[day.isoformat()] = row.get("description", "").strip()
    return out


def store_holidays(table: Dict[str, str]) -> None:
    if not table:
        raise DataError("NSE holiday list came back empty")
    write_json(settings.path("cache", "holidays.json"),
               {"fetched": now_ist().isoformat(timespec="seconds"), "holidays": table})
    set_holidays(None)
    log.info("cached %d NSE holidays", len(table))


# --- time ---------------------------------------------------------------------

def now_ist() -> dt.datetime:
    return dt.datetime.now(IST)


def to_ist(epoch: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(epoch, IST)


def parse_now(text: Optional[str]) -> dt.datetime:
    """``'2026-10-22 10:15'`` (IST) -> aware datetime; ``None`` -> the real clock."""
    if not text:
        return now_ist()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    raise ValidationError("cannot read the time %r (use 'YYYY-MM-DD HH:MM', IST)" % text)


def parse_hhmm(text: str) -> dt.time:
    try:
        hours, minutes = text.strip().split(":")
        return dt.time(int(hours), int(minutes))
    except (ValueError, AttributeError) as exc:
        raise ValidationError("cannot read the time %r (use HH:MM)" % text) from exc


def at(day: dt.date, t: dt.time) -> dt.datetime:
    return dt.datetime.combine(day, t, tzinfo=IST)


def hm(t: dt.time) -> str:
    return t.strftime("%H:%M")


# --- trading days -----------------------------------------------------------------

def is_trading_day(day: dt.date) -> bool:
    return day.weekday() < 5 and day.isoformat() not in holidays()


def holiday_name(day: dt.date) -> Optional[str]:
    if day.weekday() >= 5:
        return "weekend"
    return holidays().get(day.isoformat())


def next_trading_day(day: dt.date, include: bool = False) -> dt.date:
    cursor = day if include else day + dt.timedelta(days=1)
    for _ in range(30):
        if is_trading_day(cursor):
            return cursor
        cursor += dt.timedelta(days=1)
    raise DataError("no trading day found within 30 days of %s" % day)


def prev_trading_day(day: dt.date, include: bool = False) -> dt.date:
    cursor = day if include else day - dt.timedelta(days=1)
    for _ in range(30):
        if is_trading_day(cursor):
            return cursor
        cursor -= dt.timedelta(days=1)
    raise DataError("no trading day found within 30 days before %s" % day)


def market_status(now: dt.datetime) -> dict:
    """``state`` open / pre-open / closed, with a reason and the next open."""
    day, t = now.date(), now.time()
    out = {"now": now.isoformat(timespec="seconds"), "date": day.isoformat()}
    if not is_trading_day(day):
        out.update(state="closed", reason=holiday_name(day) or "holiday")
    elif t < PREOPEN:
        out.update(state="closed", reason="before pre-open")
    elif t < OPEN:
        out.update(state="pre-open", reason="pre-open session (orders 09:00-09:08, matching to 09:15)")
    elif t < CLOSE:
        out.update(state="open", reason="normal market",
                   minutes_to_close=int((at(day, CLOSE) - now).total_seconds() // 60))
    else:
        out.update(state="closed", reason="after the close")
    if out["state"] == "open":
        next_day = next_trading_day(day)
    else:
        next_day = day if (is_trading_day(day) and t < OPEN) else next_trading_day(day)
    out["next_open"] = at(next_day, OPEN).isoformat(timespec="minutes")
    return out


# --- expiries (fallback rule; live expiries come from NSE's option chain) ---------

def weekly_expiry(symbol: str, day: dt.date, cfg: Optional[settings.Settings] = None) -> dt.date:
    """Next weekly expiry on or after ``day`` by the weekday rule, moved to the
    previous trading day when it falls on a holiday."""
    cfg = cfg or settings.load()
    weekday = cfg["fallback_expiry_weekday"].get(symbol.upper())
    if weekday is None:
        return monthly_expiry(symbol, day)
    cursor = day
    for _ in range(3):
        candidate = cursor + dt.timedelta(days=(weekday - cursor.weekday()) % 7)
        expiry = prev_trading_day(candidate, include=True)
        if expiry >= day:
            return expiry
        cursor = candidate + dt.timedelta(days=1)
    raise DataError("could not work out the weekly expiry for %s" % symbol)


def monthly_expiry(symbol: str, day: dt.date) -> dt.date:
    """Last Tuesday of the month (Thursday for BSE indices), previous trading
    day if a holiday; rolls to the next month once passed."""
    weekday = 3 if symbol.upper() in ("SENSEX", "BANKEX") else 1
    year, month = day.year, day.month
    for _ in range(2):
        first_next = dt.date(year + (month == 12), month % 12 + 1, 1)
        last = first_next - dt.timedelta(days=1)
        candidate = last - dt.timedelta(days=(last.weekday() - weekday) % 7)
        expiry = prev_trading_day(candidate, include=True)
        if expiry >= day:
            return expiry
        year, month = first_next.year, first_next.month
    raise DataError("could not work out the monthly expiry for %s" % symbol)


def expiry_close(expiry_date: dt.date) -> dt.datetime:
    """Options expire at the close, 15:30 IST."""
    return at(expiry_date, CLOSE)


def years_to(expiry_dt: dt.datetime, now: dt.datetime) -> float:
    """Calendar time to expiry in years, floored at one minute."""
    seconds = max((expiry_dt - now).total_seconds(), 60.0)
    return seconds / (365.0 * 24 * 3600)
