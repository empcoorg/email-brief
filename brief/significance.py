"""Does an evening update earn an interruption?

The brief goes out every morning unconditionally. A second send in the evening
is only worth someone's attention if something happened that they would want to
know before tomorrow — otherwise it trains them to ignore the sender.

"Something important" was going to be a sentence in the prompt. It is a rule,
so it is a function: the evening run builds a payload covering only the window
since the morning brief, and this decides whether that payload is worth sending.

The bar is deliberately explicit. Anything that could cost money, a deadline, or
access clears it; routine movement does not.
"""

# A single movement at or above this, in USD, is worth knowing about tonight.
MATERIAL_USD = 500.00

# Severities that mean "act", as opposed to "noted" or "all clear".
URGENT = {"neg", "warn"}

# Shipment states worth a second send.
SHIPMENT_EVENTS = ("deliver", "exception", "delay", "held", "refus", "return")

# Travel changes worth a second send.
TRAVEL_EVENTS = ("delay", "cancel", "changed", "rebook", "gate", "reschedul")


def _rows(payload, key):
    return payload.get(key) or []


def reasons(payload):
    """Every reason this payload justifies an evening send. Empty means skip."""
    out = []

    for sev, title, _ in _rows(payload, "ACTIONS"):
        if sev in URGENT:
            out.append(f"action bar [{sev}]: {title}")

    for sev, title, _ in _rows(payload, "HIPRI"):
        if sev in URGENT:
            out.append(f"high priority [{sev}]: {title}")

    for row in _rows(payload, "FIN_MOVES"):
        _when, payee, _detail, _amount, _cur, usd, direction, _sign = row
        if direction == "Past due":
            out.append(f"past due: {payee}")
        elif abs(usd) >= MATERIAL_USD:
            out.append(f"movement ${abs(usd):,.2f}: {payee}")

    for title, meta, _ in _rows(payload, "JOBS_STATUS"):
        out.append(f"application status: {title} — {meta}")

    for row in _rows(payload, "PKG"):
        status = str(row[4]).lower()
        if any(w in status for w in SHIPMENT_EVENTS):
            out.append(f"shipment: {row[0]} {row[4]}")

    flights = payload.get("FLIGHTS") or {}
    for leg in flights.get("legs", []):
        note = f"{leg.get('stats', '')} {flights.get('note', '')}".lower()
        if any(w in note for w in TRAVEL_EVENTS):
            out.append(f"travel change: {leg.get('flight', '?')}")

    usps = payload.get("USPS") or {}
    if usps.get("pieces"):
        out.append(f"{len(usps['pieces'])} mailpiece(s) for the intended recipient")

    voip = payload.get("VOIP") or {}
    if voip.get("messages"):
        out.append(f"{len(voip['messages'])} voicemail/text")

    return out


def is_significant(payload):
    """True when the evening payload is worth a second send."""
    return bool(reasons(payload))
