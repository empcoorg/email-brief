"""The evening update: what the morning's reader could not see, plus what is new.

A scheduled evening run is a fresh session. It cannot see the morning run's
files, so it learns two things from what the morning left behind:

  * WHAT was left out, from the "Brief record:" line at the end of the morning
    email's text copy - sections shed from the email and sections that fell
    past Gmail's clip point.
  * The CONTENT of those sections, from the morning payload embedded in the
    privately published full page (embed_payload / extract_payload).

merge() then builds one payload: the evening's own findings, with each carried
section filled from the morning. A carried section is labelled as such by the
renderer, so nothing from 10 AM passes itself off as fresh at 6 PM.

Stdlib only.
"""
import copy
import html
import json
import re

from .model import PayloadError, validate
from .render import SECTION_KEYS
from .significance import reasons

_BLOCK = re.compile(r'<script type="application/json" id="brief-payload">(.*?)</script>', re.S)


def embed_payload(page_html, payload):
    """Append the payload to the page as an inert JSON data block.

    Escapes "</" so a value containing "</script>" cannot close the block
    early. A JSON block is never executed, so it needs no script permission.

    >>> p = embed_payload("<p>x</p>", {"A": "</script><b>"})
    >>> extract_payload(p) == {"A": "</script><b>"}
    True
    """
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return page_html + f'\n<script type="application/json" id="brief-payload">{data}</script>\n'


def extract_payload(text):
    """Recover the payload from a page, or from an Artifact read-back of one.

    A read-back arrives wrapped in the host's skeleton and sometimes a header
    line, so this looks for the block rather than parsing the whole document.
    Returns None when there is no block, rather than guessing.
    """
    m = _BLOCK.search(text)
    if not m:
        return None
    raw = m.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # A viewer that HTML-escaped the page on the way back.
        return json.loads(html.unescape(raw))


_RECORD = re.compile(r"Brief record:\s*(brief-[0-9a-f]{12})\s*\|\s*shed:\s*(.*?)\s*\|"
                     r"\s*beyond Gmail's clip:\s*(.*?)\s*$", re.M)


def parse_record(text):
    """Read the morning email's "Brief record:" line.

    >>> parse_record("Brief record: brief-0123456789ab | shed: US market; Large caps"
    ...              " | beyond Gmail's clip: Retail sales")
    {'build': 'brief-0123456789ab', 'shed': ['US market', 'Large caps'], 'clipped': ['Retail sales']}
    """
    m = _RECORD.search(text or "")
    if not m:
        return None

    def names(s):
        return [] if s.strip().lower() == "none" else [n.strip() for n in s.split(";") if n.strip()]
    return {"build": m.group(1), "shed": names(m.group(2)), "clipped": names(m.group(3))}


def _empty(v):
    """True when a payload value carries nothing a reader would see."""
    if isinstance(v, list):
        return len(v) == 0
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, dict):
        lists = [x for x in v.values() if isinstance(x, list)]
        return bool(lists) and all(len(x) == 0 for x in lists)
    return v is None


def _has_rows(v):
    """True when a value holds rows a reader would see, not just prose around them.

    A sourcing note or the list of journals scanned says nothing about whether
    anything ARRIVED, so strings never count; neither do "notes" lists.

    >>> _has_rows("sources: two sites"), _has_rows([]), _has_rows([["a", "b"]])
    (False, False, True)
    >>> _has_rows({"note": "x", "notes": ["y"], "legs": []})
    False
    """
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, dict):
        return any(isinstance(x, list) and x for k, x in v.items() if k != "notes")
    return False


def _combine(morning, evening):
    """Morning first, then the evening's additions; evening wins for scalars."""
    if _empty(evening):
        return copy.deepcopy(morning)
    if _empty(morning):
        return evening
    if isinstance(morning, list) and isinstance(evening, list):
        return copy.deepcopy(morning) + evening
    if isinstance(morning, dict) and isinstance(evening, dict):
        out = dict(evening)
        for k, mv in morning.items():
            ev = evening.get(k)
            if isinstance(mv, list) and isinstance(ev, list):
                out[k] = copy.deepcopy(mv) + ev
            elif k not in evening or _empty(ev):
                out[k] = copy.deepcopy(mv)
        return out
    return evening


def merge(morning, evening, carry, carried_from):
    """The evening payload, with each carried section filled from the morning.

    Returns (payload, carried_names). Unknown section names raise, because a
    silently ignored name is a section the reader was promised and never got.
    """
    unknown = [n for n in carry if n not in SECTION_KEYS]
    if unknown:
        raise PayloadError("cannot carry unknown section(s): " + ", ".join(unknown)
                           + " — known: " + ", ".join(SECTION_KEYS))
    out = copy.deepcopy(evening)
    merged = []
    for name in carry:
        keys = SECTION_KEYS[name]
        if not any(_has_rows(evening.get(k)) for k in keys):
            # Nothing new arrived for this section: the morning's version is
            # the section, notes and all, so it reads the way it was written.
            for k in keys:
                out[k] = copy.deepcopy(morning.get(k))
            continue
        for k in keys:
            out[k] = _combine(morning.get(k), evening.get(k))
        merged.append(name)
    out["CARRIED"] = {"from": carried_from, "sections": list(carry), "merged": merged}
    validate(out)
    return out, list(carry)


def decide(evening, carried):
    """Send the evening update, or skip it. Returns (send, why)."""
    why = reasons(evening)
    if carried:
        why = why + [f"carries {len(carried)} section(s) the morning email could not show: "
                     + ", ".join(carried)]
    return bool(why), why
