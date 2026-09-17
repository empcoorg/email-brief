"""Whether a number is good news, bad news, or neither.

A brief is scanned, not read, so a figure that moved should say which way it
went without being parsed word by word. Direction alone is not enough: an
unemployment rate rising and payrolls rising are both "up", and they mean
opposite things. So a tone has two parts - which way the number moved, and
whether up is good for that particular indicator - and anything this module
cannot place with confidence stays NEUTRAL. A wrongly coloured figure says the
opposite of the truth, which is worse than an uncoloured one.
"""
import re as _re

POS, NEG, NEU = "pos", "neg", "neu"

# Up is BAD: what these measure is a cost, a loss, or a burden on the reader.
_UP_IS_BAD = (
    "unemployment", "jobless", "layoff", "claims", "inflation", "cpi", "pce",
    "price index", "rate target", "fed funds", "funds rate", "interest rate",
    "yield", "treasury", "mortgage", "deficit", "debt", "delinquen",
    "foreclosure", "bankrupt", "vacancy", "default",
)
# Up is GOOD: more of it is more activity, income or output.
_UP_IS_GOOD = (
    "payroll", "jobs added", "hiring", "employment level", "participation",
    "gdp", "output", "productivity", "wage", "earnings", "income", "retail sales",
    "spending", "confidence", "sentiment", "starts", "permits", "orders",
)

# A sign counts only when ATTACHED to a digit: "Mar 17 - 18" is a date range,
# and reading its dash as a fall painted an FOMC row red.
_UP = _re.compile(r"(?:^|\s)(?:\+\d|up\b|rose\b|higher\b|gain|increase|climb|jump|surge|"
                  r"raise|raised|hike|hiked|tighten)", _re.I)
_DOWN = _re.compile(r"(?:^|\s)(?:[-−]\d|down\b|fell\b|lower\b|drop|decline|decrease|"
                    r"slip|fall|cut\b|cuts\b|eased?\b|reduce)", _re.I)
_FLAT = _re.compile(r"\b(unchanged|flat|steady|held|no change)\b", _re.I)
# Against an expectation the comparison IS the direction: a payroll print that
# added jobs but missed the forecast is not plainly good news, and the words
# "below the +170,000 consensus" carry a plus sign that belongs to the forecast.
_VS_FORECAST = _re.compile(r"\b(consensus|estimate|forecast|expected|expectations)\b", _re.I)
_BELOW = _re.compile(r"\b(below|under|short of|missed|miss)\b", _re.I)
_ABOVE = _re.compile(r"\b(above|over|beat|topped|exceeded)\b", _re.I)


def polarity(indicator):
    """+1 when a rise is good news for the reader, -1 when it is bad, 0 when unclear.

    >>> polarity("Unemployment rate"), polarity("Nonfarm payrolls"), polarity("Next FOMC")
    (-1, 1, 0)
    """
    text = str(indicator or "").lower()
    if any(w in text for w in _UP_IS_BAD):
        return -1
    if any(w in text for w in _UP_IS_GOOD):
        return 1
    return 0


def direction(change):
    """+1, -1 or 0 from the change text the payload states.

    >>> direction("+6 bp on the day"), direction("down from 2.9% in January")
    (1, -1)
    >>> direction("unchanged at the January meeting"), direction("Mar 17 - 18")
    (0, 0)
    >>> direction("raised 25 bp"), direction("below the +170,000 consensus")
    (1, -1)
    """
    text = str(change or "")
    if _FLAT.search(text):
        return 0
    if _VS_FORECAST.search(text):
        if _BELOW.search(text):
            return -1
        if _ABOVE.search(text):
            return 1
        return 0
    up, down = _UP.search(text), _DOWN.search(text)
    if up and not down:
        return 1
    if down and not up:
        return -1
    if up and down:                      # whichever the sentence leads with
        return 1 if up.start() < down.start() else -1
    return 0


def macro_tone(indicator, change):
    """Good news, bad news or neither, for one macro row.

    >>> macro_tone("Unemployment rate", "up from 4.1%"), macro_tone("Nonfarm payrolls", "+151,000")
    ('neg', 'pos')
    >>> macro_tone("Fed funds target", "raised 25 bp"), macro_tone("Next FOMC", "Mar 17 - 18")
    ('neg', 'neu')
    >>> macro_tone("Nonfarm payrolls", "below the +170,000 consensus")
    'neg'
    >>> macro_tone("10-yr Treasury", "+6 bp on the day")
    'neg'
    """
    d, p = direction(change), polarity(indicator)
    if not d or not p:
        return NEU
    return POS if d * p > 0 else NEG


def move_tone(pct):
    """A quote's tone from its own 1D change: up green, down red, flat neutral.

    >>> move_tone(0.6), move_tone(-0.26), move_tone(0)
    ('pos', 'neg', 'neu')
    """
    if not isinstance(pct, (int, float)) or pct == 0:
        return NEU
    return POS if pct > 0 else NEG
