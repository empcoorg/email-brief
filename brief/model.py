"""The payload contract between the Routine and the renderer.

The Routine gathers the facts and writes ONE JSON file. This module is the
contract for that file: it says which keys must be present, what shape each
one has, and it fails loudly with a precise message when something is missing
or malformed. A brief that renders the wrong shape silently is worse than one
that refuses to render, because nobody checks a brief that looks plausible.

Stdlib only — no jsonschema, no dependencies to install in a Routine run.
"""
import json

# key -> (kind, per-row arity or None, human description)
#   "rows"   list of tuples/lists, each of the given length
#   "dicts"  list of dicts, each carrying the given required keys
#   "map"    dict of str -> str
#   "mapl"   dict of str -> list of str
#   "obj"    dict carrying the given required keys
#   "str"    plain string
SPEC = {
    "MAST":       ("obj", ("title", "dateline", "tz", "window", "slot", "run", "note"), "masthead stamps"),
    "ACTIONS":    ("rows", 3, "action-bar rows: (severity, title, detail)"),
    "HIPRI":      ("rows", 3, "high-priority blocks: (severity, title, [items])"),
    "JOBS_TOP":   ("rows", 7, "ranked job leads: (role, company, comp, location, source, fit, link)"),
    "JOBS_STATUS": ("rows", 3, "application status: (title, meta, detail)"),
    "JOBS_OTHER": ("rows", 4, "lower-fit leads: (role, company, location, link)"),
    "JOBS_RANKED_NOTE": ("str", None, "what the ranking was based on"),
    "JOBS_TEAL_LABEL": ("str", None, "legend text for the teal colour"),
    "JOBS_LEGEND_FIT": ("str", None, "legend text for the fit badges"),
    "ALIGNERR":   ("str", None, "gig-platform digest summary"),
    "JOBS_SKIPPED": ("str", None, "what was skipped as off-target"),
    "FIN_SUMMARY": ("rows", 3, "summary tiles: (label, value, detail)"),
    "FIN_MOVES":  ("rows", 8, "money movements: (when, payee, detail, amount, currency, usd, direction, sign)"),
    "FIN_NOTES":  ("list", None, "bills/statements bullets"),
    "FIN_INTERNAL": ("str", None, "internal-transfer summary line"),
    "FLIGHTS":    ("obj", ("airline", "conf", "pax", "booked", "legs", "note"), "upcoming flights"),
    "VOIP":       ("obj", ("headline", "messages", "notes"), "VoIP: headline, message rows, notes"),
    "USPS":       ("obj", ("headline", "pieces", "counts", "note"), "postal digest"),
    "USPS_SCANS": ("rows", 2, "mailpiece scans: (data-uri, caption)"),
    "PKG":        ("rows", 6, "shipments: (carrier, tracking, item, recipient, status, eta)"),
    "PKG_NOTE":   ("str", None, "package section note"),
    "RETAIL":     ("obj", ("sub", "rewards", "items"), "retail: subtitle, rewards line, offer rows"),
    "MKT_ROWS":   ("rows", 6, "indexes: (name, close, pts1d, pct1d, pts1w, pct1w)"),
    "FUNDS":      ("rows", 8, "funds: (ticker, name, nav, chg_amount, chg_pct, asof, ytd, note)"),
    "MKT_BULLETS": ("list", None, "market bullets"),
    "CRYPTO_ROWS": ("rows", 6, "coins: (name, price, pct1d, amt1d, pct1w, amt1w)"),
    "CRYPTO_NOTE": ("str", None, "crypto sourcing note"),
    "CRYPTO_BULLETS": ("list", None, "crypto bullets"),
    "AI_ITEMS":   ("rows", 3, "AI items: (title, detail, link)"),
    "JOURNALS":   ("str", None, "journals scanned"),
    "JOURNAL_ITEMS": ("rows", 6, "papers: (journal, title, authors, date, takeaway, link)"),
    "ALLOWLIST":  ("map", None, "domain allowlist block"),
    "SOURCES":    ("mapl", None, "sources, grouped"),
}

FIT_TIERS = ("strong", "related", "")

# As many relevant leads as the window produced, but a brief nobody scrolls to
# the end of is not a brief. 25 is the ceiling; there is no floor.
MAX_RANKED_LEADS = 25

# A movement's detail may be tiered across up to three lines: what it was, the
# account and restrictions, then the breakdown and FX. Critical detail should be
# formatted rather than dropped — but a fourth line is a paragraph, not a cell.
MAX_DETAIL_LINES = 3

FLIGHT_LEG_KEYS = ("date", "flight", "ident", "frm", "dep", "to", "arr", "fa")
# "stats" (the flight's recent on-time record) is OPTIONAL: when the source is
# unreachable the run omits the field, and the renderer drops the whole column
# rather than printing an apology in every row.


class PayloadError(ValueError):
    """Raised with a precise, actionable message — never a bare KeyError."""


def _fail(key, why):
    raise PayloadError(f"payload key {key!r}: {why}")


def validate(payload):
    """Check the payload against SPEC. Returns it unchanged, or raises."""
    if not isinstance(payload, dict):
        raise PayloadError("payload must be a JSON object at the top level")
    missing = [k for k in SPEC if k not in payload]
    if missing:
        raise PayloadError("missing required key(s): " + ", ".join(sorted(missing)))

    for key, (kind, arity, desc) in SPEC.items():
        v = payload[key]
        if kind == "str":
            if not isinstance(v, str):
                _fail(key, f"expected a string ({desc}), got {type(v).__name__}")
        elif kind == "list":
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                _fail(key, f"expected a list of strings ({desc})")
        elif kind == "rows":
            if not isinstance(v, list):
                _fail(key, f"expected a list of rows ({desc})")
            for n, row in enumerate(v):
                if not isinstance(row, (list, tuple)):
                    _fail(key, f"row {n} is {type(row).__name__}, expected a list ({desc})")
                if len(row) != arity:
                    _fail(key, f"row {n} has {len(row)} field(s), expected {arity} — {desc}")
        elif kind in ("map", "mapl"):
            if not isinstance(v, dict):
                _fail(key, f"expected an object ({desc})")
            for k2, v2 in v.items():
                if kind == "map" and not isinstance(v2, str):
                    _fail(key, f"value for {k2!r} must be a string ({desc})")
                if kind == "mapl" and not (isinstance(v2, list) and all(isinstance(u, str) for u in v2)):
                    _fail(key, f"value for {k2!r} must be a list of strings ({desc})")
        elif kind == "obj":
            if not isinstance(v, dict):
                _fail(key, f"expected an object ({desc})")
            absent = [k2 for k2 in arity if k2 not in v]
            if absent:
                _fail(key, f"missing field(s) {', '.join(absent)} ({desc})")

    for n, row in enumerate(payload["VOIP"]["messages"]):
        if not isinstance(row, (list, tuple)) or len(row) != 5:
            _fail("VOIP", f"message {n} must have 5 fields "
                          "(when, from, to, kind, text)")
    for n, row in enumerate(payload["RETAIL"]["items"]):
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            _fail("RETAIL", f"offer {n} must have 3 fields (store, offer, detail)")

    for n, leg in enumerate(payload["FLIGHTS"]["legs"]):
        absent = [k for k in FLIGHT_LEG_KEYS if k not in leg]
        if absent:
            _fail("FLIGHTS", f"leg {n} missing field(s): {', '.join(absent)}")

    for n, row in enumerate(payload["FIN_MOVES"]):
        if not isinstance(row[2], (str, list)):
            _fail("FIN_MOVES", f"row {n}: detail must be a string, or a list of up to "
                               f"{MAX_DETAIL_LINES} lines (what it was / account and "
                               "restrictions / breakdown and FX), got "
                               f"{type(row[2]).__name__}")
        if isinstance(row[2], list):
            if len(row[2]) > MAX_DETAIL_LINES:
                _fail("FIN_MOVES", f"row {n}: {len(row[2])} detail lines, maximum is "
                                   f"{MAX_DETAIL_LINES} — a fourth line is a paragraph, "
                                   "not a table cell")
            if not all(isinstance(x, str) for x in row[2]):
                _fail("FIN_MOVES", f"row {n}: every detail line must be a string")
        if not isinstance(row[3], (int, float)):
            _fail("FIN_MOVES", f"row {n}: amount must be a number, got {row[3]!r} — "
                               "bars cannot be drawn from a formatted string")
        if not isinstance(row[5], (int, float)):
            _fail("FIN_MOVES", f"row {n}: usd must be a number, got {row[5]!r} — every "
                               "movement needs its USD equivalent, because all money bars "
                               "share one USD axis")
        if row[4] == "USD" and abs(row[3] - row[5]) > 0.01:
            _fail("FIN_MOVES", f"row {n}: currency is USD but amount {row[3]} and usd "
                               f"{row[5]} disagree")
        if row[4] != "USD" and row[3] == row[5] and row[3] != 0:
            _fail("FIN_MOVES", f"row {n}: currency is {row[4]} but usd equals the raw "
                               f"amount ({row[3]}) — an unconverted figure would plot a "
                               "foreign charge at its face value on the USD axis")
    if len(payload["JOBS_TOP"]) > MAX_RANKED_LEADS:
        _fail("JOBS_TOP", f"{len(payload['JOBS_TOP'])} ranked leads, maximum is "
                          f"{MAX_RANKED_LEADS} — keep the best {MAX_RANKED_LEADS} by fit "
                          "and move the rest to JOBS_OTHER")
    for n, row in enumerate(payload["JOBS_TOP"]):
        if row[5] not in FIT_TIERS:
            _fail("JOBS_TOP", f"row {n}: fit must be one of {sorted(FIT_TIERS)}, got "
                              f"{row[5]!r} — the fit tier depends on the owner's "
                              "interests, so the run must decide it; the renderer cannot")

    for key, idx in (("MKT_ROWS", (3, 5)), ("CRYPTO_ROWS", (2, 4)), ("FUNDS", (4,))):
        for n, row in enumerate(payload[key]):
            for i in idx:
                if not isinstance(row[i], (int, float)):
                    _fail(key, f"row {n} field {i}: percentage must be a number, got {row[i]!r}")
    return payload


def load(path):
    """Read and validate a payload file."""
    with open(path, encoding="utf-8") as fh:
        try:
            payload = json.load(fh)
        except json.JSONDecodeError as ex:
            raise PayloadError(f"{path} is not valid JSON: {ex}") from None
    return validate(payload)
