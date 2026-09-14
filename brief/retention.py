"""Which published brief pages are old enough to delete.

Every run publishes one private claude.ai page holding the complete brief:
balances, masked account numbers, names of people who send money, scans of
physical mail. The page is only useful for as long as a reader might follow
the link in that day's email, so it is kept for RETENTION_DAYS and then
deleted. Holding it longer only widens what a compromised account exposes.

The run lists its artifacts and this module decides which to delete, so the
rule is code with tests rather than a judgement made fresh on every run. It
is deliberately narrow: a page is selected only when it carries the brief's
favicon, a brief's title and a claude.ai address, AND its date parses. Anything
else is left alone - deleting the wrong page cannot be undone, while leaving a
stale one only waits for the next run.
"""
import datetime as _dt
import re as _re

RETENTION_DAYS = 30
BRIEF_FAVICON = "\U0001F4EC"          # 📬, the favicon STEP 3b publishes with
BRIEF_TITLES = ("Morning Brief", "Evening Update")

_DATE = _re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _day(value):
    """The calendar date at the start of `value`, or None when it does not parse."""
    m = _DATE.match(str(value or "").strip())
    if not m:
        return None
    try:
        return _dt.date(*map(int, m.groups()))
    except ValueError:
        return None


def is_brief_page(row):
    """True only for a page this template published.

    >>> is_brief_page({"title": "Morning Brief", "url": "https://claude.ai/code/artifacts/x",
    ...                "favicon": "\U0001F4EC"})
    True
    >>> is_brief_page({"title": "Morning Brief", "url": "https://claude.ai/code/artifacts/x",
    ...                "favicon": "\U0001F4CA"})
    False
    """
    title = str(row.get("title") or "").strip()
    return (str(row.get("favicon") or "").strip() == BRIEF_FAVICON
            and any(title.startswith(t) for t in BRIEF_TITLES)
            and str(row.get("url") or "").startswith("https://claude.ai/"))


def expired(rows, today, days=RETENTION_DAYS):
    """URLs of brief pages last updated more than `days` days before `today`.

    `rows` is the run's artifact listing as dicts with title, url, favicon and
    updated (an ISO date or timestamp). A page exactly `days` old is kept.

    >>> rows = [{"title": "Morning Brief", "url": "https://claude.ai/code/artifacts/a",
    ...          "favicon": "\U0001F4EC", "updated": "2026-08-01T17:30:00Z"},
    ...         {"title": "Morning Brief", "url": "https://claude.ai/code/artifacts/b",
    ...          "favicon": "\U0001F4EC", "updated": "2026-08-14"}]
    >>> expired(rows, "2026-09-13")
    ['https://claude.ai/code/artifacts/a']
    """
    now = _day(today)
    if now is None:
        raise ValueError(f"today must be YYYY-MM-DD, got {today!r}")
    out = []
    for row in rows:
        when = _day(row.get("updated"))
        if when is not None and is_brief_page(row) and (now - when).days > days:
            out.append(row["url"])
    return out
