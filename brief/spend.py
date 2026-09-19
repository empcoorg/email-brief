"""Running totals for what the AI services bill, year to date.

The brief has no memory: every run is a fresh session. So the total cannot be
recomputed from the mailbox each morning - that would mean re-reading a year of
billing email - and it cannot be held in the repo either, because the repo is
public. It is carried in the BRIEF ITSELF: every brief's text copy ends with a
machine-readable line,

    AI spend YTD 2026: Acme AI $120.00; Northwind AI $18.50

and the next run reads that line out of the previous sent brief, adds the
charges that arrived since, and prints the new line. Nothing is back-dated: the
count starts at zero the first time a service is seen, which is why the totals
say "counted from <date>".

The year resets on 1 January by construction: a line stamped with a different
year than today's is not carried forward. A BASIS (a starting amount for one
service in one year, established outside the mailbox) is added only when there
is nothing to carry - once it is folded into a total, carrying that total
forward is what keeps it.
"""
import datetime as _dt
import re as _re

LINE_PREFIX = "AI spend YTD"
# " | opening $250.00" - spend already made this year that no row itemises,
# carried on the same line so the next run keeps it without being told again.
OPENING = " | opening $"
# The line is indented inside the brief's finances section, and a mail client
# may have quoted it - so it is matched anywhere on its line, not at the margin.
_LINE = _re.compile(rf"^[>\s]*{LINE_PREFIX} (?P<year>\d{{4}}): (?P<body>.*?)\s*$", _re.M)
# "Acme AI $120.00" - a service name may contain spaces, the amount never does
_ENTRY = _re.compile(r"^(?P<service>.+?) \$(?P<amount>-?[\d,]+\.?\d*)$")


def year_of(today):
    """The calendar year of an ISO date, as a string."""
    m = _re.match(r"(\d{4})-(\d{2})-(\d{2})", str(today or "").strip())
    if not m:
        raise ValueError(f"today must be YYYY-MM-DD, got {today!r}")
    _dt.date(*map(int, m.groups()))          # refuses 2026-13-40
    return m.group(1)


def parse_line(text):
    """(year, {service: amount}, opening) from a brief's text copy.

    The last such line wins: a quoted older brief cannot displace this one's.
    `opening` is the un-itemised balance the owner gave when the count started
    mid-year; it is 0.0 when the line carries none.

    >>> parse_line("AI spend YTD 2026: Acme AI $120.00; Northwind AI $18.50")
    ('2026', {'Acme AI': 120.0, 'Northwind AI': 18.5}, 0.0)
    >>> parse_line("AI spend YTD 2026: Acme AI $120.00 | opening $250.00")
    ('2026', {'Acme AI': 120.0}, 250.0)
    >>> parse_line("no line here")
    (None, {}, 0.0)
    """
    last = None
    for m in _LINE.finditer(str(text or "")):
        last = m
    if last is None:
        return None, {}, 0.0
    body = last.group("body")
    opening = 0.0
    if OPENING.strip() in body or " | opening $" in body:
        body, _, tail = body.partition("| opening $")
        try:
            opening = float(tail.strip().replace(",", ""))
        except ValueError:
            raise ValueError(f"cannot read the opening balance in {last.group(0)!r}")
    totals = {}
    for part in body.split(";"):
        part = part.strip()
        if not part or part == "nothing yet":
            continue
        entry = _ENTRY.match(part)
        if not entry:
            raise ValueError(f"cannot read {part!r} in the {LINE_PREFIX} line")
        totals[entry.group("service").strip()] = float(entry.group("amount").replace(",", ""))
    return last.group("year"), totals, opening


def format_line(year, totals, opening=0.0):
    """The machine-readable line the next run reads back.

    >>> format_line("2026", {"Northwind AI": 18.5, "Acme AI": 120.0})
    'AI spend YTD 2026: Acme AI $120.00; Northwind AI $18.50'
    >>> format_line("2026", {"Acme AI": 120.0}, 250.0)
    'AI spend YTD 2026: Acme AI $120.00 | opening $250.00'
    """
    tail = f"{OPENING}{float(opening):,.2f}" if opening else ""
    if not totals:
        return f"{LINE_PREFIX} {year}: nothing yet{tail}"
    body = "; ".join(f"{s} ${totals[s]:,.2f}" for s in sorted(totals))
    return f"{LINE_PREFIX} {year}: {body}{tail}"


def accumulate(previous_text, charges, today, basis=None, basis_year=None,
               total_basis=None, total_basis_year=None):
    """Totals for today's brief: carried forward, plus this run's charges.

    `charges` is [(service, amount_usd)] for billing that arrived in THIS
    window only - anything older is already inside the carried total, and
    adding it again would double-count. A basis applies only in its own year
    and only when nothing was carried forward.

    Returns (year, {service: total}, carried_from_year or None, opening). Use
    `added(charges)` for what this window alone billed, which the brief plots.
    """
    year = year_of(today)
    prev_year, carried, opening = parse_line(previous_text)
    if prev_year != year:
        carried, opening = {}, 0.0            # 1 January: the count starts again
    if not opening and total_basis and (total_basis_year is None or str(total_basis_year) == year):
        # A brief that starts in June cannot itemise January to May, but the
        # owner may know the total. It is added once and then carried, exactly
        # like a per-service basis.
        opening = round(float(total_basis), 2)
    totals = dict(carried)
    if not carried and basis and (basis_year is None or str(basis_year) == year):
        for service, amount in basis.items():
            totals[service] = totals.get(service, 0.0) + float(amount)
    for service, amount in charges or []:
        service = str(service).strip()
        if not service:
            raise ValueError("a charge needs a service name")
        totals[service] = round(totals.get(service, 0.0) + float(amount), 2)
    return year, totals, (prev_year if prev_year == year else None), opening


def added(charges):
    """What this window billed, per service - the figure the brief plots.

    >>> added([("Acme AI", 12.0), ("Acme AI", 8.0), ("Northwind AI", 5.0)])
    {'Acme AI': 20.0, 'Northwind AI': 5.0}
    """
    out = {}
    for service, amount in charges or []:
        service = str(service).strip()
        out[service] = round(out.get(service, 0.0) + float(amount), 2)
    return out


def rows(totals, new=None):
    """Payload rows, largest first: (service, total, this window, share note).

    The third field is what arrived in THIS window, which is what the brief
    draws a bar from; the year-to-date total is a running figure and plotting
    it would say nothing about today.

    >>> rows({"Acme AI": 120.0, "Northwind AI": 40.0}, {"Acme AI": 20.0})
    [['Acme AI', 120.0, 20.0, '75% of AI spend YTD'], ['Northwind AI', 40.0, 0.0, '25% of AI spend YTD']]
    """
    grand = sum(totals.values())
    new = new or {}
    out = []
    for service, total in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
        share = f"{round(100 * total / grand)}% of AI spend YTD" if grand else "no charges yet"
        out.append([service, round(float(total), 2), round(float(new.get(service, 0.0)), 2), share])
    return out
