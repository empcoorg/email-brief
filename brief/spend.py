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
    """(year, {service: amount}) from a brief's text copy, or (None, {}).

    The last such line wins: a quoted older brief cannot displace this one's.

    >>> parse_line("AI spend YTD 2026: Acme AI $120.00; Northwind AI $18.50")
    ('2026', {'Acme AI': 120.0, 'Northwind AI': 18.5})
    >>> parse_line("no line here")
    (None, {})
    """
    last = None
    for m in _LINE.finditer(str(text or "")):
        last = m
    if last is None:
        return None, {}
    totals = {}
    for part in last.group("body").split(";"):
        part = part.strip()
        if not part or part == "nothing yet":
            continue
        entry = _ENTRY.match(part)
        if not entry:
            raise ValueError(f"cannot read {part!r} in the {LINE_PREFIX} line")
        totals[entry.group("service").strip()] = float(entry.group("amount").replace(",", ""))
    return last.group("year"), totals


def format_line(year, totals):
    """The machine-readable line the next run reads back.

    >>> format_line("2026", {"Northwind AI": 18.5, "Acme AI": 120.0})
    'AI spend YTD 2026: Acme AI $120.00; Northwind AI $18.50'
    """
    if not totals:
        return f"{LINE_PREFIX} {year}: nothing yet"
    body = "; ".join(f"{s} ${totals[s]:,.2f}" for s in sorted(totals))
    return f"{LINE_PREFIX} {year}: {body}"


def accumulate(previous_text, charges, today, basis=None, basis_year=None):
    """Totals for today's brief: carried forward, plus this run's charges.

    `charges` is [(service, amount_usd)] for billing that arrived in THIS
    window only - anything older is already inside the carried total, and
    adding it again would double-count. A basis applies only in its own year
    and only when nothing was carried forward.

    Returns (year, {service: total}, carried_from_year or None).
    """
    year = year_of(today)
    prev_year, carried = parse_line(previous_text)
    if prev_year != year:
        carried = {}                          # 1 January: the count starts again
    totals = dict(carried)
    if not carried and basis and (basis_year is None or str(basis_year) == year):
        for service, amount in basis.items():
            totals[service] = totals.get(service, 0.0) + float(amount)
    for service, amount in charges or []:
        service = str(service).strip()
        if not service:
            raise ValueError("a charge needs a service name")
        totals[service] = round(totals.get(service, 0.0) + float(amount), 2)
    return year, totals, (prev_year if prev_year == year else None)


def rows(totals):
    """Payload rows, largest first: (service, total, share of the year's spend).

    >>> rows({"Acme AI": 120.0, "Northwind AI": 40.0})
    [['Acme AI', 120.0, '75% of AI spend this year'], ['Northwind AI', 40.0, '25% of AI spend this year']]
    """
    grand = sum(totals.values())
    out = []
    for service, total in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])):
        share = f"{round(100 * total / grand)}% of AI spend this year" if grand else "no charges yet"
        out.append([service, round(float(total), 2), share])
    return out
