"""Which published brief pages are old enough to delete.

Every run publishes one private claude.ai page holding the complete brief:
balances, masked account numbers, names of people who send money, scans of
physical mail. The page is only useful for as long as a reader might follow
the link in that day's email, so it is kept for RETENTION_DAYS and then
deleted. Holding it longer only widens what a compromised account exposes.

The rule is code with tests rather than a judgement made fresh on every run,
and it is deliberately narrow: deleting the wrong page cannot be undone, while
leaving a stale one only waits for the next run. Pages are found two ways,
because neither is enough alone:

* The artifact LISTING, read exactly as the Artifact tool prints it. A row is
  selected only with the brief's favicon, a brief's title, a claude.ai address
  and a date that parses. But the listing returns at most 50 artifacts, newest
  first, and a morning plus an evening brief a day pushes a 30-day-old page off
  the end of it - so the listing alone would never see the pages it exists to
  delete.
* The SENT BRIEFS. Every brief's text copy ends with the page's address on its
  "Full brief, never truncated:" line, and the sent folder does not age out.
  A sent message is used only when its subject is a brief's, its date parses,
  and that line names a claude.ai address.
"""
import datetime as _dt
import json as _json
import re as _re

RETENTION_DAYS = 30
BRIEF_FAVICON = "\U0001F4EC"          # 📬, the favicon STEP 3b publishes with
BRIEF_TITLES = ("Morning Brief", "Evening Update")
PAGE_HOST = "https://claude.ai/"
LINK_LABEL = "Full brief, never truncated: "

_DATE = _re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# "- (mine) Morning Brief — https://claude.ai/code/artifact/… — favicon 📬 — updated 2026-09-13"
_LISTING_ROW = _re.compile(
    r"^\s*-\s*\(mine\)\s+(?P<title>.+?)\s+—\s+(?P<url>https?://\S+)"
    r"\s+—\s+favicon\s+(?P<favicon>\S+)\s+—\s+updated\s+(?P<updated>\S+)\s*$")
_TEST_PREFIX = "[TEST] "


def _day(value):
    """The calendar date at the start of `value`, or None when it does not parse."""
    m = _DATE.match(str(value or "").strip())
    if not m:
        return None
    try:
        return _dt.date(*map(int, m.groups()))
    except ValueError:
        return None


def _is_brief_title(title):
    title = str(title or "").strip()
    if title.startswith(_TEST_PREFIX):
        title = title[len(_TEST_PREFIX):]
    return any(title.startswith(t) for t in BRIEF_TITLES)


def is_brief_page(row):
    """True only for a page this template published.

    >>> is_brief_page({"title": "Morning Brief", "url": "https://claude.ai/code/artifact/x",
    ...                "favicon": "\U0001F4EC"})
    True
    >>> is_brief_page({"title": "Morning Brief", "url": "https://claude.ai/code/artifact/x",
    ...                "favicon": "\U0001F4CA"})
    False
    """
    return (str(row.get("favicon") or "").strip() == BRIEF_FAVICON
            and _is_brief_title(row.get("title"))
            and str(row.get("url") or "").startswith(PAGE_HOST))


def parse_listing(text):
    """Rows from the Artifact tool's listing, exactly as it prints it.

    Only the owner's own rows count; a shared artifact is never ours to delete.
    Lines that are not rows (the "N published artifacts" header) are skipped.

    >>> parse_listing("5 published artifacts:\\n- (mine) Morning Brief — "
    ...               "https://claude.ai/code/artifact/a — favicon \U0001F4EC — updated 2026-08-01")
    [{'title': 'Morning Brief', 'url': 'https://claude.ai/code/artifact/a', 'favicon': '\U0001F4EC', 'updated': '2026-08-01'}]
    """
    return [m.groupdict() for m in map(_LISTING_ROW.match, str(text).splitlines()) if m]


def row_from_sent(message):
    """A page row from one sent brief (a Gmail get_message result), or None.

    Its favicon is the brief's by construction: only STEP 3b's page is ever
    linked from that line.
    """
    if not isinstance(message, dict):
        return None
    subject = message.get("subject")
    body = message.get("plaintextBody") or message.get("plaintext_body") or ""
    urls = [line[len(LINK_LABEL):].strip() for line in str(body).splitlines()
            if line.startswith(LINK_LABEL)]
    if not (_is_brief_title(subject) and urls and urls[-1].startswith(PAGE_HOST)):
        return None
    return {"title": str(subject), "url": urls[-1], "favicon": BRIEF_FAVICON,
            "updated": message.get("date")}


def load_rows(text):
    """Rows from a file's text: a JSON list of rows, sent message(s), or a listing."""
    stripped = str(text).lstrip()
    listed = parse_listing(stripped)
    if listed or not ("{" in stripped or stripped[:1] == "["):
        return listed
    # A saved tool result can carry a line of preamble before its JSON.
    start = 0 if stripped[:1] in "[{" else stripped.find("{")
    data, _ = _json.JSONDecoder().raw_decode(stripped[start:])
    items = data.get("messages", [data]) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("expected a JSON list, a message, or {'messages': [...]}")
    rows = []
    for item in items:
        if isinstance(item, dict) and "url" in item:
            rows.append(item)
        else:
            row = row_from_sent(item)
            if row:
                rows.append(row)
    return rows


def expired(rows, today, days=RETENTION_DAYS):
    """URLs of brief pages last updated more than `days` days before `today`.

    `rows` are dicts with title, url, favicon and updated (an ISO date or
    timestamp). A page exactly `days` old is kept. Each URL appears once, in
    the order first seen.

    >>> rows = [{"title": "Morning Brief", "url": "https://claude.ai/code/artifact/a",
    ...          "favicon": "\U0001F4EC", "updated": "2026-08-01T17:30:00Z"},
    ...         {"title": "Morning Brief", "url": "https://claude.ai/code/artifact/b",
    ...          "favicon": "\U0001F4EC", "updated": "2026-08-14"}]
    >>> expired(rows, "2026-09-13")
    ['https://claude.ai/code/artifact/a']
    """
    now = _day(today)
    if now is None:
        raise ValueError(f"today must be YYYY-MM-DD, got {today!r}")
    out = []
    for row in rows:
        when = _day(row.get("updated"))
        if (when is not None and is_brief_page(row) and (now - when).days > days
                and row["url"] not in out):
            out.append(row["url"])
    return out
