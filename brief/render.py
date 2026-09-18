"""Rendering — the three outputs, built from a validated payload.

This module holds every layout decision the brief makes: the themed standalone
HTML file, the sanitizer-safe email, and the plain-text fallback. It used to be
prose in the Routine prompt, re-interpreted from scratch every morning; it is
now code with tests, so the brief looks the same on every run by construction.

The payload's keys are bound as module globals by render_all() before the
renderers run, so each renderer reads them directly. That keeps the functions
short, and the CLI renders once per process, so the shared binding is not a
concurrency concern.
"""
import base64, hashlib, html as H, json, math, os

from .axes import (fraction, money_axis as _money_axis_calc, money_labels, money_tick,
                   nice_step_top, pct_axis, pct_labels, pct_tick, steps_per_side,
                   tick_positions)
from .links import AIRLINE_NAMES
from .theme import (BODY_FS, D, F_B, F_H, F_M, GOOGLE_FONTS, L, attr, e,
                    space_ranges, url)

__all__ = ["render_all", "file_html", "email_html", "plain_text"]


SEV_WORD = {"warn": "CHECK", "neg": "URGENT", "info": "NOTE", "ok": "CLEAR"}


def sev_chip(sev):
    """Severity as a bordered chip in its own color."""
    return (f'<span class="badge c-{sev}" style="margin-left:0;white-space:nowrap">'
            f'{SEV_WORD.get(sev, sev.upper())}</span>')


class SectionNumber:
    """Consecutive numbering. Omitting a section used to leave a hole, because
    the numbers were written into each heading by hand while the prompt carried
    the renumbering rule as prose. Counting is arithmetic."""

    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return self.n


def build_marker(payload):
    """Fingerprint embedded in all three outputs.

    A run that hand-writes HTML imitating this design gets the styling roughly
    right and the structure wrong, in ways no test here can catch: the tests
    exercise the renderer, and a hand-written document never reaches it. Every
    output carries this marker and the run quotes it back. No marker, no render.
    """
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return "brief-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def _derive():
    """Axes that depend on the payload's own numbers, recomputed per render."""
    g = globals()
    g["FIN_AXIS"] = _money_axis_calc([m[5] for m in FIN_MOVES])
    # What each AI service billed in THIS window, on its own diverging axis: a
    # charge is money out, so it draws left of zero exactly as a payment does.
    g["AI_AXIS"] = _money_axis_calc([abs(r[2]) for r in ai_spend_rows() if len(r) > 3] or [0])
    g["FIN_BAR_SCALE"] = FIN_AXIS[2]
    g["MKT_24"] = pct_axis([r[3] for r in MKT_ROWS])
    g["MKT_7D"] = pct_axis([r[5] for r in MKT_ROWS])
    g["CRY_24"] = pct_axis([r[2] for r in CRYPTO_ROWS])
    g["CRY_7D"] = pct_axis([r[4] for r in CRYPTO_ROWS])
    g["MKT_YTD"] = pct_axis([r[7] for r in MKT_ROWS])
    g["CRY_YTD"] = pct_axis([r[6] for r in CRYPTO_ROWS])
    g["FUND_1D"] = pct_axis([r[4] for r in FUNDS])
    g["FUND_1W"] = pct_axis([r[6] for r in FUNDS])
    g["FUND_YTD"] = pct_axis([r[8] for r in FUNDS])
    g["STK_1D"] = pct_axis([r[3] for r in STOCKS])
    g["STK_1W"] = pct_axis([r[5] for r in STOCKS])
    g["STK_YTD"] = pct_axis([r[7] for r in STOCKS])


def render_all(payload, email_budget=None, text_budget=None, full_url=None,
               attached_scans=None, stamp=None):
    """Bind a validated payload and render all three outputs.

    `email_budget` overrides EMAIL_BUDGET_BYTES for the email only. The send is
    ONE tool call carrying the HTML, the text and every attachment inline, so
    scans eat into the room the body has; `brief render --scans` computes what
    is left and passes it here rather than letting the send fail at 6am.

    `full_url` is the address of the complete page, published privately by the
    run. When given, it sits in the email's masthead, each mailpiece scan links
    to its figure on it, and it is the last line of the text copy. The page
    itself never needs it.

    `stamp` is the date the standalone file is written under; the email names
    that file, so the name has to be the real one.

    `attached_scans` is how many scan JPGs ride along in the send, when known.
    The email never claims a scan is attached unless it is: a run allowed to
    drop scans to fit the send call must not leave the brief saying otherwise.

    Returns (file_html, email_html, plain_text).
    """
    # Optional keys must be reset, not merely updated: render_all binds the
    # payload into module globals, so an evening payload's CARRIED would
    # otherwise leak into the next render in the same process.
    # Phone numbers are made dialable before anything is bound, so the page,
    # the email and the text copy all print the same form. VoIP is left exactly
    # as the provider wrote it - see brief/phones.py.
    from .phones import normalize as _dialable_numbers
    payload = _dialable_numbers(payload)
    globals()["CARRIED"] = payload.get("CARRIED") or {}
    # Optional keys are bound explicitly, so a payload written against an older
    # prompt renders with the section simply absent.
    globals()["AI_SPEND"] = payload.get("AI_SPEND") or {}
    globals()["TRAVEL"] = payload.get("TRAVEL") or []
    if full_url and url(full_url) == "#":
        # A refused link would still print its text, so refuse the address
        # outright and let the run see why, instead of shipping a dead link.
        raise ValueError(f"--full-url must be an http(s) address, got {full_url!r}")
    globals()["FULL_URL"] = full_url or ""
    globals()["ATTACHED_SCANS"] = attached_scans
    globals()["FILE_STAMP"] = stamp or payload["MAST"].get("file_date") or "brief"
    globals().update(payload)
    globals()["BUILD"] = build_marker(payload)
    _derive()
    fh = _caption_carried_file(file_html())
    return fh, email_html(email_budget), plain_text(text_budget)


SCAN_CSS = ".scanfig{margin:14px 0 4px}.scanfig img{max-width:min(720px,100%);border:1px solid var(--line);border-radius:6px;display:block}.scanfig figcaption{font-size:12.5px;color:var(--ink-3);margin-top:6px}"
def cur_sym(cur): return {"USD": "$", "MXN": "MX$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(cur, cur + " ")
import re as _re

from .retention import RETENTION_DAYS
from .tone import macro_tone, move_tone


def short_url(u):
    v = _re.sub(r"^https?://(www\.)?", "", u)
    return v[:72] + ("…" if len(v) > 72 else "")
def lead_split(text):
    """Split a bullet into (lead-in, rest) at the first ': ' or ' — ' within the first ~60 chars."""
    m = _re.match(r'^(.{2,60}?)(: | — )(.*)$', text, _re.S)
    if m: return m.group(1), m.group(2), m.group(3)
    return None, "", text

FIT_LABEL = {"strong": ("STRONG FIT", "pos"), "related": ("RELATED", "accent")}


def job_fit(tier):
    """Badge text and color class for a payload fit tier.

    The renderer does NOT decide fit. Which roles are a strong fit depends on
    the owner's configured interests, which only the run knows; a keyword list
    living here would silently judge every owner by one persona's vocabulary.
    The payload carries the tier, this turns it into a badge.
    """
    return FIT_LABEL.get(tier or "", ("", ""))
def loc_tier(loc):
    l = loc.lower()
    if any(k in l for k in ("boston", "denver", "preferred")): return "accent", "Preferred area"
    if "remote" in l: return "accent", "Remote"
    return "", ""

# ------------------------------------------------------------------ RENDER: FILE (tokens)
# Direction glyphs. SHAPE carries the meaning, color only reinforces it — the
# brief never lets color be the sole channel, and an arrow is a non-color cue
# that costs a third of the width of the word it replaces.
ARROW_UP, ARROW_DOWN = "\u25b2", "\u25bc"


def arrow(v):
    """Up/down glyph for a signed change."""
    return ARROW_UP if v >= 0 else ARROW_DOWN


def pct_str(v):
    """A signed percentage using a real minus sign (U+2212), not a hyphen.

    The payload's own figures and the axis labels already use U+2212, so a
    hyphen here would put two different minus characters in one cell:
    "\u2212121.40 pts \u00b7 -0.26%".
    """
    return f"{v:+.2f}%".replace("-", "\u2212")


def pct_tick(v):
    """Even percentage axis label: −3% · 0 · +3%."""
    return "0" if v == 0 else f"{v:+g}".replace("-", "\u2212") + "%"
def _axis_marks(ax):
    step, top = ax
    return int(round(top / step))
def axis_div(ax, cls=""):
    """Fine-grain diverging ruler: a notch at every EVEN step, labels only at
    −top, 0, +top. Same contract as the money axis."""
    n = _axis_marks(ax)
    top = ax[1]
    t = [f'<i class="{"mj" if k in (-n, 0, n) else ""}" style="left:{50 + k * 50 / n:g}%"></i>'
         for k in range(-n, n + 1)]
    for v, p, c in ((-top, 0, "l"), (0, 50, ""), (top, 100, "r")):
        t.append(f'<span class="{c}" style="left:{p}%">{pct_tick(v)}</span>')
    return f'<div class="daxis{" " + cls if cls else ""}" aria-hidden="true">' + "".join(t) + "</div>"
def axis_foot(ax, label):
    return f'<div class="daxis-foot">{axis_div(ax)}<div class="meta">{e(label)}</div></div>'
def em_axis(ax):
    top = ax[1]
    return f"{pct_tick(-top)} \u00b7 0 \u00b7 {pct_tick(top)}"
def axis_note(ax, what):
    step, top = ax
    return f"{what}: diverging, 0 at center \u2192 {pct_tick(top)} each side; even {step:g}% steps"
def _money_fmt(v):
    return "$" + (f"{v:,.0f}" if v >= 10 else f"{v:,.2f}")
def money_tick(v):
    """Compact, even axis label: 0 \u00b7 $1k \u00b7 \u2212$3k. Never a raw data value."""
    a = abs(v)
    if a == 0:
        return "0"
    s = f"{a / 1000:g}k" if a >= 1000 else f"{a:g}"
    return ("\u2212$" if v < 0 else "$") + s
def _money_steps(axis=None):
    """Steps per side of the center line."""
    import math
    mode, a, b = axis or FIN_AXIS
    return int(round(b / a)) if mode == "linear" else int(round(math.log10(b / a)))
def _money_frac(amt, axis=None):
    import math
    mode, a, b = axis or FIN_AXIS
    if mode == "linear":
        return min(amt / b, 1.0)
    return max(0.0, min(1.0, (math.log10(max(amt, a)) - math.log10(a)) / (math.log10(b) - math.log10(a))))
def detail_lines(detail):
    """Normalise a movement's detail into tiered lines.

    A detail can be a plain string, or a list of up to three lines that the
    renderer weights differently:

        1. what it was            - body text
        2. account, restrictions  - muted
        3. breakdown, FX, source  - small and muted

    Critical detail should be FORMATTED, not deleted. A flight charge needs its
    confirmation code, its card, its restrictions and the rate its conversion
    used - but run together in one sentence they read as a wall and the row
    stops being scannable. Tiering them keeps every fact and restores the scan.
    """
    if isinstance(detail, (list, tuple)):
        return [str(x) for x in detail if str(x).strip()]
    return [str(detail)] if str(detail).strip() else []


def detail_html_file(detail):
    lines = detail_lines(detail)
    if not lines:
        return ""
    out = [e(lines[0])]
    if len(lines) > 1:
        out.append(f'<span class="meta">{e(lines[1])}</span>')
    for extra in lines[2:]:
        out.append(f'<span class="meta" style="font-size:12px">{e(extra)}</span>')
    return "<br>".join(out)


def detail_html_email(detail):
    lines = detail_lines(detail)
    if not lines:
        return ""
    out = [e(lines[0])]
    for extra in lines[1:]:
        out.append(small(e(extra)))
    return "<br>".join(out)


def horizon_cell_file(amount, pct, axis, unit="", reverse=False):
    """One horizon's figure centered over its bar, for the standalone file.

    `reverse` puts the percentage first, which reads better where the absolute
    move is a price delta rather than index points.
    """
    cls = "dir-pos" if pct >= 0 else "dir-neg"
    left = f"{pct_str(pct)} {arrow(pct)}" if reverse else f"{e(amount)}{' ' + unit if unit else ''}"
    right = f"{e(amount)}" if reverse else f"{pct_str(pct)} {arrow(pct)}"
    return (f'<span class="barfig"><span class="{cls} mono">{left} \u00b7 {right}</span></span>'
            + bar_div(pct, axis))


def money_amount(amt, cur, usd, sign):
    """Displayed amount: the charge in its own currency, plus the USD figure the
    bar is plotted from when they differ.

    A foreign charge shown only as "MX$10,200.00" next to a bar on a USD axis
    reads as $13,600 of movement. Stating the conversion is what makes the bar
    honest.
    """
    shown = ("" if sign == "\u00b1" else sign) + f"{cur_sym(cur)}{amt:,.2f}"
    if cur != "USD":
        shown += f" (\u2248 ${usd:,.2f} USD)"
    return shown


_MONTHS = {m: i for i, m in enumerate(
    ("jan feb mar apr may jun jul aug sep oct nov dec").split(), 1)}


def _when_key(when):
    """A sortable key from a movement's own "when" text, newest first.

    The payload writes it for a reader - "Tue Mar 3, 7:41 AM EST" - so this
    reads what it can (month, day, 24h time) and leaves the rest alone: a row
    it cannot parse keeps its position among its neighbours rather than being
    thrown to one end.
    """
    t = str(when or "").lower()
    m = _re.search(r"\b([a-z]{3})[a-z]*\.?\s+(\d{1,2})\b", t)
    if not m or m.group(1) not in _MONTHS:
        return None
    month, day = _MONTHS[m.group(1)], int(m.group(2))
    clock = _re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?", t)
    minutes = 0
    if clock:
        hour = int(clock.group(1)) % 12
        if clock.group(3) == "pm":
            hour += 12
        elif clock.group(3) is None:
            hour = int(clock.group(1))
        minutes = hour * 60 + int(clock.group(2))
    return (month, day, minutes)


# The order a reader wants: what arrived, what left, then movements with no
# side - internal transfers, then anything the run could not classify.
MOVE_GROUPS = ("+ In", "\u2212 Out", "\u00b1 Internal", "\u00b1 Unclassified")


def move_group(dirw, sign=""):
    """Which of the four groups a movement belongs to.

    >>> move_group("In", "+"), move_group("Out", "\u2212")
    ('+ In', '\u2212 Out')
    >>> move_group("Internal"), move_group("Anything else")
    ('\u00b1 Internal', '\u00b1 Unclassified')
    """
    _side, cls = money_side(dirw, sign)
    if cls == "pos":
        return MOVE_GROUPS[0]
    if cls == "neg":
        return MOVE_GROUPS[1]
    return MOVE_GROUPS[2] if str(dirw).strip().lower() == "internal" else MOVE_GROUPS[3]


def moves_in_order(moves=None):
    """FIN_MOVES grouped In, Out, Internal, Unclassified - newest first in each.

    A flat list in payload order made the reader do the grouping; the money that
    arrived and the money that left are different questions.
    """
    rows = list(FIN_MOVES if moves is None else moves)
    order = {g: i for i, g in enumerate(MOVE_GROUPS)}
    keyed = []
    for n, row in enumerate(rows):
        when, dirw, sign = row[0], row[6], row[7]
        stamp = _when_key(when)
        # unparseable stamps keep payload order, after the dated rows
        keyed.append((order[move_group(dirw, sign)],
                      0 if stamp else 1,
                      tuple(-v for v in stamp) if stamp else (n,), n, row))
    return [k[-1] for k in sorted(keyed, key=lambda k: k[:4])]


def money_side(dirw, sign=""):
    """Which side of zero a movement sits on, and in which color.

    Left/red for money leaving, right/green for money arriving, centered grey
    for a movement with no direction - a transfer between the owner's own
    accounts, or one the run could not classify. A centered bar reads as
    magnitude only, which is the honest drawing when direction is unknown.

    DIRECTION IS FREE TEXT and the run coins new words for it - "Receipt",
    "Refund", "Pending". An earlier version matched only "Out"/"Past due"/"In"
    and sent everything else to the RIGHT of zero, which is the inflow side, so
    a charge labelled "Receipt" drew a bar into positive territory while its own
    amount was printed in red. SIGN is the fallback precisely because it is the
    field that cannot be coined: the payload states it as + or the minus sign.

    Nothing unrecognised is ever drawn as an inflow.

    >>> money_side("Out"), money_side("In"), money_side("Internal")
    (('left', 'neg'), ('right', 'pos'), ('center', 'neu'))
    >>> money_side("Receipt", "\u2212")      # coined word, definite sign
    ('left', 'neg')
    >>> money_side("Receipt")                 # coined word, no sign
    ('center', 'neu')
    """
    if dirw in ("Out", "Past due"):
        return "left", "neg"
    if dirw == "In":
        return "right", "pos"
    if dirw == "Internal":
        return "center", "neu"
    if sign in ("\u2212", "-"):
        return "left", "neg"
    if sign == "+":
        return "right", "pos"
    return "center", "neu"


MONEY_COLORS = {"pos": "pos", "neg": "neg", "neu": "ink2"}


def money_bar(amt, dirw, sign="", axis=None, cls=""):
    w = _money_frac(amt, axis) * 50     # half-track either side of center
    side, fcls = money_side(dirw, sign)
    if side == "center":
        w /= 2                          # straddles zero: half each side
    n = _money_steps(axis)
    ticks = "".join(f'<i style="left:{50 + sgn * s * 50 / n:g}%"></i>'
                    for sgn in (-1, 1) for s in range(1, n + 1))
    return (f'<div class="{" ".join(filter(None, ("dbar", "money", cls)))}" aria-hidden="true">{ticks}'
            f'<div class="fill {fcls} {side}" style="width:{max(w, 1.5):.1f}%"></div></div>')
def money_head(label_left="Out \u2190", label_right="\u2192 In, USD"):
    """The column heading, with its "0" pinned to the axis centre.

    It used to be the plain string "Out <- 0 -> In, USD". The ruler under it
    positions its own 0 at 50%, but a run of text puts its characters wherever
    the glyphs fall - 30px to the left of the bars' zero, which is exactly the
    misreading a diverging chart cannot afford: the word "0" sat over negative
    territory. Same track width as the ruler and the bars, so all three agree.
    """
    return ('<div class="dhead" aria-hidden="true">'
            f'<span class="l">{e(label_left)}</span>'
            '<span class="c">0</span>'
            f'<span class="r">{e(label_right)}</span></div>')


def money_axis(axis=None, cls=""):
    """Minimal ticks: a notch at every even step, labels only at \u2212top, 0, +top."""
    axis = axis or FIN_AXIS
    mode, a, b = axis
    n = _money_steps(axis)
    t = [f'<i class="{"mj" if k in (-n, 0, n) else ""}" style="left:{50 + k * 50 / n:g}%"></i>'
         for k in range(-n, n + 1)]
    lo, mid, hi = money_labels(axis, unit="")
    for lab, p, c in ((lo, 0, "l"), (mid, 50, ""), (hi, 100, "r")):
        t.append(f'<span class="{c}" style="left:{p}%">{e(lab)}</span>')
    return (f'<div class="{" ".join(filter(None, ("daxis", "money", cls)))}" aria-hidden="true">'
            + "".join(t) + "</div>")
def money_axis_ticks_text():
    """The same axis as text, for the email (no ruler survives the sanitizer)."""
    _m, _a, b = FIN_AXIS
    return f"{money_tick(-b)} \u00b7 0 \u00b7 {money_tick(b)}"
def money_axis_note(axis=None):
    mode, a, b = axis or FIN_AXIS
    if mode == "linear":
        return (f"diverging, 0 at center \u2192 {money_tick(b)} each side; "
                f"even {_money_fmt(a)} steps")
    return f"diverging LOG scale, decade steps {_money_fmt(a)} \u2192 {_money_fmt(b)} each side"
def bar_div(pct, ax):
    n = _axis_marks(ax)
    w = min(abs(pct) / ax[1], 1.0) * 50
    side = "right" if pct >= 0 else "left"
    cls = "pos" if pct >= 0 else "neg"
    ticks = "".join(f'<i style="left:{50 + sgn * k * 50 / n:g}%"></i>'
                    for sgn in (-1, 1) for k in range(1, n + 1))
    return f'<div class="dbar" aria-hidden="true">{ticks}<div class="fill {cls} {side}" style="width:{max(w, 1.5):.1f}%"></div></div>'

def lead_inner(text):
    """Lead-in formatted for the FILE, without a list wrapper."""
    a, sep, b = lead_split(text)
    if a:
        return f'<span class="lead">{e(a)}</span>{e(sep.rstrip()) if sep.strip() == ":" else " —"} {e(b)}'
    return e(text)


def li_lead(text):
    """A bullet, or nothing at all: an empty string used to render as a bare dot."""
    return f"<li>{lead_inner(text)}</li>" if str(text).strip() else ""

def tdl(label, inner, cls=""):
    return f'<td class="{cls}" data-l="{attr(label)}">{inner}</td>'

def file_html():
    css = f"""
:root{{--bg:{D['bg']};--surface:{D['surface']};--surface-2:{D['surface2']};--ink:{D['ink']};--ink-2:{D['ink2']};--ink-3:{D['ink3']};--line:{D['line']};--line-strong:{D['lineS']};--accent:{D['accent']};--positive:{D['pos']};--negative:{D['neg']};--warning:{D['warn']};}}
@media (prefers-color-scheme: light){{:root:not([data-theme="dark"]){{--bg:{L['bg']};--surface:{L['surface']};--surface-2:{L['surface2']};--ink:{L['ink']};--ink-2:{L['ink2']};--ink-3:{L['ink3']};--line:{L['line']};--line-strong:{L['lineS']};--accent:{L['accent']};--positive:{L['pos']};--negative:{L['neg']};--warning:{L['warn']};}}}}
:root[data-theme="light"]{{--bg:{L['bg']};--surface:{L['surface']};--surface-2:{L['surface2']};--ink:{L['ink']};--ink-2:{L['ink2']};--ink-3:{L['ink3']};--line:{L['line']};--line-strong:{L['lineS']};--accent:{L['accent']};--positive:{L['pos']};--negative:{L['neg']};--warning:{L['warn']};}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Source Sans 3",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15.5px;line-height:1.55}}
h1,h2,h3,.lbl,.act-title{{font-family:Archivo,"Helvetica Neue",Arial,sans-serif}}
.mono{{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}}
a{{color:var(--accent);text-decoration:none}} a:hover{{text-decoration:underline}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 20px 60px}}
.mast{{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:22px 26px;display:grid;grid-template-columns:1.4fr 1fr;gap:18px}}
.mast h1{{margin:0 0 4px;font-size:30px;font-weight:700;letter-spacing:-.01em}}
.mast .date{{font-size:17px;color:var(--ink-2);font-weight:600}}
.mast .note{{margin-top:10px;font-size:13.5px;color:var(--ink-3)}} .mast .rev{{margin-top:6px;font-size:13px;color:var(--warning);font-weight:600}}
.stamps{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;align-content:start}}
.stamp .val{{font-size:13.5px;margin-top:2px}}
.lbl{{font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);font-weight:600}}
section{{margin-top:26px}}
h2{{font-size:19px;font-weight:700;margin:0 0 12px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}}
h2 .num{{color:var(--accent);font-weight:700}} h2 .sub{{font-family:"Source Sans 3",sans-serif;font-weight:400;color:var(--ink-3);font-size:13.5px}}
h3{{font-size:14.5px;font-weight:600;margin:16px 0 6px;color:var(--ink-2)}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px 20px}}
.actions{{display:grid;gap:8px}}
.act{{display:grid;grid-template-columns:6px 1fr;gap:14px;background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.act .stripe{{background:var(--ink-3)}} .act.warn .stripe{{background:var(--warning)}} .act.neg .stripe{{background:var(--negative)}} .act.ok .stripe{{background:var(--positive)}} .act.info .stripe{{background:var(--accent)}}
.act .body{{padding:11px 14px 11px 0}}
.act-title{{font-weight:600;font-size:15px}} .act .tag{{display:inline-block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;padding:1px 7px;border-radius:5px;border:1px solid var(--line-strong);color:var(--ink-2);margin-right:8px;vertical-align:middle}}
.act.warn .tag{{color:var(--warning);border-color:var(--warning)}} .act.ok .tag{{color:var(--positive);border-color:var(--positive)}} .act.info .tag{{color:var(--accent);border-color:var(--accent)}} .act.neg .tag{{color:var(--negative);border-color:var(--negative)}}
.act .det{{color:var(--ink-2);font-size:14px;margin-top:2px}}
.nothing{{color:var(--ink-3);font-style:italic;padding:8px 0}}
/* Section 1's rows carry the action bar's severity stripe, so one item reads
   as one item in both places. */
tr.hp>td:first-child{{border-left:6px solid var(--line-strong)}}
tr.hp.warn>td:first-child{{border-left-color:var(--warning)}}
tr.hp.neg>td:first-child{{border-left-color:var(--negative)}}
tr.hp.info>td:first-child{{border-left-color:var(--accent)}}
tr.hp.ok>td:first-child{{border-left-color:var(--positive)}}
.ringrow{{display:flex;align-items:center;gap:8px}} .ringrow .ring{{flex:0 0 auto}}
/* A summary tile says which way it points: in, owed, or neither. */
.tile.pos .v{{color:var(--positive)}} .tile.pos{{border-left-color:var(--positive)}}
.tile.neg .v{{color:var(--negative)}} .tile.neg{{border-left-color:var(--negative)}}
.tile .cur{{font-size:13px;font-weight:400;color:var(--ink-3)}}
.lead{{color:var(--accent);font-weight:600}}
.tbl-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface)}}
table{{border-collapse:collapse;width:100%;min-width:640px;font-size:14px}}
th{{text-align:left;font-family:Archivo,sans-serif;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);font-weight:600;padding:10px 12px;border-bottom:1px solid var(--line-strong);background:var(--surface-2)}}
th .qh,td.stamp[data-l]::before{{text-transform:none;letter-spacing:.01em;font-size:10px}}
td{{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}} tr:last-child td{{border-bottom:0}}
td.num{{text-align:right;white-space:nowrap}}
.dir-pos,.c-pos{{color:var(--positive);font-weight:600}} .dir-neg,.c-neg{{color:var(--negative);font-weight:600}} .dir-neu{{color:var(--ink-2);font-weight:600}} .c-accent{{color:var(--accent);font-weight:600}} .c-warn{{color:var(--warning);font-weight:600}} .muted{{color:var(--ink-3)}}
.badge{{display:inline-block;font-family:Archivo,sans-serif;font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:1px 6px;border-radius:4px;border:1px solid currentColor;margin-left:6px;vertical-align:middle;font-weight:600;white-space:nowrap}}
.legend{{font-size:12.5px;color:var(--ink-3);margin-top:8px}} .legend span{{margin-right:14px;white-space:nowrap;display:inline-block}}
.dbar{{position:relative;height:14px;width:150px;background:var(--surface-2);border:1px solid var(--line);border-radius:3px;box-sizing:border-box}}
.dbar i{{position:absolute;top:0;height:3px;width:1px;background:var(--line)}}
.dbar::before{{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line-strong);z-index:1}}
.dbar .fill{{position:absolute;top:3px;bottom:3px;min-width:3px;border-radius:2px}}
.dbar .fill.right{{left:50%}} .dbar .fill.left{{right:50%}} .dbar .fill.center{{left:50%;transform:translateX(-50%)}} .fill.pos{{background:var(--positive)}} .fill.neg{{background:var(--negative)}} .fill.neu{{background:var(--ink-3)}}
.daxis{{position:relative;height:16px;width:150px;margin-top:3px;box-sizing:border-box;border:1px solid transparent}}
.dbar.money,.daxis.money{{width:100%;min-width:150px;max-width:280px}}
/* A labelled money column: the label, the heading and the ruler share one box,
   so the label centres on the same zero the bars grow from. Left-aligned in the
   cell, it sat wherever the column happened to be wide. */
.dcol{{width:100%;min-width:150px;max-width:280px}}
.dcol .dlabel{{text-align:center}}
/* The heading's "0" must sit exactly over the ruler's, so it takes the ruler's
   width rule rather than a fixed one: in a wider column a 150px heading centred
   its zero 65px left of the bars' zero, over negative territory. */
.dhead{{position:relative;height:13px;width:100%;min-width:150px;max-width:280px}}
.dhead span{{position:absolute;top:0;white-space:nowrap}}
.dhead .l{{right:50%;margin-right:7px}} .dhead .c{{left:50%;transform:translateX(-50%)}} .dhead .r{{left:50%;margin-left:7px}}
.daxis i{{position:absolute;top:0;height:3px;width:1px;background:var(--line)}}
.daxis i.mj{{height:5px;background:var(--line-strong)}}
.daxis span{{position:absolute;top:5px;font:500 8.5px 'JetBrains Mono',monospace;letter-spacing:0;text-transform:none;color:var(--ink-3);transform:translateX(-50%)}}
.daxis span.l{{transform:none}} .daxis span.r{{transform:translateX(-100%)}}
.daxis-foot{{display:none}}
/* the figure sits centered over the track, i.e. over the axis zero the bar grows from */
.barfig{{display:block;text-align:center;margin-bottom:2px}}
.cap{{font-size:12.5px;color:var(--ink-3);padding:8px 2px}}
.tiles{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}}
.tile{{background:var(--surface-2);border-radius:10px;padding:12px 14px}} .tile .v{{font-size:22px;font-weight:700;margin:2px 0}} .tile .d{{font-size:12.5px;color:var(--ink-3)}}
ul{{margin:8px 0 0;padding-left:20px}} li{{margin:9px 0;line-height:1.55}}
.jobs li b{{font-weight:600}} .meta{{color:var(--ink-3);font-size:13px}}
.grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.grid3 .card{{min-width:0}} .grid3 h2{{font-size:17px}}
.grid3 .tbl-wrap table{{min-width:0;font-size:12px}} .grid3 th,.grid3 td{{padding:6px 6px}} .grid3 td.num{{white-space:normal}} .grid3 .dbar{{width:56px}} .grid3 .daxis{{width:56px}} .grid3 .daxis span.mid{{display:none}}
/* market + crypto carry TWO chart columns, so they span the grid rather than
   being squeezed into a third of it */
.grid3 .card.wide{{grid-column:1/-1}}
.grid3 .card.wide .tbl-wrap table{{font-size:14px}} .grid3 .card.wide th,.grid3 .card.wide td{{padding:9px 10px}}
.grid3 .card.wide .dbar,.grid3 .card.wide .daxis{{width:100%;min-width:120px;max-width:none}}
.hp{{border-left:4px solid var(--ink-3);padding:10px 14px;margin:10px 0;background:var(--surface-2);border-radius:0 8px 8px 0}} .hp.warn{{border-color:var(--warning)}} .hp.ok{{border-color:var(--positive)}} .hp.info{{border-color:var(--accent)}}
.hp .t{{font-weight:600;font-family:Archivo,sans-serif}} .hp.warn .t{{color:var(--warning)}} .hp.ok .t{{color:var(--positive)}} .hp.info .t{{color:var(--accent)}}
details{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 16px;margin-top:18px}} summary{{cursor:pointer;font-family:Archivo,sans-serif;font-weight:600;font-size:14px}}
.allow p{{font-size:12.5px;margin:6px 0}} .allow b{{color:var(--ink-2)}}
.src{{columns:2;column-gap:28px;font-size:11.5px;margin-top:8px}} .src p{{break-inside:avoid;margin:0 0 4px;overflow-wrap:anywhere}} .src b{{display:block;margin:8px 0 3px;color:var(--ink-2)}}
footer{{margin-top:28px;font-size:12.5px;color:var(--ink-3);border-top:1px solid var(--line);padding-top:14px}}
@media (max-width:940px){{.grid3{{grid-template-columns:1fr}} .mast{{grid-template-columns:1fr}} .tiles{{grid-template-columns:1fr}} .src{{columns:1}} .grid3 .tbl-wrap table{{font-size:14px}} .grid3 th,.grid3 td{{padding:9px 12px}} .grid3 .dbar{{width:150px}} .grid3 .daxis{{width:150px}} .grid3 .daxis span.mid{{display:block}}}}
@media (max-width:600px){{
 body{{font-size:17px;line-height:1.6}} .wrap{{padding:14px 10px 40px}} .mast{{padding:16px}} .mast h1{{font-size:26px}} .stamps{{grid-template-columns:1fr}} .stamp .val{{font-size:15px}}
 .card{{padding:14px}} .act{{grid-template-columns:5px 1fr;gap:10px}} .act-title{{font-size:16px}} .act .det{{font-size:15px}}
 .tbl-wrap{{border:0;background:transparent;overflow:visible}}
 table,thead,tbody,tr,td,th{{display:block;min-width:0;width:100%}} thead{{display:none}}
 tr{{background:var(--surface);border:1px solid var(--line);border-radius:10px;margin:0 0 10px;padding:6px 0}}
 td{{border:0;padding:5px 12px;font-size:15px;text-align:left!important;white-space:normal!important}}
 td[data-l]::before{{content:attr(data-l);display:block;font-family:Archivo,sans-serif;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin-bottom:1px}}
 td.num{{text-align:left}} .dbar,.daxis{{width:100%}} .grid3 .dbar{{width:100%}} .grid3 .daxis{{width:100%}} .daxis-foot{{display:block;margin:2px 12px 8px}}  /* 12px == td side padding, so the ruler lines up with the tracks */ .grid3 .tbl-wrap table{{font-size:15px}}
 li{{margin:11px 0}} .meta{{font-size:14px}} .legend span{{display:block;margin:2px 0}}
}}
"""
    o = []
    o.append(f"<title>{e(MAST['title'])}</title>")
    o.append('<meta name="color-scheme" content="dark light">')
    o.append('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    o.append('<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">')
    o.append(f"<style>{css}{SCAN_CSS}</style>")
    o.append('<div class="wrap">')
    o.append(f"""<header class="mast"><div><h1>{e(MAST['title'])}</h1><div class="date">{e(MAST['dateline'])}</div><div class="note">{e(MAST['note'])}</div><div class="rev">{e(MAST['revised'])}</div></div>
<div class="stamps">
<div class="stamp"><div class="lbl">Timezone</div><div class="val">{e(MAST['tz'])}</div></div>
<div class="stamp"><div class="lbl">Scheduled slot</div><div class="val mono">{e(MAST['slot'])}</div></div>
<div class="stamp"><div class="lbl">Window covered</div><div class="val mono">{e(MAST['window'])}</div></div>
<div class="stamp"><div class="lbl">Run stamp</div><div class="val mono">{e(MAST['run'])}</div></div>
</div></header>""")
    o.append(f'<section><h2>Needs you today <span class="sub">{e(actions_sub())}</span></h2><div class="actions">')
    tagmap = {"warn": "Check", "neg": "Urgent", "info": "Note", "ok": "Clear"}
    for sev, t, d in ACTIONS:
        o.append(f'<div class="act {sev}"><div class="stripe"></div><div class="body"><div class="act-title"><span class="tag">{tagmap[sev]}</span>{e(t)}</div><div class="det">{e(action_detail(t, d))}</div></div></div>')
    if not ACTIONS:
        o.append(f'<div class="nothing">{NOTHING_TODAY}</div>')
    o.append('</div></section>')
    # 4 high priority
    num = SectionNumber()
    o.append(f'<section><h2><span class="num">{num()}.</span> High priority <span class="sub">ranked by severity \u00b7 act on these first</span></h2><div class="card">')
    if not HIPRI:
        o.append(f'<div class="nothing">{e(nothing_new())}</div>')
    else:
        o.append('<div class="tbl-wrap"><table><thead><tr><th>What needs attention</th><th>Detail</th></tr></thead><tbody>')
    for sev, t, items in HIPRI:
        detail = "<br>".join(lead_inner(i) for i in items)
        # the chip rides WITH the title rather than in a column of its own: a
        # narrow column of its own wrapped "CHECK" to "CHEC/K" in mobile mail
        o.append(f'<tr class="hp {sev}">' + tdl("What needs attention",
                                                 f'{sev_chip(sev)} <b class="c-{sev}">{e(t)}</b>')
                 + tdl("Detail", detail) + '</tr>')
    o.append(('</tbody></table></div>' if HIPRI else '') + '</div></section>')
    # 1 jobs
    o.append(f'<section><h2><span class="num">{num()}.</span> Relevant job posts <span class="sub">{e(JOBS_RANKED_NOTE)}</span></h2><div class="card">')
    if not (JOBS_STATUS or JOBS_TOP or JOBS_OTHER):
        o.append(f'<div class="nothing">{e(nothing_new())}</div>')
    if JOBS_STATUS:
        o.append('<h3 style="margin-top:0">Application status</h3><ul class="jobs">')
        for t, m, d in JOBS_STATUS:
            o.append(f'<li><span class="lead">{e(t)}</span> <span class="meta">— {e(m)}</span><br>{e(d)}</li>')
        o.append('</ul>')
    if JOBS_TOP:
        o.append('<h3>Ranked leads</h3><div class="tbl-wrap"><table><thead><tr><th>Role</th><th>Company</th><th>Comp</th><th>Location</th><th>Source · received</th><th>Link</th></tr></thead><tbody>')
    for r, c, comp, loc, src, tier, link in JOBS_TOP:
        fit, fcls = job_fit(tier); lcls, ltag = loc_tier(loc)
        role = f'<b>{e(r)}</b>' + (f'<span class="badge c-{fcls}">{fit}</span>' if fit else "")
        compc = f'<span class="c-pos">{e(comp)}</span>' if comp != "not stated" else f'<span class="muted">{e(comp)}</span>'
        locc = f'<span class="c-accent">{e(loc)}</span>' if lcls else e(loc)
        o.append('<tr>' + tdl("Role", role) + tdl("Company", e(c)) + tdl("Comp", compc, "mono") + tdl("Location", locc) + tdl("Source · received", e(src), "meta") + tdl("Link", f'<a href="{url(link)}">open</a>') + '</tr>')
    if JOBS_TOP:
        o.append('</tbody></table></div><div class="legend"><span><b class="c-pos">Green</b> = comp stated</span><span><b class="c-accent">Teal</b> = ' + e(JOBS_TEAL_LABEL) + '</span><span><b class="c-warn">Amber</b> = deadline stated (none today)</span><span class="muted">Grey = not stated</span></div><div class="cap">' + e(JOBS_LEGEND_FIT) + '</div>')
    if JOBS_OTHER:
        o.append('<h3>Also seen (lower fit)</h3><ul class="jobs">')
        for r, c, loc, link in JOBS_OTHER:
            lcls, _ = loc_tier(loc)
            locc = f'<span class="c-accent">{e(loc)}</span>' if lcls else f'<span class="meta">{e(loc)}</span>'
            o.append(f'<li>{e(r)} — {e(c)} · {locc} · <a href="{url(link)}">link</a></li>')
        o.append('</ul>')
    o.append("".join(f'<p class="meta">{e(x)}</p>' for x in (ALIGNERR, JOBS_SKIPPED) if x) + '</div></section>')
    # 2 finances
    o.append(f'<section><h2><span class="num">{num()}.</span> Deposits &amp; finances</h2><div class="card">')
    if not (FIN_SUMMARY or FIN_MOVES or FIN_NOTES):
        o.append(f'<div class="nothing">{e(nothing_new())}</div>')
    if FIN_SUMMARY:
        tiles = []
        for l, v, d in FIN_SUMMARY:
            amount, cur = tile_amount(v)
            tiles.append(f'<div class="tile {tile_tone(l)}"><div class="lbl">{e(l)}</div>'
                         f'<div class="v mono">{e(amount)}'
                         + (f' <span class="cur">{e(cur)}</span>' if cur else "")
                         + f'</div><div class="d">{e(d)}</div></div>')
        o.append('<div class="tiles">' + "".join(tiles) + '</div>')
    if FIN_MOVES:
        o.append('<h3 style="margin-top:0">Money movements (outside → you / you → outside)</h3><div class="tbl-wrap"><table><thead><tr><th>When</th><th>Payee / source</th><th>Detail</th><th>Direction</th><th style="text-align:right">Amount</th><th>{head_html}{axis_html}</th></tr></thead><tbody>'.format(head_html=money_head(), axis_html=money_axis()))
        for when, payee, det, amt, cur, usd, dirw, sign in moves_in_order():
            cls = "dir-" + money_side(dirw, sign)[1]
            amt_s = money_amount(amt, cur, usd, sign)
            o.append('<tr>' + tdl("When", e(when), "mono") + tdl("Payee / source", e(payee)) + tdl("Detail", detail_html_file(det)) + tdl("Direction", f'<span class="{cls}">{e(sign)} {e(dirw)}</span>') + tdl("Amount", f'<span class="{cls}">{amt_s}</span>', "num mono") + tdl("Out ← 0 → In, USD", money_bar(usd, dirw, sign)) + '</tr>')
        o.append(f'</tbody></table></div><div class="daxis-foot">{money_head()}{money_axis()}<div class="meta">{money_axis_note()}</div></div><div class="cap">Bar axis, in USD: {money_axis_note()}. Amounts are shown in their original currency; bars are plotted from the USD equivalent. Money in = green on the right, out / past due = red on the left, no direction = neutral grey straddling zero (magnitude only — an internal or unclassified move has no side). The sign and direction word state it too.</div>')
    if ai_spend_rows():
        o.append('<h3>AI services — billed year to date</h3><div class="tbl-wrap"><table><thead><tr>'
                 '<th>Service</th><th style="text-align:right">Billed ' + e(AI_SPEND["year"]) + '</th>'
                 + '<th><div class="dcol"><div class="dlabel">New this window</div>'
                 + money_head() + money_axis(AI_AXIS, "ai") + '</div></th>'
                 '<th>Share AI spend (YTD)</th></tr></thead><tbody>')
        for row in ai_spend_rows():
            service, total, note = row[0], row[1], row[-1]
            new = ai_new(row)
            o.append('<tr>' + tdl("Service", f'<span class="lead">{e(service)}</span>')
                     + tdl("Billed", f'<span class="mono">{e(usd_str(total))}</span>', "num")
                     + tdl("New this window",
                           (f'<span class="dir-neg mono">{e(usd_str(new))}</span>'
                            + money_bar(abs(new), "Out", axis=AI_AXIS, cls="ai")) if new
                           else '<span class="muted">nothing new</span>')
                     + tdl("Share AI spend (YTD)",
                           f'<span class="ringrow">{ai_ring(ai_share(row))}<span>{e(note)}</span></span>') + '</tr>')
        o.append(f'</tbody></table></div><div class="cap">{e(ai_spend_caption())}</div>')
    if FIN_INTERNAL:
        o.append('<h3>Transfers between your own accounts</h3><div class="nothing">' + e(FIN_INTERNAL) + '</div>')
    if FIN_NOTES:
        o.append('<h3>Bills, statements &amp; notices</h3><ul>' + "".join(li_lead(n) for n in FIN_NOTES) + '</ul>')
    o.append('</div></section>')
    # 3 voip
    # 4 upcoming travel — flights, stays and other bookings, each carried until
    # its own date passes. Omitted when there is nothing booked at all, like
    # package tracking: the section exists to carry something forward.
    if FLIGHTS["legs"] or TRAVEL:
        o.append(f'<section><h2><span class="num">{num()}.</span> Upcoming travel <span class="sub">{e(TRAVEL_SUB)}</span></h2><div class="card">')
    if FLIGHTS["legs"]:
        o.append(f'<h3 style="margin-top:0">Flights</h3>')
        o.append(f'<p><span class="lead">{e(FLIGHTS["airline"])}, confirmation {e(FLIGHTS["conf"])}</span> — {e(FLIGHTS["pax"])}</p>')
        o.append(f'<p class="meta">{e(FLIGHTS["booked"])}</p>')
        # The on-time column exists only when at least one leg actually has a
        # record. A column of "not available" apologies costs a third of the table
        # width and tells the reader nothing they can act on.
        show_stats = any(g.get("stats") for g in FLIGHTS["legs"])
        show_terms = any(leg_terminals(g) for g in FLIGHTS["legs"])
        hdr = '<th>Date · flight</th><th>Departs (airport local)</th><th>Arrives (airport local)</th>'
        if show_terms:
            hdr += '<th>Terminal</th>'
        hdr += '<th>Airline</th><th>Confirmation</th>'
        if show_stats:
            hdr += '<th>Recent on-time record</th>'
        o.append(f'<div class="tbl-wrap"><table><thead><tr>{hdr}</tr></thead><tbody>')
        for g in FLIGHTS["legs"]:
            row = (tdl("Date · flight", f'{e(g["date"])}<br><a href="{url(g["fa"])}" class="mono">{e(g["flight"])}</a>')
                   + tdl("Departs (airport local)", f'{e(g["frm"])}<br><span class="mono">{e(g["dep"])}</span>')
                   + tdl("Arrives (airport local)", f'{e(g["to"])}<br><span class="mono">{e(g["arr"])}</span>'))
            if show_terms:
                lines = "<br>".join(e(t) for t in terminal_lines(g))
                row += tdl("Terminal", lines or '<span class="muted">not stated</span>', "meta")
            row += tdl("Airline", e(leg_airline(g)) or '<span class="muted">not stated</span>')
            row += tdl("Confirmation", f'<span class="mono">{e(leg_conf(g))}</span>' if leg_conf(g)
                       else '<span class="muted">not stated</span>')
            if show_stats:
                row += tdl("Recent on-time record", e(g.get("stats") or "not available"), "meta")
            o.append('<tr>' + row + '</tr>')
        o.append(f'</tbody></table></div><div class="cap">{e(FLIGHTS["note"])}</div>')
    if TRAVEL:
        o.append('<h3' + (' style="margin-top:0"' if not FLIGHTS["legs"] else "")
                 + '>Stays &amp; other bookings</h3><div class="tbl-wrap"><table><thead><tr>'
                 '<th>Type</th><th>Booking</th><th>Dates</th><th>Where</th><th>Confirmation</th></tr></thead><tbody>')
        for kind, what, when, where, conf, link, *rest in TRAVEL:
            source = booking_source(what, rest[0] if rest else "")
            booking = f'<span class="lead">{e(what)}</span>'
            if link.strip():
                booking = f'<a href="{url(link)}"><b>{e(what)}</b></a>'
            dates, times = booking_split(when)
            place, place_detail = booking_split(where)
            o.append('<tr>' + tdl("Type", e(kind))
                     + tdl("Booking", booking)
                     + tdl("Dates", f'<span class="mono">{e(dates)}</span>'
                           + (f'<br><span class="meta">{e(times)}</span>' if times else ""))
                     + tdl("Where", e(place) + (f'<br><span class="meta">{e(place_detail)}</span>' if place_detail else ""))
                     + tdl("Confirmation",
                           (f'<span class="mono">{e(conf)}</span>' if conf.strip()
                            else '<span class="muted">not stated</span>')
                           + (f'<br><span class="meta">{e(source)}</span>' if source else "")) + '</tr>')
        o.append(f'</tbody></table></div><div class="cap">{e(TRAVEL_NOTE)}</div>')
    if FLIGHTS["legs"] or TRAVEL:
        o.append('</div></section>')
    o.append(f'<section><h2><span class="num">{num()}.</span> VoIP voicemails &amp; texts <span class="sub">provider senders + Google Voice, Twilio, OpenPhone, Grasshopper, RingCentral, Dialpad</span></h2><div class="card">')
    if voip_empty():
        o.append(f'<div class="nothing">{e(nothing_new())}</div>')
    elif VOIP["headline"].strip():
        o.append(f'<div class="nothing">{e(VOIP["headline"])}</div>')
    if VOIP["messages"]:
        o.append('<div class="tbl-wrap"><table><thead><tr><th>When \u00b7 from</th><th>To \u00b7 type</th><th>Message</th></tr></thead><tbody>')
        for when, frm, to, kind, text in VOIP["messages"]:
            o.append('<tr>' + tdl("When \u00b7 from", f'<span class="mono">{e(when)}</span><br>{e(frm)}')
                     + tdl("To \u00b7 type", f'<span class="mono">{e(to)}</span><br><span class="meta">{e(kind)}</span>')
                     + tdl("Message", e(text)) + '</tr>')
        o.append('</tbody></table></div>')
    # last_msg and last_acct answer "is the line actually alive?" on a quiet
    # day, which is exactly the day the section is otherwise empty. Only the
    # plain-text body carried them; the file and the email dropped them.
    if voip_tail():
        o.append("<ul>" + "".join(li_lead(n) for n in voip_tail()) + "</ul>")
    o.append('</div></section>')
    # 5 USPS
    o.append(f'<section><h2><span class="num">{num()}.</span> USPS Informed Delivery <span class="sub">mail addressed to the intended recipient only; everyone else counted, never named</span></h2><div class="card">')
    if usps_empty():
        o.append(f'<div class="nothing">{e(nothing_new())}</div>')
    elif USPS["headline"].strip():
        o.append(f'<div class="nothing">{e(USPS["headline"])}</div>')
    # The headline already says how many pieces there were; an empty table
    # under it would only repeat that as a header with no rows.
    if USPS["pieces"]:
        o.append('<div class="tbl-wrap"><table><thead><tr><th>Date</th><th>Sender</th><th>Addressee (as printed)</th><th>Type / notes</th></tr></thead><tbody>')
        for d_, s_, a_, ty in USPS["pieces"]:
            o.append('<tr>' + tdl("Date", e(d_), "mono") + tdl("Sender", e(s_)) + tdl("Addressee (as printed)", e(a_), "mono") + tdl("Type / notes", e(ty), "meta") + '</tr>')
        o.append('</tbody></table></div>')
    for n, (uri, cap_) in enumerate(USPS_SCANS, 1):
        o.append(f'<figure class="scanfig" id="{scan_anchor(n)}"><img src="{url(uri)}" alt="Full mailpiece scan"><figcaption>{e(cap_)}</figcaption></figure>')
    # A detailed piece with no embedded scan is a gap the reader cannot see: the
    # page is the one place the image is meant to live, so say it is missing
    # rather than letting the section look complete.
    if USPS["pieces"] and not USPS_SCANS:
        o.append(f'<div class="nothing">{e(SCAN_MISSING)}</div>')
    counts = li_lead(USPS["counts"])
    o.append((f'<ul>{counts}</ul>' if counts else "")
             + (f'<p class="meta">{e(USPS["note"])}</p>' if USPS["note"].strip() else "")
             + '</div></section>')
    # Omitted entirely when the window carries no shipments, the way flights
    # are; the counter renumbers whatever follows. Shipments stay until the
    # carrier reports delivery, so a package in flight is never dropped.
    if PKG:
        o.append(f'<section><h2><span class="num">{num()}.</span> Package tracking <span class="sub">FedEx \u00b7 UPS \u00b7 USPS \u00b7 DHL \u00b7 merchant emails; kept until delivered</span></h2><div class="card"><div class="tbl-wrap"><table><thead><tr><th>Carrier</th><th>Tracking</th><th>Sender \u00b7 item</th><th>Recipient</th><th>Status</th><th>Est. arrival</th></tr></thead><tbody>')
        for car, trk, item, rcpt, st, eta in PKG:
            done = "dir-pos" if "deliver" in st.lower() else ""
            o.append('<tr>' + tdl("Carrier", e(car)) + tdl("Tracking", e(trk), "mono") + tdl("Sender \u00b7 item", e(item)) + tdl("Recipient", e(rcpt)) + tdl("Status", f'<span class="{done}">{e(st)}</span>', "meta") + tdl("Est. arrival", e(eta), "mono") + '</tr>')
        o.append(f'</tbody></table></div><p class="meta">{e(PKG_NOTE)}</p></div></section>')
    # Research cards are conditional: a card is drawn only when it has something
    # to show, and within a card each table only when it has rows. A heading over
    # an empty table reads as missing data, not as a quiet day. Every card also
    # closes itself - the market card used to stay open and swallow the cards
    # after it. Every card spans the full grid width: that is how they have
    # always looked, because the swallowed cards inherited the market card's
    # width, and a one-third column squeezes the AI and journal tables unreadably.
    research = []
    if MKT_ROWS or FUNDS or STOCKS:
        research.append('<div class="card wide"><h2>US market</h2>')
        if MKT_ROWS:
            stamp = shared_asof([r[8:] for r in MKT_ROWS])
            research.append('<div class="tbl-wrap"><table><thead><tr><th>Index</th><th style="text-align:right">{3}</th><th>1D{0}</th><th>1W{1}</th><th>YTD{2}</th></tr></thead><tbody>'.format(axis_div(MKT_24), axis_div(MKT_7D), axis_div(MKT_YTD), quote_head("Close", stamp)))
            for n, c, p1, v1, p7, v7, py, vy, *asof in MKT_ROWS:
                research.append('<tr>' + tdl("Index", e(n), "mono")
                                + tdl(quote_head_text("Close", stamp), quote_cell_file(c, v1, [] if stamp else asof), "num mono stamp")
                                + tdl("1D", horizon_cell_file(p1, v1, MKT_24, "pts"))
                                + tdl("1W", horizon_cell_file(p7, v7, MKT_7D, "pts"))
                                + tdl("YTD", horizon_cell_file(py, vy, MKT_YTD, "pts")) + '</tr>')
            research.append(f'</tbody></table></div>{axis_foot(MKT_24, "1D move, % of prior close")}{axis_foot(MKT_7D, "1W move, %")}{axis_foot(MKT_YTD, "YTD move, %")}<div class="cap">1D = close → close vs the prior session; 1W = trailing 5 sessions (one trading week); YTD = since the last close of the previous year. All in index points and %. {axis_note(MKT_24, "1D axis")}; {axis_note(MKT_7D, "1W axis")}; {axis_note(MKT_YTD, "YTD axis")}.</div>')
        if FUNDS:
            stamp = shared_asof([r[9] for r in FUNDS])
            # The trailing "As of" column exists to date a NAV. Once every NAV
            # carries the same date in the heading, the column is the same
            # string N more times, so it goes.
            asof_th = "" if stamp else "<th>As of</th>"
            research.append(f'<h3>Vanguard funds</h3><div class="tbl-wrap"><table><thead><tr><th>Fund</th><th style="text-align:right">{quote_head("NAV", stamp)}</th><th>1D{axis_div(FUND_1D)}</th><th>1W{axis_div(FUND_1W)}</th><th>YTD{axis_div(FUND_YTD)}</th>{asof_th}</tr></thead><tbody>')
            for tk, nm, nav, a1, v1, a7, v7, ay, vy, asof, note in FUNDS:
                research.append('<tr>' + tdl("Fund", f'<span class="lead">{e(tk)}</span><br><span class="meta">{e(nm)}</span>', "mono")
                                + tdl(quote_head_text("NAV", stamp), quote_cell_file(nav, v1, [] if stamp else asof), "num mono stamp")
                                + tdl("1D", horizon_cell_file(a1, v1, FUND_1D))
                                + tdl("1W", horizon_cell_file(a7, v7, FUND_1W))
                                + tdl("YTD", horizon_cell_file(ay, vy, FUND_YTD))
                                + ("" if stamp else tdl("As of", f'<span class="meta">{e(with_year(asof))}</span>')) + '</tr>')
            research.append(f'</tbody></table></div>{axis_foot(FUND_1D, "1D NAV change, %")}{axis_foot(FUND_1W, "1W NAV change, %")}{axis_foot(FUND_YTD, "YTD NAV change, %")}<div class="cap">Change from the prior published NAV (1D), over one trading week (1W), and since the previous year-end (YTD) - each in $ and %. {axis_note(FUND_1D, "1D axis")}; {axis_note(FUND_1W, "1W axis")}; {axis_note(FUND_YTD, "YTD axis")}. ' + e(" ".join(f"{tk}: {note}" for tk, nm, nav, a1, v1, a7, v7, ay, vy, asof, note in FUNDS)) + '</div>')
        if STOCKS:
            stamp = shared_asof([r[8:] for r in STOCKS])
            research.append(f'<h3>Large caps</h3><div class="tbl-wrap"><table><thead><tr><th>Ticker</th><th style="text-align:right">{quote_head("Price", stamp)}</th><th>1D{axis_div(STK_1D)}</th><th>1W{axis_div(STK_1W)}</th><th>YTD{axis_div(STK_YTD)}</th></tr></thead><tbody>')
            for tk, pr, a1, v1, a7, v7, ay, vy, *asof in STOCKS:
                research.append('<tr>' + tdl("Ticker", f'<span class="lead">{e(tk)}</span>', "mono")
                                + tdl(quote_head_text("Price", stamp), quote_cell_file(pr, v1, [] if stamp else asof), "num mono stamp")
                                + tdl("1D", horizon_cell_file(a1, v1, STK_1D))
                                + tdl("1W", horizon_cell_file(a7, v7, STK_1W))
                                + tdl("YTD", horizon_cell_file(ay, vy, STK_YTD)) + '</tr>')
            research.append(f'</tbody></table></div>{axis_foot(STK_1D, "1D move, %")}{axis_foot(STK_1W, "1W move, %")}{axis_foot(STK_YTD, "YTD move, %")}<div class="cap">Same horizons as the indexes, each in $ per share and %. {axis_note(STK_1D, "1D axis")}; {axis_note(STK_1W, "1W axis")}; {axis_note(STK_YTD, "YTD axis")}.</div>')
        research.append('</div>')
    if CRYPTO_ROWS or CRYPTO_BULLETS:
        research.append('<div class="card wide"><h2>Cryptocurrency</h2>')
        if CRYPTO_ROWS:
            stamp = shared_asof([r[8:] for r in CRYPTO_ROWS])
            research.append(f'<div class="tbl-wrap"><table><thead><tr><th>Asset</th><th style="text-align:right">{quote_head("Price", stamp)}</th><th>1D{axis_div(CRY_24)}</th><th>1W{axis_div(CRY_7D)}</th><th>YTD{axis_div(CRY_YTD)}</th></tr></thead><tbody>')
            for n, pr, v1, a1, v7, a7, vy, ay, *asof in CRYPTO_ROWS:
                research.append('<tr>' + tdl("Asset", f'<span class="lead">{e(n)}</span>', "mono")
                                + tdl(quote_head_text("Price", stamp), quote_cell_file(pr, v1, [] if stamp else asof), "num mono stamp")
                                + tdl("1D", horizon_cell_file(a1, v1, CRY_24, reverse=True))
                                + tdl("1W", horizon_cell_file(a7, v7, CRY_7D, reverse=True))
                                + tdl("YTD", horizon_cell_file(ay, vy, CRY_YTD, reverse=True)) + '</tr>')
            research.append(f'</tbody></table></div>{axis_foot(CRY_24, "1D change, %")}{axis_foot(CRY_7D, "1W change, %")}{axis_foot(CRY_YTD, "YTD change, %")}<div class="cap">1D = rolling 24 h; 1W = rolling 7 days; YTD = since the last price of the previous year - crypto trades continuously, so there is no daily close and every window is measured back from the quote time. Each given as % and $. {axis_note(CRY_24, "1D axis")}; {axis_note(CRY_7D, "1W axis")}; {axis_note(CRY_YTD, "YTD axis")}. {e(CRYPTO_NOTE)}</div>')
        if CRYPTO_BULLETS:
            research.append('<ul>' + "".join(li_lead(b) for b in CRYPTO_BULLETS) + '</ul>')
        research.append('</div>')
    if MACRO_ROWS or JOBS_SECTORS:
        research.append('<div class="card wide"><h2>Fed &amp; labor market</h2>')
        if MACRO_ROWS:
            research.append('<div class="tbl-wrap"><table><thead><tr><th>Indicator</th><th>Latest</th><th>Change · context</th><th>As of</th></tr></thead><tbody>')
            for name, latest, context, asof in MACRO_ROWS:
                research.append('<tr>' + tdl("Indicator", f'<span class="lead">{e(name)}</span>')
                                + tdl("Latest", macro_cell(latest, name, context))
                                + tdl("Change · context", e(context))
                                + tdl("As of", f'<span class="meta">{e(with_year(asof))}</span>') + '</tr>')
            research.append('</tbody></table></div>')
        if JOBS_SECTORS:
            research.append('<h3>Jobs by sector</h3><div class="tbl-wrap"><table><thead><tr><th>Sector</th><th style="text-align:right">Payrolls</th><th>Context</th><th>As of</th></tr></thead><tbody>')
            for sector, change, context, asof in JOBS_SECTORS:
                cls = "dir-pos" if not str(change).lstrip().startswith(("\u2212", "-")) else "dir-neg"
                research.append('<tr>' + tdl("Sector", e(sector))
                                + tdl("Payrolls", f'<span class="{cls} mono">{e(change)}</span>', "num")
                                + tdl("Context", e(context))
                                + tdl("As of", f'<span class="meta">{e(with_year(asof))}</span>') + '</tr>')
            research.append('</tbody></table></div>')
        research.append(f'<div class="cap">{e(MACRO_NOTE)}</div></div>')
    if AI_ITEMS:
        research.append('<div class="card wide"><h2>AI &amp; programming</h2><div class="tbl-wrap"><table><thead><tr><th>Item</th><th>What it means</th><th>Source</th></tr></thead><tbody>')
        for t, d, link in AI_ITEMS:
            research.append('<tr>' + tdl("Item", f'<span class="lead">{e(t)}</span>')
                            + tdl("What it means", e(d))
                            + tdl("Source", f'<a href="{url(link)}">open</a>') + '</tr>')
        research.append('</tbody></table></div></div>')
    # No papers means no card - it used to print "Journals scanned: ;".
    if JOURNAL_ITEMS:
        research.append('<div class="card wide"><h2>Research &amp; publications</h2><div class="tbl-wrap"><table><thead><tr><th>Journal \u00b7 date</th><th>Paper</th><th>Takeaway</th></tr></thead><tbody>')
        for j, t, au, d, tk, link in JOURNAL_ITEMS:
            research.append('<tr>' + tdl("Journal \u00b7 date", f'<span class="lead">{e(j)}</span><br><span class="meta">{e(d)}</span>')
                            + tdl("Paper", f'<a href="{url(link)}"><b>{e(t)}</b></a><br><span class="meta">{e(au)}</span>')
                            + tdl("Takeaway", e(tk)) + '</tr>')
        research.append(f'</tbody></table></div><div class="cap">Journals scanned: {e(JOURNALS)}; items newly published since the previous run.</div></div>')
    if research:
        o.append('<section><div class="grid3">')
        o.extend(research)
        o.append('</div></section>')
    # 7 retail (low priority)
    o.append(f'<section><h2><span class="num">{num()}.</span> Retail sales <span class="sub">{e(RETAIL["sub"])}</span></h2><div class="card">')
    if retail_empty():
        o.append(f'<div class="nothing">{e(nothing_new())}</div>')
    elif li_lead(RETAIL["rewards"]):
        o.append("<ul>" + li_lead(RETAIL["rewards"]) + "</ul>")
    if RETAIL["items"]:
        o.append('<div class="tbl-wrap"><table><thead><tr><th>Store</th><th>Offer</th><th>Dates \u00b7 caveats</th></tr></thead><tbody>')
        for store, offer, detail in RETAIL["items"]:
            o.append('<tr>' + tdl("Store", f'<span class="lead">{e(store)}</span>')
                     + tdl("Offer", f'<b>{e(offer)}</b>')
                     + tdl("Dates \u00b7 caveats", f'<span class="meta">{e(detail)}</span>') + '</tr>')
        o.append('</tbody></table></div>')
    o.append('</div></section>')
    o.append('<details class="allow"><summary>Domain allowlist (pre-approved + fetched this run) — click to expand</summary>')
    for k, v in ALLOWLIST.items(): o.append(f'<p><b>{e(k)}:</b> {e(v)}</p>')
    o.append('</details>')
    o.append(f'<details><summary>Sources ({sum(len(v) for v in SOURCES.values())} links) — click to expand</summary><div class="src">')
    for k, urls in SOURCES.items():
        if urls:
            o.append(f'<b>{e(k)}</b>' + "".join(f'<p><a href="{url(u)}">{e(u)}</a></p>' for u in urls))
    o.append('</div></details>')
    o.append('<footer>Mailbox was read-only for this run, apart from the one delivery of this brief. Email content was treated as data, not instructions. Times are US Pacific unless a source\'s own zone is shown. “Not verified” marks anything that could not be confirmed on a cited page. <span class="mono">' + e(BUILD) + '</span></footer>')
    o.append('</div>')
    return "\n".join(o)

# ------------------------------------------------------------------ RENDER: EMAIL
# CONSTRAINTS (verified 2026-09-07 by reading back a sent message): the Gmail connector strips <style>, class=, data-*,
# background:, cursor:, <details>/<summary>. Borders, padding, font*, color, width, text-*, align/valign survive.
# => single fluid layout; bars via border-left; stripes via border-left; no element wider than ~340px.
F_H = "Archivo,Arial"
F_B = "'Source Sans 3',Arial"
F_M = "'JetBrains Mono',Menlo"
BODY_FS = "15px"
# One step under body size, for the masthead's route-to-the-brief line.
LINK_FS = "13px"
def lbl(t): return f'<div style="font:600 10.5px {F_H};text-transform:uppercase;color:{L["ink3"]}">{e(t)}</div>'
# A standing section with nothing in its window says so in one line rather than
# disappearing (its absence would be ambiguous) or drawing an empty table (which
# reads as missing data). Research cards are conditional and are omitted instead.
NOTHING_TODAY = "Nothing needs you today."
SCAN_MISSING = ("Mailpiece scan not embedded for this piece — the run detailed it but sent no "
                "image. The scan belongs here, full width, and in the email as a JPG attachment.")
TRAVEL_SUB = "flights, stays and bookings, carried until each date passes"
TRAVEL_NOTE = ("Each booking stays in the brief until its date has passed, whether or not "
               "new mail about it arrived in the window.")


def nothing_new():
    """One line for a standing section whose window brought nothing.

    It names the window, because "nothing new" alone leaves the reader asking
    nothing new SINCE WHEN - and on a late or long run that is exactly the
    question. The section keeps its heading: its absence would be ambiguous.
    """
    return f"No new data in this period ({MAST['window']})."


def _norm(text):
    return _re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def action_detail(title, detail):
    """An action row's detail, or a pointer when High priority repeats it.

    The bar and section 1 are written from the same facts, so a run that puts
    an item in both prints the same sentence twice, one under the other. The
    row stays - the bar is what the reader acts from - but its detail becomes
    a pointer, and nothing is lost: the full text is directly below.
    """
    if any(_norm(t) == _norm(title) for _sev, t, _items in HIPRI):
        return DETAIL_IN_HIPRI
    return detail


DETAIL_IN_HIPRI = "Detail in 1. High priority, below."


def tile_tone(label):
    """Which way a summary tile reads: money in, money owed, or neither.

    From the tile's own label, because the payload states the figure and not
    its sense. Anything unrecognised stays neutral - a grey tile is merely
    quiet, a wrongly green one says the opposite of the truth.

    >>> tile_tone("In from outside"), tile_tone("Outstanding"), tile_tone("Moved internally")
    ('pos', 'neg', 'neu')
    """
    t = _norm(label)
    if any(w in t for w in ("in from outside", "received", "deposits", "income", "paid to you")):
        return "pos"
    if any(w in t for w in ("outstanding", "owed", "due", "bills", "payable", "out to")):
        return "neg"
    return "neu"


def tile_amount(value):
    """(the figure, its trailing currency) - "$1,326.64 USD" reads as two things.

    The currency is set quietly beside the amount rather than inside it, so the
    number stays the thing the eye lands on.
    """
    v = str(value).strip()
    m = _re.match(r"^(.*?)(?:\s+([A-Z]{3}))$", v)
    if m:
        return m.group(1), m.group(2)
    return v, ("USD" if v[:1] in "$-\u2212+" or v[:2] in ("MX", "US") else "")


def actions_sub():
    """Subtitle for the action bar, counted from the rows it sits above.

    It read "nothing expires before tomorrow's run" whatever the rows said, so a
    bar whose top row expired that night contradicted its own heading - and
    "tomorrow" is wrong on any cadence but daily.
    """
    urgent = sum(1 for sev, _t, _d in ACTIONS if sev == "neg")
    if not urgent:
        return "ranked; nothing here is marked urgent before the next run"
    return f"ranked; {urgent} urgent before the next run"


def usd_str(amount):
    """A USD figure, formatted the way every money column in the brief is.

    NOT named usd(): `usd` is a loop variable in the money-movement rows, and a
    module-level function of that name is shadowed inside those functions.
    """
    return f"${amount:,.2f}"


def ai_spend_rows():
    """The AI billing rows, or nothing when the payload carries no AI_SPEND."""
    return (AI_SPEND or {}).get("rows") or []


def ai_new(row):
    """What this service billed in THIS window (0.0 on a row written before the field)."""
    return float(row[2]) if len(row) > 3 else 0.0


def ai_share(row):
    """The share percentage as a number, read back from the row's own note.

    The note is the authority - `brief ai-spend` computes it - so the ring and
    the words can never disagree.
    """
    m = _re.match(r"\s*(\d+(?:\.\d+)?)\s*%", str(row[-1]))
    return float(m.group(1)) if m else None


def ai_ring(pct, size=26):
    """A small ring showing one service's share, for the page.

    An inline SVG, because the email's sanitizer strips it and the page is where
    a reader compares services at a glance. aria-hidden: the same percentage is
    written beside it in words.
    """
    if pct is None:
        return ""
    r = (size - 5) / 2
    circ = 2 * 3.141592653589793 * r
    on = max(0.0, min(pct, 100.0)) / 100 * circ
    return (f'<svg class="ring" width="{size}" height="{size}" viewBox="0 0 {size} {size}" aria-hidden="true">'
            f'<circle cx="{size/2:g}" cy="{size/2:g}" r="{r:g}" fill="none" stroke="var(--line-strong)" stroke-width="3"/>'
            f'<circle cx="{size/2:g}" cy="{size/2:g}" r="{r:g}" fill="none" stroke="var(--accent)" stroke-width="3"'
            f' stroke-linecap="round" stroke-dasharray="{on:.1f} {circ - on:.1f}"'
            f' transform="rotate(-90 {size/2:g} {size/2:g})"/></svg>')


def ai_spend_total():
    return sum(float(r[1]) for r in ai_spend_rows())


def ai_spend_caption():
    """Says what the figure is and, plainly, what it is not.

    Nothing is back-dated: the count starts when a service is first seen, so a
    reader must not mistake it for a full year of billing.
    """
    note = (AI_SPEND or {}).get("note") or ""
    base = (f"Billed {AI_SPEND['year']} to date across {len(ai_spend_rows())} service(s): "
            f"{usd_str(ai_spend_total())}. Counted from billing emails as they arrive - earlier "
            f"charges are not back-dated - and reset to $0.00 on 1 January.")
    return f"{base} {note}".strip()


_CONF_PART = _re.compile(r"\(([^)]+)\)\s*$")


def leg_conf(leg):
    """The confirmation code for THIS leg, not every code on the booking.

    A trip flown on two airlines arrives as one string - "MOCKR1 / MOCKR2
    (Delta) \u00b7 FAKEA9 (Alaska)" - and printing it against every row makes the
    reader work out which code belongs to the flight they are looking at. When
    the booking labels its codes by airline, the leg's own carrier picks one.
    A leg that carries its own "conf" always wins; an unlabelled or unmatched
    string is printed whole rather than guessed at, because a wrong code at a
    desk is worse than a long one.
    """
    own = str(leg.get("conf") or "").strip()
    if own:
        return own
    booking = str(FLIGHTS.get("conf") or "").strip()
    parts = [p.strip() for p in _re.split(r"\s*[\u00b7;]\s*", booking) if p.strip()]
    if len(parts) < 2:
        return booking
    airline = _leg_airline(leg)
    if not airline:
        return booking
    for part in parts:
        m = _CONF_PART.search(part)
        if m and airline.lower() in m.group(1).strip().lower():
            return part[:m.start()].strip() or part
    return booking


def _leg_airline(leg):
    """The airline name for a leg, from its flight number's IATA prefix."""
    m = _re.match(r"\s*([A-Z0-9]{2})\s*\d", str(leg.get("flight") or "").upper())
    return AIRLINE_NAMES.get(m.group(1)) if m else None


def leg_airline(leg):
    """Who flies THIS leg, for the table's own column.

    A connection is often sold by one airline and flown by another, and the
    booking headline names only the seller - so "DL 2200" and "B6 88" under
    one Delta record are two different check-in desks. The leg's own "airline"
    wins; otherwise the flight number's IATA prefix names the carrier. When
    neither does, the booking's airline stands in ONLY where the booking names
    a single airline: on a two-airline record it would be a coin toss, and a
    reader sent to the wrong desk is worse served than one sent to none.

    >>> FLIGHTS.update({"airline": "Northwind Air"})
    >>> leg_airline({"flight": "B6 88"}), leg_airline({"flight": "ZZ 1"})
    ('Alaska', 'Northwind Air')
    >>> leg_airline({"flight": "ZZ 1", "airline": "Cascade Air"})
    'Cascade Air'
    """
    own = str(leg.get("airline") or "").strip()
    if own:
        return own
    named = _leg_airline(leg)
    if named:
        return named
    booking = str(FLIGHTS.get("airline") or "").strip()
    return "" if _re.search(r"[/&\u00b7]| and ", booking) else booking


def leg_terminals(leg):
    """Departure and arrival terminal/gate text, as the airline stated it."""
    return str(leg.get("term") or "").strip()


_AIRPORT = _re.compile(r"\(([A-Z]{3})\)")


def terminal_lines(leg):
    """One line per airport: ["DEN: Terminal A, gate A12", "ORD: Terminal 2"].

    A run writes the pair as one string - "Terminal A, gate A12 \u2192 Terminal 2" -
    which reads as a sentence when what a traveller wants is a label per
    airport. The codes come from the leg's own from/to, so a string this cannot
    split is returned whole rather than guessed at.

    >>> terminal_lines({"frm": "Denver (DEN)", "to": "Chicago (ORD)",
    ...                 "term": "Terminal A, gate A12 \u2192 Terminal 2"})
    ['DEN: Terminal A, gate A12', 'ORD: Terminal 2']
    >>> terminal_lines({"frm": "Denver (DEN)", "to": "Chicago (ORD)", "term": "Terminal 2"})
    ['Terminal 2']
    >>> terminal_lines({"frm": "", "to": "", "term": ""})
    []
    """
    text = leg_terminals(leg)
    if not text:
        return []
    parts = [p.strip() for p in _re.split(r"\s*(?:\u2192|->|;)\s*", text) if p.strip()]
    codes = [(_AIRPORT.search(str(leg.get(k) or "")) or [None]) for k in ("frm", "to")]
    codes = [m.group(1) if hasattr(m, "group") else None for m in codes]
    if len(parts) != 2 or not all(codes):
        return parts
    return [f"{code}: {part}" for code, part in zip(codes, parts)]


_GENERIC_PROPERTY = _re.compile(r"\b(the property|the hotel|the venue|the operator)\b", _re.I)


_MONTH = _re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
                     r"(\s+\d{1,2})?\b")


def brief_year():
    """The year this brief is for, from its own dateline."""
    m = _re.search(r"\b(20\d{2})\b", str(MAST.get("dateline") or "") + " " + str(FILE_STAMP))
    return m.group(1) if m else ""


def with_year(text):
    """An as-of that names a month but no year gets this brief's year.

    "Feb data" is ambiguous the moment a brief is read in March of the next
    year - or carried forward, or opened out of the archive. A string that
    already states a year, or names no month at all, is left alone.

    >>> MAST["dateline"] = "Tuesday, March 3, 2026"
    >>> with_year("Feb data"), with_year("as of Mar 2")
    ('Feb 2026 data', 'as of Mar 2, 2026')
    >>> with_year("Feb 2025 data"), with_year("last close"), with_year("")
    ('Feb 2025 data', 'last close', '')
    """
    text = str(text or "")
    year = brief_year()
    if not text or not year or _re.search(r"\b(19|20)\d{2}\b", text):
        return text
    m = _MONTH.search(text)
    if not m:
        return text
    sep = ", " if m.group(2) else " "
    return text[:m.end()] + sep + year + text[m.end():]


def asof_str(asof):
    """The as-of a quote row states, as a string - "" when it states none.

    Rows carry it either as the tail of a starred unpack (a list) or as a
    plain field, so both shapes arrive here.
    """
    if isinstance(asof, (list, tuple)):
        asof = asof[0] if asof else ""
    return str(asof or "").strip()


def shared_asof(values):
    """The one as-of that EVERY row states, or "" when they differ.

    A quote table is read at one moment, so its rows normally carry the same
    stamp - and printed down the column it repeated "Mon Mar 2, 4:00 PM EST
    close" against every index, wrapping onto three lines and tripling the
    height of the table to say nothing new. When they agree it moves into the
    column heading; when they do not (a fund priced last night beside one
    priced this morning) each row keeps its own, because then it is news.
    """
    stamps = {asof_str(v) for v in values}
    return next(iter(stamps)) if len(stamps) == 1 and all(stamps) else ""


def quote_head_text(word, stamp):
    """A quote column's heading: "Mon Mar 2, 4:00 PM EST close", or just the word.

    The word goes last so the column still reads as a close, a NAV or a price.
    A stamp that already names a quote - "Mon Mar 2 close (5:48 PM ET)" - is
    left alone rather than made to read "close ... NAV".

    >>> quote_head_text("Close", "Mon Mar 2, 4:00 PM EST")
    'Mon Mar 2, 4:00 PM EST close'
    >>> quote_head_text("NAV", "Mon Mar 2, 5:48 PM ET")
    'Mon Mar 2, 5:48 PM ET NAV'
    >>> quote_head_text("NAV", "Mon Mar 2 close (5:48 PM ET)"), quote_head_text("Price", "")
    ('Mon Mar 2 close (5:48 PM ET)', 'Price')
    """
    if not stamp:
        return word
    if _re.search(r"\b(close|nav|price)\b", stamp, _re.I):
        return stamp
    return f"{stamp} {word if word.isupper() else word.lower()}"   # NAV is an acronym


def quote_head(word, stamp):
    """That heading for the page. A stamped heading keeps its own casing and
    tighter tracking: the column's uppercase letter-spacing on a whole date
    would push the money columns off their axes."""
    if not stamp:
        return e(word)
    return f'<span class="qh">{e(quote_head_text(word, stamp))}</span>'


def _asof_text(asof):
    """" (as of 4:00 PM EST)" when the row states a time, else nothing."""
    when = asof_str(asof)
    return f" (as of {when})" if when else ""


def quote_cell_file(value, pct, asof, cls="mono"):
    """A close, NAV or price for the page: coloured by its own 1D move, with the
    time it was taken under it when the run states one."""
    tone = {"pos": "dir-pos", "neg": "dir-neg", "neu": ""}[move_tone(pct)]
    inner = f'<span class="{tone}">{e(value)}</span>'
    when = asof_str(asof)
    return inner + (f'<br><span class="meta">{e(when)}</span>' if when else "")


def quote_cell_email(value, pct, asof):
    """The same, for the email: inline colour, and the time beneath."""
    col = {"pos": L["pos"], "neg": L["neg"], "neu": L["ink"]}[move_tone(pct)]
    when = asof_str(asof)
    return sp(e(value), col) + (f'<br>{small(e(when))}' if when else "")


def macro_cell(value, indicator, change):
    """A macro figure for the page, coloured by what the move MEANS."""
    tone = {"pos": "dir-pos", "neg": "dir-neg", "neu": ""}[macro_tone(indicator, change)]
    return f'<b class="{tone} mono">{e(value)}</b>'


def booking_source(what, source):
    """Where a booking was made, with the generic word replaced by the name.

    "Booked direct with the property" tells a reader nothing they cannot see;
    "Booked direct with Northwind Harbor Hotel" is who to call. The run writes
    either, so the renderer names it.

    >>> booking_source("Northwind Harbor Hotel", "Booked direct with the property")
    'Booked direct with Northwind Harbor Hotel'
    >>> booking_source("Northwind Harbor Hotel", "Booking.com")
    'Booking.com'
    >>> booking_source("", "Booked direct with the property")
    'Booked direct with the property'
    """
    name = str(what or "").strip()
    text = str(source or "").strip()
    return _GENERIC_PROPERTY.sub(name, text) if name else text


def booking_split(text):
    """A booking field as (what it says first, the fine print after it).

    A run writes one field as "Mon, Sep 21 → Wed, Sep 23, 2026 (2 nights) ·
    check-in 3:00 PM, check-out 11:00 AM property-local time". Printed as one
    run of text in a narrow column that is a wall. The part before the first
    "\u00b7" is what the reader scans for - the dates, the room, the seat - and
    the rest is detail that belongs under it, smaller.
    """
    head, _, rest = str(text or "").partition("\u00b7")
    return head.strip(), rest.strip()


def voip_empty():
    """Nothing to show at all - not a message, not a note, not even a headline."""
    return not (VOIP["messages"] or voip_tail() or VOIP["headline"].strip())


def usps_empty():
    return not (USPS["pieces"] or USPS_SCANS or USPS["counts"].strip()
                or USPS["headline"].strip() or USPS["note"].strip())


def retail_empty():
    return not (RETAIL["items"] or RETAIL["rewards"].strip())


def voip_tail():
    """The VoIP notes, then the lines that say whether the line is alive.

    The last inbound message is named only when the window had none - otherwise
    it is already the newest row of the table, and would be printed twice. The
    last account notice is not a message, so it always appears when known.
    """
    last = [] if VOIP["messages"] else [VOIP.get("last_msg")]
    return list(VOIP["notes"]) + [x for x in last + [VOIP.get("last_acct")] if x]


def h2(t, sub=""):
    s_ = (f' <span style="font-family:{F_B};font-weight:400;font-size:13px;color:{L["ink3"]}">{e(sub)}</span>') if sub else ""
    return f'<div style="font-family:{F_H};font-size:19px;font-weight:700;color:{L["ink"]};margin:0 0 10px">{t}{s_}</div>'
def h3(t): return f'<div style="font:600 14px {F_H};color:{L["ink2"]};margin:14px 0 6px">{e(t)}</div>'
def card(inner): return f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {L["line"]};border-radius:12px;margin-top:18px"><tr><td style="padding:14px 14px;font-family:{F_B};font-size:{BODY_FS};color:{L["ink"]};line-height:1.55">{inner}</td></tr></table>'
class Raw(str):
    """A header string that is already HTML and must not be escaped."""
def th(t, w=None): return f'<th align="left"{f" width={chr(34)}{w}{chr(34)}" if w else ""} style="font:600 10.5px {F_H};text-transform:uppercase;color:{L["ink3"]};padding:8px 8px;border-bottom:2px solid {L["lineS"]}">{t if isinstance(t, Raw) else e(t)}</th>'
def th_axis(name, labels):
    """Two lines: the column name, then its axis.

    The axis is laid out as three equal cells rather than a run of text, so the
    center label sits over the TRACK'S CENTRE. A plain text run ("−1% · 0 · +1%")
    flows from the left edge and puts the zero wherever the characters happen to
    land, which misreads the chart beneath it — the label must agree with the
    geometry it describes. The email cannot position elements, but equal-width
    table cells with align= give the same result, and both survive the sanitizer.
    """
    lo, mid, hi = labels
    cell = f"font:400 10px {F_M};text-transform:none;letter-spacing:0;color:{L['ink3']};padding:0"
    return Raw(
        f'{e(name)}'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:1px">'
        f'<tr><td width="33%" align="left" style="{cell}">{e(lo)}</td>'
        f'<td width="34%" align="center" style="{cell}">{e(mid)}</td>'
        f'<td width="33%" align="right" style="{cell}">{e(hi)}</td></tr></table>')


def td(t, mono=False, border_left=None):
    # font-size / line-height / word-break are inherited from the table
    st = f'padding:8px 8px;border-bottom:1px solid {L["line"]};'
    if mono: st += f"font-family:{F_M};"
    # a severity stripe, the one thing a cell borrows from the action bar
    if border_left: st += f"border-left:6px solid {border_left};"
    return f'<td valign="top" style="{st}">{t}</td>'
def tbl(headers, rows, widths=None):
    """`widths` pins the column proportions with width= attributes (which survive
    the sanitizer). Without them a cell holding a 100%-wide bar table starves the
    text columns down to one character per line."""
    ws = widths or [None] * len(headers)
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {L["line"]};font-size:14px;line-height:1.45;word-break:break-word"><tr>' + "".join(th(h, w) for h, w in zip(headers, ws)) + "</tr>" + "".join("<tr>" + "".join(r) + "</tr>" for r in rows) + "</table>"
def sp(t, color, bold=True): return f'<span style="color:{color};{"font-weight:600;" if bold else ""}">{t}</span>'
def lead(t): return sp(e(t), L["accent"])
def muted(t): return f'<span style="color:{L["ink3"]}">{t}</span>'
def small(t): return f'<span style="color:{L["ink3"]};font-size:12.5px">{t}</span>'
def em_lead_inner(text):
    """Lead-in formatted for the EMAIL, without a list wrapper."""
    a, sep, b = lead_split(text)
    if a:
        return f'{lead(a)}{":" if sep.strip() == ":" else " —"} {e(b)}'
    return e(text)


def em_li(text):
    """A bullet, or nothing at all - see li_lead."""
    return f'<li style="margin:9px 0">{em_lead_inner(text)}</li>' if str(text).strip() else ""
def ul(items): return '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(f'<li style="margin:9px 0">{i}</li>' for i in items) + "</ul>"
def _seg(w, col): return f'<span style="display:inline-block;width:0;height:0;border-left:{w}px solid {col};border-top:5px solid {col};border-bottom:5px solid {col}"></span>'
# FLUID DIVERGING BAR for the email. Percentage table cells, so the track fills
# whatever width the column has at any screen size instead of sitting at a fixed
# 80px stub; the fill is drawn with border-top/border-bottom because the send
# path strips every `background`. Center line = 0, left = negative, right =
# positive. Both `width=` attributes and inline width survive the sanitizer.
def _em_cell(pct, style):
    # font-size / line-height are inherited from the track table
    return f'<td width="{pct:.1f}%" style="{style}"></td>'


def _em_bar(frac, col, right):
    """Fluid diverging bar for the email: ONE table row, four cells at most.

    Percentage widths, so the track fills whatever width the column has; the
    fill is drawn with border-top/border-bottom because backgrounds never
    survive the sanitizer; the center line is a border on the cell that ends at
    zero. An earlier version nested a table inside each half, which read the
    same and cost twice the bytes - and the email has a hard 85 KB budget, so
    markup weight is a feature constraint, not a detail.
    """
    p = max(frac * 100, 3.0) / 2          # percent of the FULL track
    fill = f"border-top:5px solid {col};border-bottom:5px solid {col}"
    line = f'border-bottom:1px solid {L["line"]}'
    center = f';border-right:1px solid {L["lineS"]}'
    if right is None:
        # No direction: straddle zero so the bar states magnitude and nothing
        # more. Drawing it on either side would assert a direction the data
        # does not carry.
        h = p / 2
        cells = (_em_cell(50 - h, line) + _em_cell(h, fill + center)
                 + _em_cell(h, fill) + _em_cell(50 - h, line))
    elif right:
        cells = (_em_cell(50, line + center)
                 + _em_cell(p, fill) + _em_cell(50 - p, line))
    else:
        cells = (_em_cell(50 - p, line) + _em_cell(p, fill + center)
                 + _em_cell(50, line))
    return ('<table width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed;'
            'border-collapse:collapse;margin-top:4px;font-size:0;line-height:0">'
            f'<tr>{cells}</tr></table>')


def em_bar_div(pct, ax):
    return _em_bar(min(abs(pct) / ax[1], 1.0), L["pos"] if pct >= 0 else L["neg"], pct >= 0)
def em_bar_money(amt, dirw, sign="", axis=None):
    side, cls = money_side(dirw, sign)
    col = {"pos": L["pos"], "neg": L["neg"], "neu": L["ink3"]}[cls]
    return _em_bar(_money_frac(amt, axis), col,
                   None if side == "center" else side == "right")
def cap(t): return f'<div style="font-size:12px;color:{L["ink3"]};padding:6px 2px">{e(t)}</div>'
def stripe_row(color, title_html, det_html):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {L["line"]};border-left:6px solid {color};margin-top:6px"><tr><td style="padding:10px 12px"><div style="font:600 15px {F_H};color:{L["ink"]}">{title_html}</div><div style="font-size:14px;color:{L["ink2"]};margin-top:2px">{det_html}</div></td></tr></table>'

def layout_note():
    """Names the standalone file the run actually wrote.

    It was a frozen literal, so every brief for weeks told the reader to open a
    file named for a date long past.
    """
    return ("One fluid layout for phone and desktop — the mail path strips stylesheets. "
            f"The standalone file <b>morning-brief-{e(FILE_STAMP)}.html</b>, with full tables, "
            "dark mode and the mailpiece scans, is in the Claude session.")

# Gmail clips a message past ~102 KB and its sanitizer inflates the HTML ~12%,
# so the body is budgeted at 85 KB. When the brief outgrows that, the EMAIL sheds
# its least actionable cards in this order and says so; the standalone file
# always carries everything. Shedding in a fixed order beats a human guessing
# which section to cut at 6am, and beats Gmail truncating mid-table.
# Override with BRIEF_EMAIL_BUDGET_BYTES. Raising it past ~85 KB does not break
# anything: Gmail CLIPS rather than rejects, showing "[Message clipped] View
# entire message". That is a real option - a clip link beats seven missing
# cards - but the clip point is ~102 KB of DELIVERED bytes and the send path
# inflates the source ~12%, so 85 KB source lands near 95 KB delivered and is
# already close to it.
EMAIL_BUDGET_BYTES = int(os.environ.get("BRIEF_EMAIL_BUDGET_BYTES", 85 * 1024))
SHED_ORDER = ("Retail sales", "Research & publications", "AI & programming",
              "Fed & labor market", "Large caps", "Cryptocurrency", "US market")

# HOW IT REACHES THE INBOX. A Routine holds an email CONNECTOR, not credentials,
# and a connector's send tool takes the body only as an inline string - there is
# no way to hand it a file. So the body must pass through the run's context and
# come back out as a tool argument. That works, and has for every brief sent so
# far, but Gmail strips <style> (verified below), so every rule here is an inline
# style= attribute and the body runs ~85 KB. One run tried to read it in a single
# call, hit the tool's read cap partway through, and gave up - substituting a
# placeholder and then breaking the one-send rule trying to correct itself.
#
# So the renderer splits the body itself. `render` writes email.partNN.html
# alongside email.html; each part is under SEND_PART_BYTES and breaks only at a
# tag boundary, so concatenating them in order reproduces email.html byte for
# byte. The run reads parts, never the whole file, and never has to invent a
# chunking scheme at 6am.
SEND_PART_BYTES = 12 * 1024


def split_for_send(html, limit=None):
    """Split the email body into parts that concatenate back exactly.

    Breaks only between tags, so every part starts with "<" and ends with ">"
    and a truncated part is obvious on sight. `"".join(parts) == html` always -
    that is the property the send depends on, and test_email_brief asserts it.

    >>> "".join(split_for_send("<a>xx</a><b>yy</b>", limit=8)) == "<a>xx</a><b>yy</b>"
    True
    """
    limit = limit or SEND_PART_BYTES
    parts, start = [], 0
    while start < len(html):
        if len(html) - start <= limit:
            parts.append(html[start:])
            break
        cut = html.rfind("><", start, start + limit)
        # No tag boundary in range (one enormous tag): take the whole run to the
        # next one rather than splitting inside an attribute.
        cut = cut + 1 if cut > start else (html.find("><", start + limit) + 1 or len(html))
        parts.append(html[start:cut])
        start = cut
    return parts


# What Gmail hides. It clips past ~102 KB delivered, and EMAIL_BUDGET_BYTES is
# that point in source bytes with margin for the send path's ~12% inflation -
# the same threshold the "Gmail will clip" note uses, so the two can never
# disagree. A section whose markup ends past it sits wholly or partly behind
# "[Message clipped]". The renderer knows every section's offset and can say
# which; a run cannot, because the message in the mailbox is complete and only
# the view is clipped. Conservative on purpose: carrying a section the reader
# could in fact see costs an evening a few lines, missing one they could not
# costs the section.

# Which payload keys make up each section, so an evening run can carry a
# section out of the morning's payload whole. Derived axes (MKT_24 ...) are
# recomputed from these on render, so they are not listed.
SECTION_KEYS = {
    "High priority": ("HIPRI",),
    "Relevant job posts": ("JOBS_TOP", "JOBS_STATUS", "JOBS_OTHER"),
    "Deposits & finances": ("FIN_SUMMARY", "FIN_MOVES", "FIN_NOTES", "FIN_INTERNAL"),
    "Upcoming travel": ("FLIGHTS", "TRAVEL"),
    "VoIP voicemails & texts": ("VOIP",),
    "USPS Informed Delivery": ("USPS", "USPS_SCANS"),
    "Package tracking": ("PKG", "PKG_NOTE"),
    "US market": ("MKT_ROWS", "FUNDS", "MKT_BULLETS"),
    "Large caps": ("STOCKS",),
    "Fed & labor market": ("MACRO_ROWS", "JOBS_SECTORS", "MACRO_NOTE"),
    "Cryptocurrency": ("CRYPTO_ROWS", "CRYPTO_NOTE", "CRYPTO_BULLETS"),
    "AI & programming": ("AI_ITEMS",),
    "Research & publications": ("JOURNALS", "JOURNAL_ITEMS"),
    "Retail sales": ("RETAIL",),
}

# Filled by every email render: what this email left out, and why.
LAST_EMAIL_REPORT = {"shed": [], "clipped": [], "bytes": 0}

_EM_H2 = _re.compile(r'<div style="font-family:[^"]*font-size:19px;font-weight:700;[^"]*">(.*?)</div>', _re.S)
_EM_SUB = _re.compile(r'<span style="[^"]*font-weight:400;font-size:13px;[^"]*">.*?</span>', _re.S)


def _title_of(markup):
    """The section name a heading renders, without its number or subtitle.

    >>> _title_of('<span style="color:teal;font-weight:600;">3.</span> Deposits &amp; finances')
    'Deposits & finances'
    """
    t = _re.sub(r"<[^>]+>", "", _EM_SUB.sub("", markup))
    return _re.sub(r"^\s*\d+\.\s*", "", H.unescape(t)).strip()


def carried_caption(name):
    """What a carried section says about where its content came from."""
    c = CARRIED or {}
    if name not in (c.get("sections") or []):
        return ""
    when = c.get("from") or "this morning"
    if name in (c.get("merged") or []):
        return f"Includes this morning's items ({when}) plus what arrived since."
    return f"Carried from this morning's brief ({when}) \u2014 not refreshed this evening."


def _caption_carried_file(html):
    if not (CARRIED or {}).get("sections"):
        return html

    # Standing sections are <section><h2>, research cards are <div class="card">
    # <h2>, and Large caps is an <h3> inside the US market card - so match any
    # h2/h3 whose title is a known section rather than one wrapper shape.
    def add(m):
        cap = carried_caption(_title_of(_re.sub(r'<span class="sub">.*?</span>', "", m.group(2), flags=_re.S)))
        return m.group(0) + (f'<div class="cap">{e(cap)}</div>' if cap else "")
    return _re.sub(r"<(h2|h3)>(.*?)</\1>", add, html, flags=_re.S)


FULL_LINK_NOTE = (f"Private: opens only when signed in to claude.ai. "
                  f"Deleted after {RETENTION_DAYS} days.")


def full_link_html():
    """The full-page link, for the masthead.

    It sits in the header, not at the end: Gmail clips a long message and hides
    its tail behind "View entire message", and the link is the route to
    whatever the reader cannot see - so it must come before any clip point.
    It follows the layout note, which already draws the rule above it, and sits
    a step below body size: it is a route to the brief, not part of it.
    """
    if not FULL_URL:
        return ""
    return (f'<div style="margin-top:6px;font-family:{F_B};font-size:{LINK_FS};color:{L["ink"]}">'
            f'{sp("Full brief, never truncated:", L["ink"])} '
            f'<a href="{url(FULL_URL)}" style="color:{L["accent"]};font-weight:600">{e(short_url(FULL_URL))}</a>'
            f'<div style="font-size:11.5px;color:{L["ink3"]};margin-top:2px">{e(FULL_LINK_NOTE)}</div>'
            '</div>')


def scan_anchor(n):
    """The id of the n-th mailpiece figure on the full page (1-based)."""
    return f"usps-scan-{n}"


def scan_url(n):
    """The full page's address, pointed at the n-th scan.

    Any fragment already on the address is replaced, not appended to: a second
    "#" would make the browser look for an id that does not exist.
    """
    return FULL_URL.split("#", 1)[0] + "#" + scan_anchor(n)


def scan_attached(n):
    """Is the n-th scan attached to this send? Unknown counts count as attached."""
    return ATTACHED_SCANS is None or n <= ATTACHED_SCANS


def scan_links_html():
    """Where the email's reader finds each mailpiece scan.

    The email cannot show the scan itself: the Gmail send path strips every
    <img> - data: URI, cid: inline attachment and remote URL alike (verified by
    reading a sent test message back in RAW form). So each scan is named,
    linked to its figure on the private full page when there is one, and
    pointed at the JPG attached to the end of the email when it is attached.
    """
    if not USPS_SCANS:
        return ""
    rows = []
    for n, _ in enumerate(USPS_SCANS, 1):
        parts = []
        if FULL_URL:
            parts.append(f' <a href="{url(scan_url(n))}" style="color:{L["accent"]};font-weight:600">'
                         'view on claude.ai</a> (sign-in required)')
        parts.append(" attached at the end of this email" if scan_attached(n)
                     else " not attached \u2014 it did not fit in this email")
        joined = " \u00b7".join(parts)   # a backslash may not sit inside an f-string's braces before 3.12
        rows.append(f'<div>{sp(f"Mailpiece scan {n}:", L["ink"])}{joined}</div>')
    return f'<div style="margin-top:8px;font-size:{BODY_FS};color:{L["ink2"]}">' + "".join(rows) + '</div>'


def _assemble_email(parts, droppable, budget=None):
    """Join the email, shedding whole cards until it fits the send budget.

    `droppable` maps a card name to its index in `parts`. Cards are shed in
    SHED_ORDER - least actionable first - and the reader is told which ones and
    where to find them. Nothing is shortened or summarized: a half-rendered
    table is worse than an absent one.
    """
    dropped = []
    # Say which limit actually bit. When scans ride along they take their room
    # out of the body, and blaming Gmail for that sends the reader looking in
    # the wrong place - and hides the lever that would have kept the cards.
    why = ("The whole message had to fit one send, and the attached scans took "
           "part of the room." if budget and budget < EMAIL_BUDGET_BYTES
           else "Gmail clips a message past ~102 KB.")
    # None means DO NOT SHED. The brief outranks the Gmail-clip threshold: a
    # clip is a link the reader can follow, a shed card is gone. The caller
    # decides, because only the caller knows the whole send call.
    budget = budget if budget else float("inf")
    where = ("in the full brief linked at the top" if FULL_URL
             else "in the attached brief file")

    def trim_note(names):
        """The note that tells the reader which cards went, and where they are."""
        if not names:
            return ""
        return ('<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid '
                f'{L["line"]};border-left:4px solid {L["warn"]};border-radius:12px;margin-top:18px">'
                f'<tr><td style="padding:12px 14px;font-family:{F_B};font-size:{BODY_FS};color:{L["ink"]}">'
                f'{sp("Trimmed to fit the inbox", L["warn"])} — '
                f'{e(", ".join(names))} '
                f'{"is" if len(names) == 1 else "are"} {where} but not in this '
                f'email. {e(why)} Nothing was shortened; whole cards were '
                'dropped, least actionable first.</td></tr></table>')

    # The note is part of the email, so its own bytes are counted while shedding.
    # They used not to be, and a brief that shed cards could still land OVER the
    # budget by the size of the note explaining the shedding.
    def size(names):
        return len(("\n".join(parts)).encode("utf-8")) + len(trim_note(names).encode("utf-8"))

    while size(dropped) > budget:
        nxt = next((n for n in SHED_ORDER if n in droppable and parts[droppable[n]]), None)
        if nxt is None:
            break                      # nothing left that may be shed
        parts[droppable[nxt]] = ""
        dropped.append(nxt)
    if (CARRIED or {}).get("sections"):
        for i, part in enumerate(parts):
            m = _EM_H2.search(part)
            cap = carried_caption(_title_of(m.group(1))) if m else ""
            if cap:
                parts[i] = (part[:m.end()] + f'<div style="font-size:12.5px;color:{L["ink3"]};'
                            f'margin:-6px 0 10px">{e(cap)}</div>' + part[m.end():])
    if dropped:
        parts.insert(-1, trim_note(dropped))
    # Record what the reader cannot see: shed cards are gone, clipped sections
    # are behind Gmail's "View entire message". An evening run reads this back
    # out of the sent text copy to know what to carry.
    clipped, pos = [], 0
    for part in parts:
        end = pos + len(part.encode("utf-8"))
        m = _EM_H2.search(part)
        name = _title_of(m.group(1)) if m else ""
        if name in SECTION_KEYS and end > EMAIL_BUDGET_BYTES:
            clipped.append(name)
        pos = end + 1
    LAST_EMAIL_REPORT.clear()
    LAST_EMAIL_REPORT.update(shed=list(dropped), clipped=clipped)
    html = "\n".join(parts)
    LAST_EMAIL_REPORT["bytes"] = len(html.encode("utf-8"))
    return html


def email_html(budget=None):
    droppable = {}

    def mark(name):
        """Record that the card just appended may be shed to fit the budget."""
        droppable[name] = len(o) - 1

    o = [f'<div style="padding:12px 6px;font-family:{F_B};color:{L["ink"]}"><table width="100%" cellpadding="0" cellspacing="0" style="max-width:860px;margin:0 auto"><tr><td>']
    stamps = "".join(f'<div style="margin-top:8px">{lbl(k)}<div style="font-family:{F_M};font-size:14px">{e(v)}</div></div>' for k, v in [("Timezone", MAST["tz"]), ("Scheduled slot", MAST["slot"]), ("Window covered", MAST["window"]), ("Run stamp", MAST["run"])])
    o.append(f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {L["line"]};border-radius:14px"><tr><td style="padding:18px 16px">'
             f'<div style="font-family:{F_H};font-size:28px;font-weight:700;color:{L["ink"]}">{e(MAST["title"])}</div>'
             f'<div style="font-size:16px;font-weight:600;color:{L["ink2"]};margin-top:2px">{e(MAST["dateline"])}</div>{stamps}'
             f'<div style="font-size:13px;color:{L["ink3"]};margin-top:10px">{e(MAST["note"])}</div>'
             f'<div style="font-size:12.5px;color:{L["ink3"]};margin-top:6px;border-top:1px solid {L["line"]};padding-top:6px">{layout_note()}</div>{full_link_html()}'
             f'<div style="font-size:13px;color:{L["warn"]};font-weight:600;margin-top:6px">{e(MAST["revised"])}</div></td></tr></table>')
    sevcol = {"warn": L["warn"], "neg": L["neg"], "info": L["accent"], "ok": L["pos"]}
    tagmap = {"warn": "Check", "neg": "Urgent", "info": "Note", "ok": "Clear"}
    rows = "".join(stripe_row(sevcol[sev], f'<span style="font-size:10.5px;text-transform:uppercase;padding:1px 6px;border:1px solid {sevcol[sev]};color:{sevcol[sev]};margin-right:8px">{tagmap[sev]}</span>{e(t)}', e(action_detail(t, d))) for sev, t, d in ACTIONS)
    if not ACTIONS:
        rows = f'<div style="color:{L["ink3"]};font-style:italic">{NOTHING_TODAY}</div>'
    o.append('<div style="margin-top:18px">' + h2("Needs you today", actions_sub()) + rows + '</div>')
    # 4 hipri
    num = SectionNumber()
    inner = h2(f'{sp(f"{num()}.", L["accent"])} High priority', "ranked by severity · act on these first")
    rws = []
    for sev, t_, items in HIPRI:
        # No nowrap here: the sanitizer rule forbids it, and sharing a 40%
        # column with the title gives the chip room to sit on one line anyway.
        chip = (f'<span style="font:600 10px {F_H};text-transform:uppercase;border:1px solid '
                f'{sevcol[sev]};color:{sevcol[sev]};padding:1px 5px;border-radius:4px">'
                f'{SEV_WORD.get(sev, sev.upper())}</span>')
        # the same stripe the action bar uses, so one item reads as one item
        rws.append([td(f"{chip} {sp(e(t_), sevcol[sev])}", border_left=sevcol[sev]),
                    td("<br>".join(em_lead_inner(i) for i in items))])
    inner += tbl(["What needs attention", "Detail"], rws, ["40%", "60%"]) if rws else f'<div style="color:{L["ink3"]};font-style:italic">{e(nothing_new())}</div>'
    o.append(card(inner))
    # 1 jobs — 3 columns
    inner = h2(f'{sp(f"{num()}.", L["accent"])} Relevant job posts', JOBS_RANKED_NOTE)
    if not (JOBS_STATUS or JOBS_TOP or JOBS_OTHER):
        inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(nothing_new())}</div>'
    if JOBS_STATUS:
        inner += h3("Application status") + ul([f'{lead(t)} {small("— " + e(m))}<br>{e(d)}' for t, m, d in JOBS_STATUS])
    rws = []
    for r, c, comp, loc, src, tier, link in JOBS_TOP:
        fit, fcls = job_fit(tier); lcls, _ = loc_tier(loc); fitc = L["pos"] if fcls == "pos" else L["accent"]
        badge = (f' <span style="font:600 10px {F_H};text-transform:uppercase;border:1px solid {fitc};color:{fitc};padding:0 5px;border-radius:4px;white-space:nowrap">{fit}</span>' if fit else "")
        compc = sp(e(comp), L["pos"]) if comp != "not stated" else muted(e(comp))
        locc = sp(e(loc), L["accent"]) if lcls else e(loc)
        rws.append([td(f'<b>{e(r)}</b>{badge}<br>{small(e(c))}'), td(f'<span style="font-family:{F_M}">{compc}</span><br>{locc}'), td(f'<a href="{url(link)}" style="color:{L["accent"]};font-weight:600">open</a><br>{small(e(src))}')])
    if JOBS_TOP:
        inner += h3("Ranked leads") + tbl(["Role · company", "Comp · location", "Link · source"], rws)
        inner += f'<div style="font-size:12.5px;color:{L["ink3"]};margin-top:8px">{sp("Green",L["pos"])} = comp stated · {sp("Teal",L["accent"])} = {JOBS_TEAL_LABEL} · {sp("Amber",L["warn"])} = deadline stated (none today) · Grey = not stated<br>{e(JOBS_LEGEND_FIT)}</div>'
    if JOBS_OTHER:
        inner += h3("Also seen (lower fit)") + ul([f'{e(r)} — {e(c)} · ' + (sp(e(loc),L["accent"]) if loc_tier(loc)[0] else muted(e(loc))) + f' · <a href="{url(link)}" style="color:{L["accent"]}">link</a>' for r, c, loc, link in JOBS_OTHER])
    inner += "".join(f'<p style="font-size:13px;color:{L["ink3"]}">{e(x)}</p>' for x in (ALIGNERR, JOBS_SKIPPED) if x)
    o.append(card(inner))
    # 2 finances
    inner = h2(f'{sp(f"{num()}.", L["accent"])} Deposits &amp; finances')
    if not (FIN_SUMMARY or FIN_MOVES or FIN_NOTES):
        inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(nothing_new())}</div>'
    for l, v, d in FIN_SUMMARY:
        tone = tile_tone(l)
        col = {"pos": L["pos"], "neg": L["neg"], "neu": L["ink"]}[tone]
        edge = {"pos": L["pos"], "neg": L["neg"], "neu": L["accent"]}[tone]
        amount, cur = tile_amount(v)
        inner += (f'<div style="border:1px solid {L["line"]};border-left:4px solid {edge};'
                  f'padding:8px 12px;margin:6px 0">{lbl(l)}'
                  f'<div style="font-family:{F_M};font-size:20px;font-weight:700;color:{col}">{e(amount)}'
                  + (f' <span style="font-size:13px;font-weight:400;color:{L["ink3"]}">{e(cur)}</span>' if cur else "")
                  + f'</div>{small(e(d))}</div>')
    rws = []
    for when, payee, det, amt, cur, usd, dirw, sign in moves_in_order():
        _, _mcls = money_side(dirw, sign)
        col = {"pos": L["pos"], "neg": L["neg"], "neu": L["ink2"]}[_mcls]
        amt_s = money_amount(amt, cur, usd, sign)
        rws.append([td(f'<span style="font-family:{F_M}">{e(when)}</span><br>{e(payee)}'), td(detail_html_email(det)), td(f'{sp(e(sign+" "+dirw), col)} {sp(amt_s, col)}<br>{em_bar_money(usd, dirw, sign)}')])
    if FIN_MOVES:
        inner += h3("Money movements (outside → you / you → outside)") + tbl(["When · payee", "Detail", th_axis("Direction · amount", money_labels(FIN_AXIS))], rws, ["30%", "32%", "38%"]) + cap(f"Bar axis, in USD: {money_axis_note()}. Amounts shown in their original currency; bars plotted from the USD equivalent. In = green right of 0, out / past due = red left of 0, internal = grey (magnitude only) — sign and word state it too.")
    if ai_spend_rows():
        rws = []
        for row in ai_spend_rows():
            service, total, note = row[0], row[1], row[-1]
            new = ai_new(row)
            rws.append([td(f'{lead(service)}<br>{small(e(note))}'),
                        td(sp(e(usd_str(total)), L["ink"]), mono=True),
                        td((sp(e(usd_str(new)), L["neg"]) + em_bar_money(abs(new), "Out", axis=AI_AXIS))
                           if new else muted("nothing new"), mono=True)])
        inner += h3("AI services — billed year to date") + tbl(
            ["Service · share AI spend (YTD)", f'Billed {AI_SPEND["year"]}',
             th_axis("New this window", money_labels(AI_AXIS))],
            rws, ["40%", "22%", "38%"]) + cap(ai_spend_caption())
    if FIN_INTERNAL:
        inner += h3("Transfers between your own accounts") + f'<div style="color:{L["ink3"]};font-style:italic">{e(FIN_INTERNAL)}</div>'
    if FIN_NOTES:
        inner += h3("Bills, statements & notices") + '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(n) for n in FIN_NOTES) + "</ul>"
    o.append(card(inner))
    # 3 voip
    # 4 upcoming flights — persists until the trip date passes
    # Omitted when nothing is booked, like package tracking.
    if FLIGHTS["legs"] or TRAVEL:
        inner = h2(f'{sp(f"{num()}.", L["accent"])} Upcoming travel', TRAVEL_SUB)
    if FLIGHTS["legs"]:
        inner += h3("Flights")
        inner += f'<p>{lead(FLIGHTS["airline"] + ", confirmation " + FLIGHTS["conf"])} — {e(FLIGHTS["pax"])}</p>'
        inner += f'<p style="font-size:13px;color:{L["ink3"]}">{e(FLIGHTS["booked"])}</p>'
        show_stats = any(g.get("stats") for g in FLIGHTS["legs"])
        rws = []
        for g in FLIGHTS["legs"]:
            route = (f'{e(g["frm"])} <span style="font-family:{F_M}">{e(g["dep"])}</span>'
                     f'<br>→ {e(g["to"])} <span style="font-family:{F_M}">{e(g["arr"])}</span>')
            for line in terminal_lines(g):
                route += f'<br>{small(e(line))}'
            conf = (f'<span style="font-family:{F_M}">{e(leg_conf(g))}</span>' if leg_conf(g)
                    else muted("not stated"))
            # The email is capped at three columns so a phone can read it, so
            # the carrier rides above the code rather than beside it.
            if leg_airline(g):
                conf = e(leg_airline(g)) + "<br>" + conf
            if show_stats:
                conf += f'<br>{small(e(g.get("stats") or "not available"))}'
            rws.append([td(f'{e(g["date"])}<br><a href="{url(g["fa"])}" style="color:{L["accent"]};font-family:{F_M};font-weight:600">{e(g["flight"])}</a>'),
                        td(route), td(conf)])
        show_airline = any(leg_airline(g) for g in FLIGHTS["legs"])
        inner += tbl(["Date · flight", "Route (airport local times)",
                      ("Airline · confirmation" if show_airline else "Confirmation")
                      + (" · on-time" if show_stats else "")],
                     rws, ["26%", "44%", "30%"])
        inner += cap(FLIGHTS["note"])
    if TRAVEL:
        inner += h3("Stays & other bookings")
        rws = []
        for kind, what, when, where, conf, link, *rest in TRAVEL:
            source = booking_source(what, rest[0] if rest else "")
            dates, times = booking_split(when)
            place, place_detail = booking_split(where)
            name = (f'<a href="{url(link)}" style="color:{L["accent"]};font-weight:600">{e(what)}</a>'
                    if link.strip() else lead(what))
            # The date is the column a reader scans, so it is set in the body
            # face: monospace is wider and wrapped three deep at phone width.
            rws.append([
                td(f'<b>{e(dates)}</b>' + (f'<br>{small(e(times))}' if times else "")),
                td(f'{small(e(kind))}<br>{name}'
                   + (f'<br>{small(e(place))}' if place else "")
                   + (f'<br>{small(e(place_detail))}' if place_detail else "")),
                td((f'<span style="font-family:{F_M}">{e(conf)}</span>' if conf.strip() else muted("not stated"))
                   + (f'<br>{small(e(source))}' if source else ""))])
        inner += tbl(["Dates", "Booking", "Confirmation"], rws, ["34%", "44%", "22%"])
        inner += cap(TRAVEL_NOTE)
    if FLIGHTS["legs"] or TRAVEL:
        o.append(card(inner))
    inner = h2(f'{sp(f"{num()}.", L["accent"])} VoIP voicemails &amp; texts', "searched by the configured provider senders + Google Voice, Twilio, OpenPhone, Grasshopper, RingCentral, Dialpad")
    if voip_empty():
        inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(nothing_new())}</div>'
    elif VOIP["headline"].strip():
        inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(VOIP["headline"])}</div>'
    if VOIP["messages"]:
        rws = [[td(f'<span style="font-family:{F_M}">{e(w)}</span><br>{e(frm)}'),
                td(f'<span style="font-family:{F_M}">{e(to)}</span><br>{small(e(kind))}'),
                td(e(text))] for w, frm, to, kind, text in VOIP["messages"]]
        inner += tbl(["When · from", "To · type", "Message"], rws, ["30%", "24%", "46%"])
    if voip_tail():
        inner += '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(n) for n in voip_tail()) + "</ul>"
    o.append(card(inner))
    # 5 USPS
    inner = h2(f'{sp(f"{num()}.", L["accent"])} USPS Informed Delivery', "mail addressed to the intended recipient only; everyone else counted, never named")
    if usps_empty():
        inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(nothing_new())}</div>'
    elif USPS["headline"].strip():
        inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(USPS["headline"])}</div>'
    rws = [[td(f'<span style="font-family:{F_M}">{e(d_)}</span><br>{e(s_)}'), td(f'<span style="font-family:{F_M}">{e(a_)}</span>'), td(e(ty))] for d_, s_, a_, ty in USPS["pieces"]]
    if rws:
        inner += tbl(["Date · sender", "Addressee (as printed)", "Type / notes"], rws)
    inner += scan_links_html()
    if USPS["pieces"] and not USPS_SCANS:
        inner += f'<div style="color:{L["warn"]};font-style:italic">{e(SCAN_MISSING)}</div>'
    counts = em_li(USPS["counts"])
    inner += ('<ul style="margin:8px 0 0;padding-left:20px">' + counts + '</ul>' if counts else "")
    if USPS["note"].strip():
        inner += f'<p style="font-size:13px;color:{L["ink3"]}">{e(USPS["note"])}</p>'
    o.append(card(inner))
    # package tracking — omitted when the window carries no shipments; shipments
    # stay until the carrier reports delivery, so nothing in flight is dropped
    if PKG:
        inner = h2(f'{sp(f"{num()}.", L["accent"])} Package tracking', "FedEx · UPS · USPS · DHL · merchant emails; kept until delivered")
        rws = [[td(f'<b>{e(car)}</b><br>{small("ETA: " + e(eta))}'), td(f'<span style="font-family:{F_M};word-break:break-all">{e(trk)}</span>'), td(f'{e(item)}<br>{small("To: " + e(rcpt) + " · " + e(st))}')] for car, trk, item, rcpt, st, eta in PKG]
        inner += tbl(["Carrier · ETA", "Tracking", "Item · status"], rws) + f'<p style="font-size:13px;color:{L["ink3"]}">{e(PKG_NOTE)}</p>'
        o.append(card(inner))
    # Research cards are conditional: a card only when it has something to show,
    # and within it a table only when that table has rows. A card that is not
    # appended is not marked either, so the shed order never names a card that
    # was never emitted.
    if MKT_ROWS or FUNDS or MKT_BULLETS:
        inner = h2("US market")
        if MKT_ROWS:
            rws = []
            stamp = shared_asof([r[8:] for r in MKT_ROWS])
            for n, c, p1, v1, p7, v7, py, vy, *asof in MKT_ROWS:
                ky = L["pos"] if vy >= 0 else L["neg"]
                rws.append([td(f'{lead(n)}<br>{quote_cell_email(c, v1, [] if stamp else asof)}<br>{sp(f"YTD {pct_str(vy)} {arrow(vy)}", ky)}', mono=True),
                            td(f'<div style="text-align:center">{sp(f"{e(p1)} pts · {pct_str(v1)} {arrow(v1)}", L["pos"] if v1 >= 0 else L["neg"])}</div>{em_bar_div(v1, MKT_24)}', mono=True),
                            td(f'<div style="text-align:center">{sp(f"{e(p7)} pts · {pct_str(v7)} {arrow(v7)}", L["pos"] if v7 >= 0 else L["neg"])}</div>{em_bar_div(v7, MKT_7D)}', mono=True)])
            inner += tbl([f'Index · {quote_head_text("close", stamp)} · YTD', th_axis("1D", pct_labels(MKT_24)), th_axis("1W", pct_labels(MKT_7D))], rws, ["30%", "35%", "35%"]) + cap(f"1D = close → close vs the prior session; 1W = trailing 5 sessions; YTD = since the previous year-end, shown as a figure because the email is capped at three columns. {axis_note(MKT_24, '1D axis')}; {axis_note(MKT_7D, '1W axis')}.")
        if FUNDS:
            rws = []
            stamp = shared_asof([r[9] for r in FUNDS])
            for tk, nm, nav, a1, v1, a7, v7, ay, vy, asof, note in FUNDS:
                ky = L["pos"] if vy >= 0 else L["neg"]
                rws.append([td(f'{lead(tk)}<br>{quote_cell_email(nav, v1, [] if stamp else asof)}<br>{sp(f"YTD {pct_str(vy)} {arrow(vy)}", ky)}', mono=True),
                            td(f'<div style="text-align:center">{sp(f"{e(a1)} · {pct_str(v1)} {arrow(v1)}", L["pos"] if v1 >= 0 else L["neg"])}</div>{em_bar_div(v1, FUND_1D)}', mono=True),
                            td(f'<div style="text-align:center">{sp(f"{e(a7)} · {pct_str(v7)} {arrow(v7)}", L["pos"] if v7 >= 0 else L["neg"])}</div>{em_bar_div(v7, FUND_1W)}', mono=True)])
            inner += h3("Vanguard funds") + tbl([f'Fund · {quote_head_text("NAV", stamp)} · YTD', th_axis("1D", pct_labels(FUND_1D)), th_axis("1W", pct_labels(FUND_1W))], rws, ["30%", "35%", "35%"]) + cap("Change from the prior published NAV (1D), over one trading week (1W), and since the previous year-end (YTD). " + " ".join(f"{tk}: {note}" for tk, nm, nav, a1, v1, a7, v7, ay, vy, asof, note in FUNDS))
        if MKT_BULLETS:
            inner += '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(b) for b in MKT_BULLETS) + "</ul>"
        o.append(card(inner))
        mark("US market")
    # large caps — its own card; appending to `inner` here re-emitted the whole
    # market card, silently doubling ~25 KB of the email
    if STOCKS:
        inner = h2("Large caps")
        rws = []
        stamp = shared_asof([r[8:] for r in STOCKS])
        for tk, pr, a1, v1, a7, v7, ay, vy, *asof in STOCKS:
            ky = L["pos"] if vy >= 0 else L["neg"]
            rws.append([td(f'{lead(tk)}<br>{quote_cell_email(pr, v1, [] if stamp else asof)}<br>{sp(f"YTD {pct_str(vy)} {arrow(vy)}", ky)}', mono=True),
                        td(f'<div style="text-align:center">{sp(f"{e(a1)} · {pct_str(v1)} {arrow(v1)}", L["pos"] if v1 >= 0 else L["neg"])}</div>{em_bar_div(v1, STK_1D)}', mono=True),
                        td(f'<div style="text-align:center">{sp(f"{e(a7)} · {pct_str(v7)} {arrow(v7)}", L["pos"] if v7 >= 0 else L["neg"])}</div>{em_bar_div(v7, STK_1W)}', mono=True)])
        inner += tbl([f'Ticker · {quote_head_text("price", stamp)} · YTD', th_axis("1D", pct_labels(STK_1D)), th_axis("1W", pct_labels(STK_1W))], rws, ["30%", "35%", "35%"])
        o.append(card(inner))
        mark("Large caps")
    if MACRO_ROWS or JOBS_SECTORS:
        inner = h2("Fed &amp; labor market")
        if MACRO_ROWS:
            inner += tbl(["Indicator", "Latest", "Change · context"],
                         [[td(lead(n)),
                           td(sp(e(v), {"pos": L["pos"], "neg": L["neg"], "neu": L["ink"]}[macro_tone(n, c)]), mono=True),
                           td(f"{e(c)}<br>{small(e(with_year(a)))}")]
                          for n, v, c, a in MACRO_ROWS], ["28%", "22%", "50%"])
        if JOBS_SECTORS:
            inner += h3("Jobs by sector")
            inner += tbl(["Sector", "Payrolls", "Context"],
                         [[td(e(sec)),
                           td(sp(e(ch), L["neg"] if str(ch).lstrip().startswith(("\u2212", "-")) else L["pos"]), mono=True),
                           td(f"{e(ctx)}<br>{small(e(with_year(a)))}")]
                          for sec, ch, ctx, a in JOBS_SECTORS], ["30%", "18%", "52%"])
        inner += cap(MACRO_NOTE)
        o.append(card(inner))
        mark("Fed & labor market")
    if CRYPTO_ROWS or CRYPTO_BULLETS:
        inner = h2("Cryptocurrency")
        if CRYPTO_ROWS:
            rws = []
            stamp = shared_asof([r[8:] for r in CRYPTO_ROWS])
            for n, pr, v1, a1, v7, a7, vy, ay, *asof in CRYPTO_ROWS:
                ky = L["pos"] if vy >= 0 else L["neg"]
                rws.append([td(f'{lead(n)}<br>{quote_cell_email(pr, v1, [] if stamp else asof)}<br>{sp(f"YTD {pct_str(vy)} {arrow(vy)}", ky)}', mono=True),
                            td(f'<div style="text-align:center">{sp(f"{pct_str(v1)} {arrow(v1)} · {e(a1)}", L["pos"] if v1 >= 0 else L["neg"])}</div>{em_bar_div(v1, CRY_24)}', mono=True),
                            td(f'<div style="text-align:center">{sp(f"{pct_str(v7)} {arrow(v7)} · {e(a7)}", L["pos"] if v7 >= 0 else L["neg"])}</div>{em_bar_div(v7, CRY_7D)}', mono=True)])
            inner += tbl([f'Asset · {quote_head_text("price", stamp)} · YTD', th_axis("1D", pct_labels(CRY_24)), th_axis("1W", pct_labels(CRY_7D))], rws, ["30%", "35%", "35%"]) + cap(f"1D = rolling 24 h; 1W = rolling 7 days; YTD = since the previous year-end — crypto trades continuously, so every window runs back from the quote time. {axis_note(CRY_24, '1D axis')}; {axis_note(CRY_7D, '1W axis')}. {CRYPTO_NOTE}")
        if CRYPTO_BULLETS:
            inner += '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(b) for b in CRYPTO_BULLETS) + "</ul>"
        o.append(card(inner))
        mark("Cryptocurrency")
    if AI_ITEMS:
        inner = h2("AI &amp; programming") + tbl(
            ["Item", "What it means", "Source"],
            [[td(lead(t_)), td(e(d)),
              td(f'<a href="{url(l)}" style="color:{L["accent"]};font-weight:600">open</a>')]
             for t_, d, l in AI_ITEMS], ["30%", "56%", "14%"])
        o.append(card(inner))
        mark("AI & programming")
    # No papers -> no card; it used to render "Journals scanned: ;".
    if JOURNAL_ITEMS:
        inner = h2("Research &amp; publications") + tbl(
            ["Journal · date", "Paper", "Takeaway"],
            [[td(f'{lead(j)}<br>{small(e(d))}'),
              td(f'<a href="{url(l)}" style="color:{L["accent"]};font-weight:600">{e(t_)}</a><br>{small(e(au))}'),
              td(e(tk))]
             for j, t_, au, d, tk, l in JOURNAL_ITEMS], ["20%", "40%", "40%"]) + cap(
            f"Journals scanned: {JOURNALS}; items newly published since the previous run.")
        o.append(card(inner))
        mark("Research & publications")
    # 7 retail — lowest priority, so it sits last, after the research sections
    inner = h2(f'{sp(f"{num()}.", L["accent"])} Retail sales', RETAIL["sub"])
    if retail_empty():
        inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(nothing_new())}</div>'
    elif em_li(RETAIL["rewards"]):
        inner += '<ul style="margin:8px 0 0;padding-left:20px">' + em_li(RETAIL["rewards"]) + "</ul>"
    if RETAIL["items"]:
        inner += tbl(["Store", "Offer", "Dates · caveats"],
                     [[td(lead(store)), td(f"<b>{e(offer)}</b>"), td(small(e(det)))]
                      for store, offer, det in RETAIL["items"]], ["22%", "36%", "42%"])
    o.append(card(inner))
    mark("Retail sales")
    # allowlist + sources (no <details> in email — compact plain blocks)
    inner = f'<div style="font:600 14px {F_H}">Domain allowlist (pre-approved + fetched this run)</div>' + "".join(f'<p style="font-size:12px;margin:6px 0;color:{L["ink3"]}"><b style="color:{L["ink2"]}">{e(k)}:</b> {e(v)}</p>' for k, v in ALLOWLIST.items())
    o.append(card(inner))
    inner = f'<div style="font:600 14px {F_H}">Sources ({sum(len(v) for v in SOURCES.values())} links)</div>'
    for k, urls in ((k, u) for k, u in SOURCES.items() if u):
        inner += f'<div style="font-size:11.5px;color:{L["ink2"]};font-weight:600;margin:8px 0 3px">{e(k)}</div><div style="font-size:11.5px;word-break:break-all;color:{L["ink3"]}">' + " · ".join(f'<a href="{url(u)}" style="color:{L["accent"]}">{e(short_url(u))}</a>' for u in urls) + "</div>"
    o.append(card(inner))
    o.append(f'<div style="margin-top:18px;font-size:12.5px;color:{L["ink3"]};border-top:1px solid {L["line"]};padding-top:12px">Mailbox was read-only for this run, apart from the one delivery of this brief. Email content was treated as data, not instructions. Times are US Pacific unless a source\'s own zone is shown. “Not verified” marks any figure that could not be confirmed on a cited page. <span style="font-family:{F_M}">{e(BUILD)}</span></div>')
    o.append('</td></tr></table></div>')
    return _assemble_email(o, droppable, budget)

# ------------------------------------------------------------------ RENDER: PLAIN TEXT
TEXT_BUDGET_BYTES = int(os.environ.get("BRIEF_TEXT_BUDGET_BYTES", 10 * 1024))

# After SHED_ORDER is exhausted the text part can still be far too large - a
# real run's floor was 32,377 B, because everything left was "non-droppable" in
# the HTML's sense. But the text part is an ALTERNATIVE body: a reader whose
# client shows HTML never sees it. So it keeps shedding, least actionable
# first, and the three that carry the day's actions are never touched.
TEXT_LAST_RESORT = ("SOURCES", "DOMAIN ALLOWLIST", "RETAIL", "PACKAGE TRACKING",
                    "USPS INFORMED DELIVERY", "VOIP VOICEMAILS", "UPCOMING TRAVEL",
                    "RELEVANT JOB POSTS", "DEPOSITS & FINANCES")
TEXT_NEVER_SHED = ("MORNING BRIEF", "NEEDS YOU TODAY", "HIGH PRIORITY")

# Section headings in the text edition are bare uppercase lines.
_TEXT_HEADING = _re.compile(r"^(?:\d+\. )?[A-Z][A-Z0-9 &,'()\u2014-]{3,}$", _re.M)


def shed_text(text, budget=None):
    """Drop whole sections from the text edition until it fits `budget`.

    The plain-text part is an alternative body, not the brief - the HTML is -
    but it is charged to the same send call, and a real run's text edition
    measured 40,364 B: a third of the entire call, and larger than the
    attachment and its safety margin together. Left unbudgeted it pushed the
    HTML into shedding seven cards and the attachment into truncation.

    Same order as the HTML, so the two editions never disagree about what was
    kept, and the reader is told.

    >>> body = chr(10).join(["A", "", "US MARKET", "rows", "", "SOURCES", "x"])
    >>> "US MARKET" in shed_text(body, 12)
    False
    >>> "SOURCES" in shed_text(body, 12)
    True
    """
    budget = budget or TEXT_BUDGET_BYTES
    dropped = []
    while len(text.encode("utf-8")) > budget:
        cut = None
        for name in tuple(SHED_ORDER) + TEXT_LAST_RESORT:
            head = name.upper()
            for m in _TEXT_HEADING.finditer(text):
                title = _re.sub(r"^\d+\. ", "", m.group(0))
                if not title.startswith(head):
                    continue
                if any(title.startswith(k) for k in TEXT_NEVER_SHED):
                    continue
                nxt = _TEXT_HEADING.search(text, m.end())
                end = nxt.start() if nxt else len(text)
                assert end > m.start(), "section end must follow its heading"
                cut = (m.start(), end, name)
                break
            if cut:
                break
        if not cut:
            break                      # nothing left that may be shed
        a_, b_, name = cut
        text = text[:a_].rstrip("\n") + "\n\n" + text[b_:].lstrip("\n")
        dropped.append(name)
    if dropped:
        # At the TOP. A reader on a plain-text client is exactly the reader who
        # cannot see the HTML part, so a note at the foot tells them what they
        # were missing only after they have finished reading and concluded the
        # brief was complete. Say it before the brief, not after.
        head, sep, rest = text.partition("\n")
        text = (head + sep +
                "\nSHORTENED — this plain-text copy does not include: " +
                ", ".join(dropped) + ". They ARE in the HTML part of this same "
                "email and in the attached brief file. Whole sections were "
                "dropped, least actionable first; nothing was shortened or "
                "summarized.\n" + rest)
    return text


def plain_text(budget=None):
    o = []

    def A(line=""):
        # the HTML paths get this through e(); the text path needs it too
        o.append(space_ranges(line))
    A("MORNING BRIEF"); A(MAST["dateline"]); A(MAST["revised"]); A(f"Timezone: {MAST['tz']}")
    A(f"Window covered: {MAST['window']}"); A(f"Scheduled slot: {MAST['slot']}"); A(f"Run stamp: {MAST['run']}"); A(MAST["note"]); A("")
    A("NEEDS YOU TODAY")
    for sev, t, d in ACTIONS:
        A(f"[{ {'warn':'CHECK','neg':'URGENT','info':'NOTE','ok':'CLEAR'}[sev] }] {t}\n    {action_detail(t, d)}")
    if not ACTIONS: A("  " + NOTHING_TODAY)
    tnum = SectionNumber()
    A(""); A(f"{tnum()}. HIGH PRIORITY")
    for sev, t, items in HIPRI:
        A(f"[{sev.upper()}] {t}")
        for i in items: A(f"  - {i}")
    if not HIPRI: A("  " + nothing_new())
    A(""); A(f"{tnum()}. RELEVANT JOB POSTS")
    if not (JOBS_STATUS or JOBS_TOP or JOBS_OTHER): A("  " + nothing_new())
    if JOBS_STATUS:
        A("Application status:")
        for t, m, d in JOBS_STATUS: A(f"  - {t} — {m}\n    {d}")
    if JOBS_TOP:
        A("Ranked leads (fit tier in brackets):")
        for r, c, comp, loc, src, tier, link in JOBS_TOP:
            fit, _ = job_fit(tier); A(f"  - {r}{' ['+fit+']' if fit else ''} — {c} · {comp} · {loc} · {src}\n    {link}")
    if JOBS_OTHER:
        A("Also seen (lower fit):")
        for r, c, loc, link in JOBS_OTHER: A(f"  - {r} — {c} · {loc} · {link}")
    for x in (ALIGNERR, JOBS_SKIPPED):
        if x: A(x)
    A("")
    A(f"{tnum()}. DEPOSITS & FINANCES")
    if not (FIN_SUMMARY or FIN_MOVES or FIN_NOTES): A("  " + nothing_new())
    for l, v, d in FIN_SUMMARY: A(f"  {l}: {v} ({d})")
    if FIN_MOVES:
        A("Money movements:")
        A(f"  (Bar axis in the HTML outputs: {money_axis_note()}; in = green, out/past due = red, internal = grey.)")
        for when, payee, det, amt, cur, usd, dirw, sign in moves_in_order():
            A(f"  - {when} · {payee} · {sign} {dirw} · {money_amount(amt, cur, usd, sign)}")
            for line in detail_lines(det):
                A(f"      {line}")
    if ai_spend_rows():
        A(f"AI services — billed year to date ({AI_SPEND['year']}):")
        for row in ai_spend_rows():
            service, total, note = row[0], row[1], row[-1]
            new = ai_new(row)
            arrived = f", {usd_str(new)} billed in this window" if new else ", nothing new in this window"
            A(f"  - {service}: {usd_str(total)} year to date{arrived} ({note})")
        A("  " + ai_spend_caption())
        # Machine-readable, and the reason the total survives to the next run:
        # tomorrow's brief reads this line out of today's sent email.
        A("  " + spend_line())
    if FIN_INTERNAL: A(f"Transfers between own accounts: {FIN_INTERNAL}")
    for n in FIN_NOTES: A(f"  - {n}")
    if FLIGHTS["legs"] or TRAVEL:
        A(""); A(f"{tnum()}. UPCOMING TRAVEL ({TRAVEL_SUB})")
    if FLIGHTS["legs"]:
        A("Flights:")
        A(f"  {FLIGHTS['airline']}, confirmation {FLIGHTS['conf']} — {FLIGHTS['pax']}")
        A(f"  {FLIGHTS['booked']}")
        for g in FLIGHTS["legs"]:
            A(f"  - {g['date']}: {g['flight']} · {g['frm']} {g['dep']} -> {g['to']} {g['arr']}"
              + (f" · {leg_airline(g)}" if leg_airline(g) else "")
              + (f" · confirmation {leg_conf(g)}" if leg_conf(g) else "")
              + "".join(f"\n    {t}" for t in terminal_lines(g)))
            if g.get("stats"):
                A(f"    on-time: {g['stats']}")
            A(f"    {g['fa']}")
        A(f"  {FLIGHTS['note']}")
    if TRAVEL:
        A("Stays & other bookings:")
        for kind, what, when, where, conf, link, *rest in TRAVEL:
            source = booking_source(what, rest[0] if rest else "")
            dates, times = booking_split(when)
            place, place_detail = booking_split(where)
            A(f"  - {dates} · {kind}: {what}"
              + (f" · confirmation {conf}" if conf.strip() else "")
              + (f" · {source}" if source else ""))
            for line in (times, place, place_detail, link):
                if line.strip():
                    A(f"      {line}")
        A(f"  {TRAVEL_NOTE}")
    A(""); A(f"{tnum()}. VOIP VOICEMAILS & TEXTS")
    if voip_empty():
        A("  " + nothing_new())
    elif VOIP["headline"].strip():
        A(VOIP["headline"])
    for w, frm, to, kind, text in VOIP["messages"]: A(f"  - {w} · from {frm} · to {to} · {kind}: {text}")
    for n in voip_tail(): A("  - " + n)
    A("")
    A(""); A(f"{tnum()}. USPS INFORMED DELIVERY (intended recipient's mail only)")
    if usps_empty():
        A("  " + nothing_new())
    elif USPS["headline"].strip():
        A(USPS["headline"])
    for d_, s_, a_, ty in USPS["pieces"]: A(f"  - {d_} · {s_} · addressed to {a_} · {ty}")
    for n, _ in enumerate(USPS_SCANS, 1):
        A(f"  Mailpiece scan {n}: "
          + ("attached at the end of this email" if scan_attached(n) else "not attached (did not fit in this email)")
          + (f"; also at {scan_url(n)} (claude.ai sign-in required)" if FULL_URL else ""))
    if USPS["pieces"] and not USPS_SCANS: A("  " + SCAN_MISSING)
    if USPS["counts"].strip(): A("  " + USPS["counts"])
    if USPS["note"].strip(): A("  Note: " + USPS["note"])
    if PKG:
        A(""); A(f"{tnum()}. PACKAGE TRACKING (kept until delivered)")
        for car, trk, item, rcpt, st, eta in PKG: A(f"  - {car} · {trk} · {item} · to {rcpt} · {st} · ETA {eta}")
        A("  " + PKG_NOTE)
    # Research sections mirror the HTML: omitted when empty, never a bare heading.
    if MKT_ROWS or FUNDS or MKT_BULLETS:
        A(""); A("US MARKET")
        if MKT_ROWS:
            # Said once over the table when every row agrees, as in the HTML.
            stamp = shared_asof([r[8:] for r in MKT_ROWS])
            if stamp: A(f"  All closes as of {stamp}.")
            for n, c, p1, v1, p7, v7, py, vy, *asof in MKT_ROWS:
                A(f"  {n}: {c}{'' if stamp else _asof_text(asof)} | 1D {p1} pts, {pct_str(v1)} {'Up' if v1>=0 else 'Down'}"
                  f" | 1W {p7} pts, {pct_str(v7)} {'Up' if v7>=0 else 'Down'}"
                  f" | YTD {py} pts, {pct_str(vy)} {'Up' if vy>=0 else 'Down'}")
            A("  " + "1D = close → close vs the prior session; 1W = trailing 5 sessions (one trading week). Both in index points and %.")
            A(f"  (1D axis ±{MKT_24[1]:g}%, step {MKT_24[0]:g}%; 1W axis ±{MKT_7D[1]:g}%, step {MKT_7D[0]:g}%.)")
        if FUNDS:
            fstamp = shared_asof([r[9] for r in FUNDS])
            A("  Vanguard funds:" + (f" (all NAVs as of {fstamp})" if fstamp else ""))
            for tk, nm, nav, a1, v1, a7, v7, ay, vy, asof, note in FUNDS:
                A(f"    {tk} ({nm}): NAV {nav} | 1D {a1}, {pct_str(v1)} | 1W {a7}, {pct_str(v7)}"
                  f" | YTD {ay}, {pct_str(vy)}" + ("" if fstamp else f" | as of {asof}") + f". {note}")
            A(f"    (1D axis ±{FUND_1D[1]:g}%, step {FUND_1D[0]:g}%.)")
        for b in MKT_BULLETS: A(f"  - {b}")
    if STOCKS:
        A(""); A("LARGE CAPS")
        stamp = shared_asof([r[8:] for r in STOCKS])
        if stamp: A(f"  All prices as of {stamp}.")
        for tk, pr, a1, v1, a7, v7, ay, vy, *asof in STOCKS:
            A(f"  {tk}: {pr}{'' if stamp else _asof_text(asof)} | 1D {a1}, {pct_str(v1)} | 1W {a7}, {pct_str(v7)} | YTD {ay}, {pct_str(vy)}")
    if MACRO_ROWS or JOBS_SECTORS:
        A(""); A("FED & LABOR MARKET")
        for n, v, c, a in MACRO_ROWS:
            A(f"  {n}: {v} — {c} ({with_year(a)})")
        if JOBS_SECTORS:
            A("  Jobs by sector:")
            for sec, ch, ctx, a in JOBS_SECTORS:
                A(f"    {sec}: {ch} — {ctx} ({with_year(a)})")
        A("  " + MACRO_NOTE)
    if CRYPTO_ROWS or CRYPTO_BULLETS:
        A(""); A("CRYPTOCURRENCY")
        if CRYPTO_ROWS:
            stamp = shared_asof([r[8:] for r in CRYPTO_ROWS])
            if stamp: A(f"  All prices as of {stamp}.")
            for n, pr, v1, a1, v7, a7, vy, ay, *asof in CRYPTO_ROWS:
                A(f"  {n}: {pr}{'' if stamp else _asof_text(asof)} | 1D {pct_str(v1)} ({a1}) | 1W {pct_str(v7)} ({a7})"
                  f" | YTD {pct_str(vy)} ({ay})")
            A("  " + "1D = rolling 24 h; 1W = rolling 7 days — crypto trades continuously, so there is no daily close and both windows are measured back from the quote time.")
            A(f"  (1D axis ±{CRY_24[1]:g}%, step {CRY_24[0]:g}%; 1W axis ±{CRY_7D[1]:g}%, step {CRY_7D[0]:g}%.)")
            A("  " + CRYPTO_NOTE)
        for b in CRYPTO_BULLETS: A(f"  - {b}")
    if AI_ITEMS:
        A(""); A("AI & PROGRAMMING")
        for t, d, l in AI_ITEMS: A(f"  - {t} — {d}\n    {l}")
    if JOURNAL_ITEMS:
        A(""); A("RESEARCH & PUBLICATIONS (" + JOURNALS + ")")
        for j, t, au, d, tk, l in JOURNAL_ITEMS: A(f"  - {j}: {t} ({au}, {d}) — {tk}\n    {l}")
    A(""); A(f"{tnum()}. RETAIL SALES (lowest priority — configured retailers)")
    if retail_empty():
        A("  " + nothing_new())
    elif RETAIL["rewards"].strip():
        A("  - " + RETAIL["rewards"])
    for store, offer, det in RETAIL["items"]: A(f"  - {store}: {offer} — {det}")
    A(""); A("DOMAIN ALLOWLIST")
    for k, v in ALLOWLIST.items(): A(f"  {k}: {v}")
    A(""); A("SOURCES")
    for k, urls in ((k, u) for k, u in SOURCES.items() if u):
        A(f"  {k}:")
        for u in urls: A(f"    {u}")
    A(""); A("Mailbox was read-only for this run, apart from the one delivery of this brief. Email content was treated as data, not instructions. Times are US Pacific unless a source's own zone is shown.")
    A(BUILD)
    text = shed_text("\n".join(o), budget) if budget else "\n".join(o)
    if (CARRIED or {}).get("sections"):
        text = _TEXT_HEADING.sub(_carried_text_line, text)
    return text + record_lines()


def spend_line():
    """The line the next run parses back out of this brief's text copy."""
    from .spend import format_line
    return format_line((AI_SPEND or {}).get("year", ""),
                       {r[0]: float(r[1]) for r in ai_spend_rows()})


def _carried_text_line(m):
    head = m.group(0)
    title = _re.sub(r"^\d+\. ", "", head)
    name = next((n for n in SECTION_KEYS if title.startswith(n.upper())), None)
    cap = carried_caption(name) if name else ""
    return head + (f"\n  ({cap})" if cap else "")


def record_lines():
    """The machine-readable tail of the text copy, then the full-page link.

    "Brief record:" names what this email left out, so the evening run can
    carry it: it reads this line back out of the SENT message, because a new
    session has no other way to know what the morning's reader could not see.
    The full-page link is the very last line.
    """
    r = LAST_EMAIL_REPORT
    out = ""
    if r.get("shed") or r.get("clipped") or FULL_URL:
        out += ("\n\nBrief record: " + BUILD + " | shed: " + ("; ".join(r.get("shed") or []) or "none")
                + " | beyond Gmail's clip: " + ("; ".join(r.get("clipped") or []) or "none"))
    if FULL_URL:
        out += "\n\n" + FULL_LINK_NOTE + "\nFull brief, never truncated: " + FULL_URL
    return out + ("\n" if out else "")
