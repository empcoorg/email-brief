"""Phone numbers, written so they can be dialled from where they are read.

A brief is read on a phone. "1 (555) 010-6200" has to be retyped before it can
be dialled; "+1-555-010-6200" can be tapped, or pasted into a dialler, and
works from any country. So every phone number the brief prints carries its
country code.

The rewrite is deliberately narrow, because a brief is full of digits that are
NOT phone numbers - tracking numbers, ZIP+4, masked account digits, amounts,
seat and flight numbers, and the base64 of a mailpiece scan. Only two shapes
are touched:

* a North American number with separators or parentheses (10 digits as 3-3-4,
  with an optional leading 1), which gains +1 when it has no country code;
* a number already written with a leading +, whose spacing is regularised.

A bare run of ten digits is left alone on purpose: an order number looks
exactly like one, and mangling an order number is worse than leaving a phone
number unlinked.
"""
import re as _re

DEFAULT_CC = "+1"          # the numbering plan the 3-3-4 shape belongs to
_SEP = r"[ .·‑–-]"

# One pass, international FIRST, so a number that already carries its country
# code is consumed here and cannot then be matched again as a bare 3-3-4 and
# given a second +1.
#   +44 20 7946 0958 / +52-55-1234-5678 — a country code, then 6-14 more digits
#   1 (555) 010-6200 / 555.010.6200 / (555) 010-7788 — never a bare 5550106200
_NUMBER = _re.compile(
    rf"(?P<intl>(?<![\w+])\+(?P<cc>\d{{1,3}}){_SEP}?(?P<rest>\d(?:{_SEP}?\d){{5,13}})(?![\w]))"
    rf"|(?P<nanp>(?<![\d+])(?:1{_SEP})?\(?(?P<a>\d{{3}})\)?{_SEP}(?P<b>\d{{3}}){_SEP}(?P<c>\d{{4}})(?![\d]))")


def dialable(text):
    """Rewrite the phone numbers in `text` so each carries its country code.

    >>> dialable("property phone 1 (555) 010-6200")
    'property phone +1-555-010-6200'
    >>> dialable("from 555-010-7788 to (555) 010-0001")
    'from +1-555-010-7788 to +1-555-010-0001'
    >>> dialable("+44 20 7946 0958")
    '+44-20-7946-0958'
    >>> dialable("call +1-555-010-6200 now")       # already dialable, left alone
    'call +1-555-010-6200 now'
    >>> dialable("tracking 9400 1000 0000 0000 0000 00, ZIP 00000-0000, order 5550106200")
    'tracking 9400 1000 0000 0000 0000 00, ZIP 00000-0000, order 5550106200'
    """
    if not isinstance(text, str) or ("+" not in text and not _re.search(r"\d{3}", text)):
        return text

    def one(m):
        if m.group("intl"):
            return "+" + m.group("cc") + "-" + _group_intl(m.group("rest"))
        return f'{DEFAULT_CC}-{m.group("a")}-{m.group("b")}-{m.group("c")}'

    return _NUMBER.sub(one, text)


def _group_intl(rest):
    """Keep an international number's own grouping, with one separator style."""
    return "-".join(part for part in _re.split(_SEP, rest) if part)


# Values that only look like text: a link, or the base64 of a scan, where a run
# of digits is never a number anyone dials. VOIP is skipped by the owner's
# explicit choice: that section prints the numbers exactly as the provider wrote
# them, and its "to number" column reads as a set of the owner's own lines
# rather than as something to dial.
_SKIP_KEYS = frozenset({"USPS_SCANS", "SOURCES", "ALLOWLIST", "PKG", "VOIP"})


def normalize(payload):
    """A copy of the payload with every phone number made dialable.

    Skips the keys whose values are addresses rather than prose, and any string
    that is itself a URL or a data: URI.
    """
    def walk(value):
        if isinstance(value, str):
            return value if value[:5].lower() in ("http:", "https", "data:") else dialable(value)
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, tuple):
            return tuple(walk(v) for v in value)
        if isinstance(value, dict):
            return {k: (v if k in _SKIP_KEYS else walk(v)) for k, v in value.items()}
        return value

    return {k: (v if k in _SKIP_KEYS else walk(v)) for k, v in payload.items()}
