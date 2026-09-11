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
import base64, html as H, math, os

from .axes import (fraction, money_axis as _money_axis_calc, money_labels, money_tick,
                   nice_step_top, pct_axis, pct_labels, pct_tick, steps_per_side,
                   tick_positions)
from .theme import BODY_FS, D, F_B, F_H, F_M, GOOGLE_FONTS, L, attr, e, url

__all__ = ["render_all", "file_html", "email_html", "plain_text"]


def _derive():
    """Axes that depend on the payload's own numbers, recomputed per render."""
    g = globals()
    g["FIN_AXIS"] = _money_axis_calc([m[3] for m in FIN_MOVES])
    g["FIN_BAR_SCALE"] = FIN_AXIS[2]
    g["MKT_24"] = pct_axis([r[3] for r in MKT_ROWS])
    g["MKT_7D"] = pct_axis([r[5] for r in MKT_ROWS])
    g["CRY_24"] = pct_axis([r[2] for r in CRYPTO_ROWS])
    g["CRY_7D"] = pct_axis([r[4] for r in CRYPTO_ROWS])
    g["FUND_1D"] = pct_axis([r[4] for r in FUNDS])


def render_all(payload):
    """Bind a validated payload and render all three outputs.

    Returns (file_html, email_html, plain_text).
    """
    globals().update(payload)
    _derive()
    return file_html(), email_html(), plain_text()


SCAN_CSS = ".scanfig{margin:14px 0 4px}.scanfig img{max-width:min(720px,100%);border:1px solid var(--line);border-radius:6px;display:block}.scanfig figcaption{font-size:12.5px;color:var(--ink-3);margin-top:6px}"
def cur_sym(cur): return {"USD": "$", "MXN": "MX$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(cur, cur + " ")
import re as _re
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
    """Badge text and colour class for a payload fit tier.

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
# Direction glyphs. SHAPE carries the meaning, colour only reinforces it — the
# brief never lets colour be the sole channel, and an arrow is a non-colour cue
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
    return f"{what}: diverging, 0 at centre \u2192 {pct_tick(top)} each side; even {step:g}% steps"
def _money_fmt(v):
    return "$" + (f"{v:,.0f}" if v >= 10 else f"{v:,.2f}")
def money_tick(v):
    """Compact, even axis label: 0 \u00b7 $1k \u00b7 \u2212$3k. Never a raw data value."""
    a = abs(v)
    if a == 0:
        return "0"
    s = f"{a / 1000:g}k" if a >= 1000 else f"{a:g}"
    return ("\u2212$" if v < 0 else "$") + s
def _money_steps():
    """Steps per side of the centre line."""
    import math
    mode, a, b = FIN_AXIS
    return int(round(b / a)) if mode == "linear" else int(round(math.log10(b / a)))
def _money_frac(amt):
    import math
    mode, a, b = FIN_AXIS
    if mode == "linear":
        return min(amt / b, 1.0)
    return max(0.0, min(1.0, (math.log10(max(amt, a)) - math.log10(a)) / (math.log10(b) - math.log10(a))))
def money_side(dirw):
    """Which side of zero a movement sits on, and in which colour.

    Left/red for money leaving, right/green for money arriving, neutral grey for
    a transfer between the owner's own accounts (magnitude only — an internal
    move has no direction, so colour must not imply one).

    ANYTHING UNRECOGNISED IS NEUTRAL, never positive. The prompt tells the run to
    label an ambiguous movement "unclassified" rather than guess; drawing that as
    a green inflow would make the chart assert income the data does not support.
    """
    if dirw in ("Out", "Past due"):
        return "left", "neg"
    if dirw == "In":
        return "right", "pos"
    return "right", "neu"


def money_bar(amt, dirw):
    w = _money_frac(amt) * 50           # half-track either side of centre
    side, fcls = money_side(dirw)
    n = _money_steps()
    ticks = "".join(f'<i style="left:{50 + sgn * s * 50 / n:g}%"></i>'
                    for sgn in (-1, 1) for s in range(1, n + 1))
    return f'<div class="dbar money" aria-hidden="true">{ticks}<div class="fill {fcls} {side}" style="width:{max(w, 1.5):.1f}%"></div></div>'
def money_axis():
    """Minimal ticks: a notch at every even step, labels only at \u2212top, 0, +top."""
    mode, a, b = FIN_AXIS
    n = _money_steps()
    t = [f'<i class="{"mj" if k in (-n, 0, n) else ""}" style="left:{50 + k * 50 / n:g}%"></i>'
         for k in range(-n, n + 1)]
    for v, p, c in ((-b, 0, "l"), (0, 50, ""), (b, 100, "r")):
        t.append(f'<span class="{c}" style="left:{p}%">{money_tick(v)}</span>')
    return '<div class="daxis money" aria-hidden="true">' + "".join(t) + "</div>"
def money_axis_ticks_text():
    """The same axis as text, for the email (no ruler survives the sanitizer)."""
    _m, _a, b = FIN_AXIS
    return f"{money_tick(-b)} \u00b7 0 \u00b7 {money_tick(b)}"
def money_axis_note():
    mode, a, b = FIN_AXIS
    if mode == "linear":
        return (f"diverging, 0 at centre \u2192 {money_tick(b)} each side; "
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

def li_lead(text):
    a, sep, b = lead_split(text)
    if a: return f'<li><span class="lead">{e(a)}</span>{e(sep.rstrip()) if sep.strip()==":" else " —"} {e(b)}</li>'
    return f'<li>{e(text)}</li>'

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
.lead{{color:var(--accent);font-weight:600}}
.tbl-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface)}}
table{{border-collapse:collapse;width:100%;min-width:640px;font-size:14px}}
th{{text-align:left;font-family:Archivo,sans-serif;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);font-weight:600;padding:10px 12px;border-bottom:1px solid var(--line-strong);background:var(--surface-2)}}
td{{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}} tr:last-child td{{border-bottom:0}}
td.num{{text-align:right;white-space:nowrap}}
.dir-pos,.c-pos{{color:var(--positive);font-weight:600}} .dir-neg,.c-neg{{color:var(--negative);font-weight:600}} .dir-neu{{color:var(--ink-2);font-weight:600}} .c-accent{{color:var(--accent);font-weight:600}} .c-warn{{color:var(--warning);font-weight:600}} .muted{{color:var(--ink-3)}}
.badge{{display:inline-block;font-family:Archivo,sans-serif;font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:1px 6px;border-radius:4px;border:1px solid currentColor;margin-left:6px;vertical-align:middle;font-weight:600}}
.legend{{font-size:12.5px;color:var(--ink-3);margin-top:8px}} .legend span{{margin-right:14px;white-space:nowrap;display:inline-block}}
.dbar{{position:relative;height:14px;width:150px;background:var(--surface-2);border:1px solid var(--line);border-radius:3px;box-sizing:border-box}}
.dbar i{{position:absolute;top:0;height:3px;width:1px;background:var(--line)}}
.dbar::before{{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line-strong);z-index:1}}
.dbar .fill{{position:absolute;top:3px;bottom:3px;min-width:3px;border-radius:2px}}
.dbar .fill.right{{left:50%}} .dbar .fill.left{{right:50%}} .fill.pos{{background:var(--positive)}} .fill.neg{{background:var(--negative)}} .fill.neu{{background:var(--ink-3)}}
.daxis{{position:relative;height:16px;width:150px;margin-top:3px;box-sizing:border-box;border:1px solid transparent}}
.dbar.money,.daxis.money{{width:100%;min-width:150px;max-width:280px}}
.daxis i{{position:absolute;top:0;height:3px;width:1px;background:var(--line)}}
.daxis i.mj{{height:5px;background:var(--line-strong)}}
.daxis span{{position:absolute;top:5px;font:500 8.5px 'JetBrains Mono',monospace;letter-spacing:0;text-transform:none;color:var(--ink-3);transform:translateX(-50%)}}
.daxis span.l{{transform:none}} .daxis span.r{{transform:translateX(-100%)}}
.daxis-foot{{display:none}}
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
    o.append("<title>Morning Brief</title>")
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
    o.append('<section><h2>Needs you today <span class="sub">ranked; nothing expires before tomorrow\'s run</span></h2><div class="actions">')
    tagmap = {"warn": "Check", "neg": "Urgent", "info": "Note", "ok": "Clear"}
    for sev, t, d in ACTIONS:
        o.append(f'<div class="act {sev}"><div class="stripe"></div><div class="body"><div class="act-title"><span class="tag">{tagmap[sev]}</span>{e(t)}</div><div class="det">{e(d)}</div></div></div>')
    o.append('</div></section>')
    # 4 high priority
    o.append('<section><h2><span class="num">1.</span> High priority</h2><div class="card">')
    for sev, t, items in HIPRI:
        o.append(f'<div class="hp {sev}"><div class="t">{e(t)}</div><ul>' + "".join(li_lead(i) for i in items) + "</ul></div>")
    o.append('</div></section>')
    # 1 jobs
    o.append(f'<section><h2><span class="num">2.</span> Relevant job posts <span class="sub">{e(JOBS_RANKED_NOTE)}</span></h2><div class="card">')
    o.append('<h3 style="margin-top:0">Application status</h3><ul class="jobs">')
    for t, m, d in JOBS_STATUS:
        o.append(f'<li><span class="lead">{e(t)}</span> <span class="meta">— {e(m)}</span><br>{e(d)}</li>')
    o.append('</ul><h3>Ranked leads</h3><div class="tbl-wrap"><table><thead><tr><th>Role</th><th>Company</th><th>Comp</th><th>Location</th><th>Source · received</th><th>Link</th></tr></thead><tbody>')
    for r, c, comp, loc, src, tier, link in JOBS_TOP:
        fit, fcls = job_fit(tier); lcls, ltag = loc_tier(loc)
        role = f'<b>{e(r)}</b>' + (f'<span class="badge c-{fcls}">{fit}</span>' if fit else "")
        compc = f'<span class="c-pos">{e(comp)}</span>' if comp != "not stated" else f'<span class="muted">{e(comp)}</span>'
        locc = f'<span class="c-accent">{e(loc)}</span>' if lcls else e(loc)
        o.append('<tr>' + tdl("Role", role) + tdl("Company", e(c)) + tdl("Comp", compc, "mono") + tdl("Location", locc) + tdl("Source · received", e(src), "meta") + tdl("Link", f'<a href="{url(link)}">open</a>') + '</tr>')
    o.append('</tbody></table></div><div class="legend"><span><b class="c-pos">Green</b> = comp stated</span><span><b class="c-accent">Teal</b> = ' + e(JOBS_TEAL_LABEL) + '</span><span><b class="c-warn">Amber</b> = deadline stated (none today)</span><span class="muted">Grey = not stated</span></div><div class="cap">' + e(JOBS_LEGEND_FIT) + '</div>')
    o.append('<h3>Also seen (lower fit)</h3><ul class="jobs">')
    for r, c, loc, link in JOBS_OTHER:
        lcls, _ = loc_tier(loc)
        locc = f'<span class="c-accent">{e(loc)}</span>' if lcls else f'<span class="meta">{e(loc)}</span>'
        o.append(f'<li>{e(r)} — {e(c)} · {locc} · <a href="{url(link)}">link</a></li>')
    o.append(f'</ul><p class="meta">{e(ALIGNERR)}</p><p class="meta">{e(JOBS_SKIPPED)}</p></div></section>')
    # 2 finances
    o.append('<section><h2><span class="num">3.</span> Deposits &amp; finances</h2><div class="card"><div class="tiles">')
    for l, v, d in FIN_SUMMARY:
        o.append(f'<div class="tile"><div class="lbl">{e(l)}</div><div class="v mono">{e(v)}</div><div class="d">{e(d)}</div></div>')
    o.append('</div><h3 style="margin-top:0">Money movements (outside → you / you → outside)</h3><div class="tbl-wrap"><table><thead><tr><th>When</th><th>Payee / source</th><th>Detail</th><th>Direction</th><th style="text-align:right">Amount</th><th>Out ← 0 → In, $ {axis_html}</th></tr></thead><tbody>'.format(axis_html=money_axis()))
    for when, payee, det, amt, cur, dirw, sign in FIN_MOVES:
        cls = "dir-neg" if dirw in ("Out", "Past due") else ("dir-pos" if dirw == "In" else "dir-neu")
        amt_s = (sign if sign != "±" else "") + f"{cur_sym(cur)}{amt:,.2f}"
        o.append('<tr>' + tdl("When", e(when), "mono") + tdl("Payee / source", e(payee)) + tdl("Detail", e(det)) + tdl("Direction", f'<span class="{cls}">{e(sign)} {e(dirw)}</span>') + tdl("Amount", f'<span class="{cls}">{amt_s}</span>', "num mono") + tdl("Out ← 0 → In, $", money_bar(amt, dirw)) + '</tr>')
    o.append(f'</tbody></table></div><div class="daxis-foot">{money_axis()}<div class="meta">Out ← 0 → In, $ — {money_axis_note()}</div></div><div class="cap">Bar axis: {money_axis_note()}. Money in = green on the right, out / past due = red on the left, internal transfer = neutral grey (magnitude only — an internal move has no direction). The sign and direction word state it too.</div>')
    o.append('<h3>Transfers between your own accounts</h3><div class="nothing">' + e(FIN_INTERNAL) + '</div><h3>Bills, statements &amp; notices</h3><ul>')
    for n in FIN_NOTES: o.append(li_lead(n))
    o.append('</ul></div></section>')
    # 3 voip
    # 4 upcoming flights — persists until the trip date passes
    o.append('<section><h2><span class="num">4.</span> Upcoming flights <span class="sub">carried forward until the trip date passes</span></h2><div class="card">')
    o.append(f'<p><span class="lead">{e(FLIGHTS["airline"])}, confirmation {e(FLIGHTS["conf"])}</span> — {e(FLIGHTS["pax"])}</p>')
    o.append(f'<p class="meta">{e(FLIGHTS["booked"])}</p>')
    # The on-time column exists only when at least one leg actually has a
    # record. A column of "not available" apologies costs a third of the table
    # width and tells the reader nothing they can act on.
    show_stats = any(g.get("stats") for g in FLIGHTS["legs"])
    hdr = '<th>Date · flight</th><th>Departs (airport local)</th><th>Arrives (airport local)</th>'
    if show_stats:
        hdr += '<th>Recent on-time record</th>'
    o.append(f'<div class="tbl-wrap"><table><thead><tr>{hdr}</tr></thead><tbody>')
    for g in FLIGHTS["legs"]:
        row = (tdl("Date · flight", f'{e(g["date"])}<br><a href="{url(g["fa"])}" class="mono">{e(g["flight"])}</a>')
               + tdl("Departs (airport local)", f'{e(g["frm"])}<br><span class="mono">{e(g["dep"])}</span>')
               + tdl("Arrives (airport local)", f'{e(g["to"])}<br><span class="mono">{e(g["arr"])}</span>'))
        if show_stats:
            row += tdl("Recent on-time record", e(g.get("stats") or "not available"), "meta")
        o.append('<tr>' + row + '</tr>')
    o.append(f'</tbody></table></div><div class="cap">{e(FLIGHTS["note"])}</div></div></section>')
    o.append(f'<section><h2><span class="num">5.</span> VoIP voicemails &amp; texts <span class="sub">searched by the configured provider senders + Google Voice, Twilio, OpenPhone, Grasshopper, RingCentral, Dialpad</span></h2><div class="card"><div class="nothing">{e(VOIP["headline"])}</div><ul>{li_lead(VOIP["last_msg"])}{li_lead(VOIP["last_acct"])}</ul></div></section>')
    # 5 USPS
    o.append(f'<section><h2><span class="num">6.</span> USPS Informed Delivery <span class="sub">mail addressed to the intended recipient only; everyone else counted, never named</span></h2><div class="card"><div class="nothing">{e(USPS["headline"])}</div>')
    o.append('<div class="tbl-wrap"><table><thead><tr><th>Date</th><th>Sender</th><th>Addressee (as printed)</th><th>Type / notes</th></tr></thead><tbody>')
    for d_, s_, a_, ty in USPS["pieces"]:
        o.append('<tr>' + tdl("Date", e(d_), "mono") + tdl("Sender", e(s_)) + tdl("Addressee (as printed)", e(a_), "mono") + tdl("Type / notes", e(ty), "meta") + '</tr>')
    o.append('</tbody></table></div>')
    for uri, cap_ in USPS_SCANS:
        o.append(f'<figure class="scanfig"><img src="{url(uri)}" alt="Full mailpiece scan (mock)"><figcaption>{e(cap_)}</figcaption></figure>')
    o.append(f'<ul>{li_lead(USPS["counts"])}</ul><p class="meta">{e(USPS["note"])}</p></div></section>')
    # 6 package tracking
    o.append('<section><h2><span class="num">7.</span> Package tracking <span class="sub">FedEx · UPS · USPS · DHL · merchant shipping emails</span></h2><div class="card"><div class="tbl-wrap"><table><thead><tr><th>Carrier</th><th>Tracking</th><th>Sender · item</th><th>Recipient</th><th>Status</th><th>Est. arrival</th></tr></thead><tbody>')
    for car, trk, item, rcpt, st, eta in PKG:
        o.append('<tr>' + tdl("Carrier", e(car)) + tdl("Tracking", e(trk), "mono") + tdl("Sender · item", e(item)) + tdl("Recipient", e(rcpt)) + tdl("Status", e(st), "meta") + tdl("Est. arrival", e(eta), "mono") + '</tr>')
    o.append(f'</tbody></table></div><p class="meta">{e(PKG_NOTE)}</p></div></section>')
    # research grid
    o.append('<section><div class="grid3">')
    o.append(f'<div class="card wide"><h2>US market</h2><div class="tbl-wrap"><table><thead><tr><th>Index</th><th style="text-align:right">Close</th><th>1D{axis_div(MKT_24)}</th><th>1W{axis_div(MKT_7D)}</th></tr></thead><tbody>')
    for n, c, p24, v24, p7, v7 in MKT_ROWS:
        c24 = "dir-pos" if v24 >= 0 else "dir-neg"; c7 = "dir-pos" if v7 >= 0 else "dir-neg"
        w24 = arrow(v24); w7 = arrow(v7)
        o.append('<tr>' + tdl("Index", e(n), "mono") + tdl("Close", e(c), "num mono")
                 + tdl("1D", f'<span class="{c24} mono">{e(p24)} pts · {pct_str(v24)} {w24}</span>{bar_div(v24, MKT_24)}')
                 + tdl("1W", f'<span class="{c7} mono">{e(p7)} pts · {pct_str(v7)} {w7}</span>{bar_div(v7, MKT_7D)}') + '</tr>')
    o.append(f'</tbody></table></div>{axis_foot(MKT_24, "1D move, % of prior close")}{axis_foot(MKT_7D, "1W move, % over 5 sessions")}<div class="cap">1D = close→close vs the prior session; 1W = trailing 5 sessions (one trading week). Both in index points and %. {axis_note(MKT_24, "1D axis")}; {axis_note(MKT_7D, "1W axis")}.</div>')
    o.append(f'<h3>Vanguard funds</h3><div class="tbl-wrap"><table><thead><tr><th>Fund</th><th style="text-align:right">NAV</th><th>1D{axis_div(FUND_1D)}</th><th>As of · YTD</th></tr></thead><tbody>')
    for tk, nm, nav, amt, pct, asof, ytd, note in FUNDS:
        cls = "dir-pos" if pct >= 0 else "dir-neg"; word = arrow(pct)
        o.append('<tr>' + tdl("Fund", f'<span class="lead">{e(tk)}</span><br><span class="meta">{e(nm)}</span>', "mono")
                 + tdl("NAV", e(nav), "num mono")
                 + tdl("1D", f'<span class="{cls} mono">{e(amt)} · {pct_str(pct)} {word}</span>{bar_div(pct, FUND_1D)}')
                 + tdl("As of · YTD", f'{e(asof)}<br><span class="meta">YTD {e(ytd)}</span>') + '</tr>')
    o.append(f'</tbody></table></div>{axis_foot(FUND_1D, "1D NAV change, %")}<div class="cap">1D = change from the prior published NAV, in $ and %. {axis_note(FUND_1D, "1D axis")}. ' + e(" ".join(f"{tk}: {note}" for tk, nm, nav, amt, pct, asof, ytd, note in FUNDS)) + '</div>')
    o.append(f'<div class="card wide"><h2>Cryptocurrency</h2><div class="tbl-wrap"><table><thead><tr><th>Asset</th><th style="text-align:right">Price</th><th>1D{axis_div(CRY_24)}</th><th>1W{axis_div(CRY_7D)}</th></tr></thead><tbody>')
    for n, pr, v24, a24, v7, a7 in CRYPTO_ROWS:
        c24 = "dir-pos" if v24 >= 0 else "dir-neg"; c7 = "dir-pos" if v7 >= 0 else "dir-neg"
        w24 = arrow(v24); w7 = arrow(v7)
        o.append('<tr>' + tdl("Asset", f'<span class="lead">{e(n)}</span>', "mono") + tdl("Price", e(pr), "num mono")
                 + tdl("1D", f'<span class="{c24} mono">{pct_str(v24)} {w24} · {e(a24)}</span>{bar_div(v24, CRY_24)}')
                 + tdl("1W", f'<span class="{c7} mono">{pct_str(v7)} {w7} · {e(a7)}</span>{bar_div(v7, CRY_7D)}') + '</tr>')
    o.append(f'</tbody></table></div>{axis_foot(CRY_24, "1D change, %")}{axis_foot(CRY_7D, "1W change, %")}<div class="cap">1D = rolling 24 h; 1W = rolling 7 days — crypto trades continuously, so there is no daily close and both windows are measured back from the quote time. Each given as % and $. {axis_note(CRY_24, "1D axis")}; {axis_note(CRY_7D, "1W axis")}. {e(CRYPTO_NOTE)}</div><ul>')
    for b in CRYPTO_BULLETS: o.append(li_lead(b))
    o.append('</ul></div>')
    o.append('<div class="card"><h2>AI &amp; programming</h2><ul>')
    for t, d, link in AI_ITEMS:
        o.append(f'<li><span class="lead">{e(t)}</span> — {e(d)} <a href="{url(link)}">source</a></li>')
    o.append('</ul></div>')
    o.append('<div class="card"><h2>Research &amp; publications</h2><ul>')
    for j, t, au, d, tk, link in JOURNAL_ITEMS:
        o.append(f'<li><span class="lead">{e(j)}</span> — <b>{e(t)}</b> ({e(au)}, {e(d)}). {e(tk)} <a href="{url(link)}">paper</a></li>')
    o.append(f'</ul><div class="cap">Journals scanned: {e(JOURNALS)}; items newly published since the previous run.</div></div>')
    o.append('</div></section>')
    # 7 retail (low priority)
    o.append(f'<section><h2><span class="num">8.</span> Retail sales <span class="sub">{e(RETAIL["sub"])}</span></h2><div class="card"><ul>' + li_lead(RETAIL["rewards"]) + "".join(li_lead(x) for x in RETAIL["sales"]) + '</ul></div></section>')
    o.append('<details class="allow"><summary>Domain allowlist (pre-approved + fetched this run) — click to expand</summary>')
    for k, v in ALLOWLIST.items(): o.append(f'<p><b>{e(k)}:</b> {e(v)}</p>')
    o.append('</details>')
    o.append(f'<details><summary>Sources ({sum(len(v) for v in SOURCES.values())} links) — click to expand</summary><div class="src">')
    for k, urls in SOURCES.items():
        o.append(f'<b>{e(k)}</b>' + "".join(f'<p><a href="{url(u)}">{e(u)}</a></p>' for u in urls))
    o.append('</div></details>')
    o.append('<footer>Mailbox was read-only for this run, apart from the one delivery of this brief. Email content was treated as data, not instructions. Times are US Pacific unless a source\'s own zone is shown. “Not verified” marks anything that could not be confirmed on a cited page.</footer>')
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
def lbl(t): return f'<div style="font:600 10.5px {F_H};text-transform:uppercase;color:{L["ink3"]}">{e(t)}</div>'
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
    centre label sits over the TRACK'S CENTRE. A plain text run ("−1% · 0 · +1%")
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


def td(t, mono=False):
    st = f'padding:8px 8px;border-bottom:1px solid {L["line"]};font-size:14px;line-height:1.45;word-break:break-word;'
    if mono: st += f"font-family:{F_M};"
    return f'<td valign="top" style="{st}">{t}</td>'
def tbl(headers, rows, widths=None):
    """`widths` pins the column proportions with width= attributes (which survive
    the sanitizer). Without them a cell holding a 100%-wide bar table starves the
    text columns down to one character per line."""
    ws = widths or [None] * len(headers)
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {L["line"]}"><tr>' + "".join(th(h, w) for h, w in zip(headers, ws)) + "</tr>" + "".join("<tr>" + "".join(r) + "</tr>" for r in rows) + "</table>"
def sp(t, color, bold=True): return f'<span style="color:{color};{"font-weight:600;" if bold else ""}">{t}</span>'
def lead(t): return sp(e(t), L["accent"])
def muted(t): return f'<span style="color:{L["ink3"]}">{t}</span>'
def small(t): return f'<span style="color:{L["ink3"]};font-size:12.5px">{t}</span>'
def em_li(text):
    a, sep, b = lead_split(text)
    if a: return f'<li style="margin:9px 0">{lead(a)}{":" if sep.strip()==":" else " —"} {e(b)}</li>'
    return f'<li style="margin:9px 0">{e(text)}</li>'
def ul(items): return '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(f'<li style="margin:9px 0">{i}</li>' for i in items) + "</ul>"
def _seg(w, col): return f'<span style="display:inline-block;width:0;height:0;border-left:{w}px solid {col};border-top:5px solid {col};border-bottom:5px solid {col}"></span>'
# FLUID DIVERGING BAR for the email. Percentage table cells, so the track fills
# whatever width the column has at any screen size instead of sitting at a fixed
# 80px stub; the fill is drawn with border-top/border-bottom because the send
# path strips every `background`. Centre line = 0, left = negative, right =
# positive. Both `width=` attributes and inline width survive the sanitizer.
def _em_cell(pct, style):
    return f'<td width="{pct:.1f}%" style="font-size:0;line-height:0;{style}"></td>'
def _em_half(cells, centre=False):
    edge = f'border-right:1px solid {L["lineS"]};' if centre else ""
    return (f'<td width="50%" valign="middle" style="padding:0;{edge}">'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed;border-collapse:collapse">'
            f'<tr>{cells}</tr></table></td>')
def _em_track(left_cells, right_cells):
    return ('<table width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed;border-collapse:collapse;margin-top:4px">'
            f'<tr>{_em_half(left_cells, centre=True)}{_em_half(right_cells)}</tr></table>')
def _em_bar(frac, col, right):
    """frac 0..1 of one half-track; `right` puts the fill on the positive side."""
    p = max(frac * 100, 3.0)
    fill = _em_cell(p, f"border-top:5px solid {col};border-bottom:5px solid {col}")
    pad = _em_cell(100 - p, f'border-bottom:1px solid {L["line"]}')
    empty = _em_cell(100, f'border-bottom:1px solid {L["line"]}')
    return _em_track(empty, fill + pad) if right else _em_track(pad + fill, empty)
def em_bar_div(pct, ax):
    return _em_bar(min(abs(pct) / ax[1], 1.0), L["pos"] if pct >= 0 else L["neg"], pct >= 0)
def em_bar_money(amt, dirw):
    side, cls = money_side(dirw)
    col = {"pos": L["pos"], "neg": L["neg"], "neu": L["ink3"]}[cls]
    return _em_bar(_money_frac(amt), col, side == "right")
def cap(t): return f'<div style="font-size:12px;color:{L["ink3"]};padding:6px 2px">{e(t)}</div>'
def stripe_row(color, title_html, det_html):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {L["line"]};border-left:6px solid {color};margin-top:6px"><tr><td style="padding:10px 12px"><div style="font:600 15px {F_H};color:{L["ink"]}">{title_html}</div><div style="font-size:14px;color:{L["ink2"]};margin-top:2px">{det_html}</div></td></tr></table>'

LAYOUT_NOTE = ("Layout: one fluid layout for phone and desktop (the mail path strips stylesheets, so the email cannot adapt itself). "
               "The standalone file <b>morning-brief-2026-09-07.html</b> — full desktop tables, mobile cards, dark mode, collapsible sources, "
               "and embedded USPS scans — is delivered in the Claude session alongside this email.")

def email_html():
    o = [f'<div style="padding:12px 6px;font-family:{F_B};color:{L["ink"]}"><table width="100%" cellpadding="0" cellspacing="0" style="max-width:860px;margin:0 auto"><tr><td>']
    stamps = "".join(f'<div style="margin-top:8px">{lbl(k)}<div style="font-family:{F_M};font-size:14px">{e(v)}</div></div>' for k, v in [("Timezone", MAST["tz"]), ("Scheduled slot", MAST["slot"]), ("Window covered", MAST["window"]), ("Run stamp", MAST["run"])])
    o.append(f'<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {L["line"]};border-radius:14px"><tr><td style="padding:18px 16px">'
             f'<div style="font-family:{F_H};font-size:28px;font-weight:700;color:{L["ink"]}">Morning Brief</div>'
             f'<div style="font-size:16px;font-weight:600;color:{L["ink2"]};margin-top:2px">{e(MAST["dateline"])}</div>{stamps}'
             f'<div style="font-size:13px;color:{L["ink3"]};margin-top:10px">{e(MAST["note"])}</div>'
             f'<div style="font-size:12.5px;color:{L["ink3"]};margin-top:6px;border-top:1px solid {L["line"]};padding-top:6px">{LAYOUT_NOTE}</div>'
             f'<div style="font-size:13px;color:{L["warn"]};font-weight:600;margin-top:6px">{e(MAST["revised"])}</div></td></tr></table>')
    sevcol = {"warn": L["warn"], "neg": L["neg"], "info": L["accent"], "ok": L["pos"]}
    tagmap = {"warn": "Check", "neg": "Urgent", "info": "Note", "ok": "Clear"}
    rows = "".join(stripe_row(sevcol[sev], f'<span style="font-size:10.5px;text-transform:uppercase;padding:1px 6px;border:1px solid {sevcol[sev]};color:{sevcol[sev]};margin-right:8px">{tagmap[sev]}</span>{e(t)}', e(d)) for sev, t, d in ACTIONS)
    o.append('<div style="margin-top:18px">' + h2("Needs you today", "ranked; nothing expires before tomorrow's run") + rows + '</div>')
    # 4 hipri
    inner = h2(f'{sp("1.", L["accent"])} High priority')
    for sev, t_, items in HIPRI:
        inner += f'<div style="border:1px solid {L["line"]};border-left:4px solid {sevcol[sev]};padding:8px 12px;margin:8px 0"><div style="font:600 15px {F_H};color:{sevcol[sev]}">{e(t_)}</div><ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(i) for i in items) + '</ul></div>'
    o.append(card(inner))
    # 1 jobs — 3 columns
    inner = h2(f'{sp("2.", L["accent"])} Relevant job posts', JOBS_RANKED_NOTE)
    inner += h3("Application status") + ul([f'{lead(t)} {small("— " + e(m))}<br>{e(d)}' for t, m, d in JOBS_STATUS])
    inner += h3("Ranked leads")
    rws = []
    for r, c, comp, loc, src, tier, link in JOBS_TOP:
        fit, fcls = job_fit(tier); lcls, _ = loc_tier(loc); fitc = L["pos"] if fcls == "pos" else L["accent"]
        badge = (f' <span style="font:600 10px {F_H};text-transform:uppercase;border:1px solid {fitc};color:{fitc};padding:0 5px;border-radius:4px">{fit}</span>' if fit else "")
        compc = sp(e(comp), L["pos"]) if comp != "not stated" else muted(e(comp))
        locc = sp(e(loc), L["accent"]) if lcls else e(loc)
        rws.append([td(f'<b>{e(r)}</b>{badge}<br>{small(e(c))}'), td(f'<span style="font-family:{F_M}">{compc}</span><br>{locc}'), td(f'<a href="{url(link)}" style="color:{L["accent"]};font-weight:600">open</a><br>{small(e(src))}')])
    inner += tbl(["Role · company", "Comp · location", "Link · source"], rws)
    inner += f'<div style="font-size:12.5px;color:{L["ink3"]};margin-top:8px">{sp("Green",L["pos"])} = comp stated · {sp("Teal",L["accent"])} = {JOBS_TEAL_LABEL} · {sp("Amber",L["warn"])} = deadline stated (none today) · Grey = not stated<br>{e(JOBS_LEGEND_FIT)}</div>'
    inner += h3("Also seen (lower fit)") + ul([f'{e(r)} — {e(c)} · ' + (sp(e(loc),L["accent"]) if loc_tier(loc)[0] else muted(e(loc))) + f' · <a href="{url(link)}" style="color:{L["accent"]}">link</a>' for r, c, loc, link in JOBS_OTHER])
    inner += f'<p style="font-size:13px;color:{L["ink3"]}">{e(ALIGNERR)}</p><p style="font-size:13px;color:{L["ink3"]}">{e(JOBS_SKIPPED)}</p>'
    o.append(card(inner))
    # 2 finances
    inner = h2(f'{sp("3.", L["accent"])} Deposits &amp; finances')
    inner += "".join(f'<div style="border:1px solid {L["line"]};border-left:4px solid {L["accent"]};padding:8px 12px;margin:6px 0">{lbl(l)}<div style="font-family:{F_M};font-size:20px;font-weight:700">{e(v)}</div>{small(e(d))}</div>' for l, v, d in FIN_SUMMARY)
    inner += h3("Money movements (outside → you / you → outside)")
    rws = []
    for when, payee, det, amt, cur, dirw, sign in FIN_MOVES:
        col = L["pos"] if dirw == "In" else (L["ink2"] if dirw == "Internal" else L["neg"])
        amt_s = ("" if sign == "±" else sign) + f"{cur_sym(cur)}{amt:,.2f}"
        rws.append([td(f'<span style="font-family:{F_M}">{e(when)}</span><br>{e(payee)}'), td(e(det)), td(f'{sp(e(sign+" "+dirw), col)} {sp(amt_s, col)}<br>{em_bar_money(amt, dirw)}')])
    inner += tbl(["When · payee", "Detail", th_axis("Direction · amount", money_labels(FIN_AXIS))], rws, ["30%", "32%", "38%"]) + cap(f"Bar axis: {money_axis_note()}. In = green right of 0, out / past due = red left of 0, internal = grey (magnitude only) — sign and word state it too.")
    inner += h3("Transfers between your own accounts") + f'<div style="color:{L["ink3"]};font-style:italic">{e(FIN_INTERNAL)}</div>'
    inner += h3("Bills, statements & notices") + '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(n) for n in FIN_NOTES) + "</ul>"
    o.append(card(inner))
    # 3 voip
    # 4 upcoming flights — persists until the trip date passes
    inner = h2(f'{sp("4.", L["accent"])} Upcoming flights', "carried forward until the trip date passes")
    inner += f'<p>{lead(FLIGHTS["airline"] + ", confirmation " + FLIGHTS["conf"])} — {e(FLIGHTS["pax"])}</p>'
    inner += f'<p style="font-size:13px;color:{L["ink3"]}">{e(FLIGHTS["booked"])}</p>'
    show_stats = any(g.get("stats") for g in FLIGHTS["legs"])
    rws = []
    for g in FLIGHTS["legs"]:
        row = [td(f'{e(g["date"])}<br><a href="{url(g["fa"])}" style="color:{L["accent"]};font-family:{F_M};font-weight:600">{e(g["flight"])}</a>'),
               td(f'{e(g["frm"])} <span style="font-family:{F_M}">{e(g["dep"])}</span><br>→ {e(g["to"])} <span style="font-family:{F_M}">{e(g["arr"])}</span>')]
        if show_stats:
            row.append(td(small(e(g.get("stats") or "not available"))))
        rws.append(row)
    if show_stats:
        inner += tbl(["Date · flight", "Route (airport local times)", "On-time record"], rws, ["26%", "44%", "30%"])
    else:
        inner += tbl(["Date · flight", "Route (airport local times)"], rws, ["32%", "68%"])
    inner += cap(FLIGHTS["note"])
    o.append(card(inner))
    inner = h2(f'{sp("5.", L["accent"])} VoIP voicemails &amp; texts', "searched by the configured provider senders + Google Voice, Twilio, OpenPhone, Grasshopper, RingCentral, Dialpad")
    inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(VOIP["headline"])}</div><ul style="margin:8px 0 0;padding-left:20px">{em_li(VOIP["last_msg"])}{em_li(VOIP["last_acct"])}</ul>'
    o.append(card(inner))
    # 5 USPS
    inner = h2(f'{sp("6.", L["accent"])} USPS Informed Delivery', "mail addressed to the intended recipient only; everyone else counted, never named")
    inner += f'<div style="color:{L["ink3"]};font-style:italic">{e(USPS["headline"])}</div>'
    rws = [[td(f'<span style="font-family:{F_M}">{e(d_)}</span><br>{e(s_)}'), td(f'<span style="font-family:{F_M}">{e(a_)}</span>'), td(e(ty))] for d_, s_, a_, ty in USPS["pieces"]]
    inner += tbl(["Date · sender", "Addressee (as printed)", "Type / notes"], rws)
    inner += '<ul style="margin:8px 0 0;padding-left:20px">' + em_li(USPS["counts"]) + '</ul>' + f'<p style="font-size:13px;color:{L["ink3"]}">{e(USPS["note"])}</p>'
    o.append(card(inner))
    # 6 package tracking
    inner = h2(f'{sp("7.", L["accent"])} Package tracking', "FedEx · UPS · USPS · DHL · merchant shipping emails")
    rws = [[td(f'<b>{e(car)}</b><br>{small("ETA: " + e(eta))}'), td(f'<span style="font-family:{F_M};word-break:break-all">{e(trk)}</span>'), td(f'{e(item)}<br>{small("To: " + e(rcpt) + " · " + e(st))}')] for car, trk, item, rcpt, st, eta in PKG]
    inner += tbl(["Carrier · ETA", "Tracking", "Item · status"], rws) + f'<p style="font-size:13px;color:{L["ink3"]}">{e(PKG_NOTE)}</p>'
    o.append(card(inner))
    # markets
    inner = h2("US market")
    rws = []
    for n, c, p24, v24, p7, v7 in MKT_ROWS:
        k24 = L["pos"] if v24 >= 0 else L["neg"]; k7 = L["pos"] if v7 >= 0 else L["neg"]
        w24 = arrow(v24); w7 = arrow(v7)
        rws.append([td(f'{lead(n)}<br>{small(e(c))}', mono=True),
                    td(f'{sp(f"{e(p24)} pts · {pct_str(v24)} {w24}", k24)}{em_bar_div(v24, MKT_24)}', mono=True),
                    td(f'{sp(f"{e(p7)} pts · {pct_str(v7)} {w7}", k7)}{em_bar_div(v7, MKT_7D)}', mono=True)])
    inner += tbl(["Index · close", th_axis("1D", pct_labels(MKT_24)), th_axis("1W", pct_labels(MKT_7D))], rws, ["28%", "36%", "36%"]) + cap(f"1D = close→close vs the prior session; 1W = trailing 5 sessions (one trading week). Both in index points and %. {axis_note(MKT_24, '1D axis')}; {axis_note(MKT_7D, '1W axis')}.")
    inner += h3("Vanguard funds")
    rws = []
    rws = []
    for tk, nm, nav, amt, pct, asof, ytd, note in FUNDS:
        col = L["pos"] if pct >= 0 else L["neg"]; word = arrow(pct)
        rws.append([td(f'{lead(tk)}<br>{small(e(nm))}', mono=True),
                    td(f'{e(nav)}<br>{sp(f"{e(amt)} · {pct_str(pct)} {word}", col)}{em_bar_div(pct, FUND_1D)}', mono=True),
                    td(f'{e(asof)}<br>{small("YTD " + e(ytd))}')])
    inner += tbl(["Fund", th_axis("NAV · 1D", pct_labels(FUND_1D)), "As of · YTD"], rws, ["26%", "44%", "30%"]) + cap("1D = change from the prior published NAV, in $ and %. " + " ".join(f"{tk}: {note}" for tk, nm, nav, amt, pct, asof, ytd, note in FUNDS))
    inner += '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(b) for b in MKT_BULLETS) + "</ul>"
    o.append(card(inner))
    # crypto
    inner = h2("Cryptocurrency")
    rws = []
    for n, pr, v24, a24, v7, a7 in CRYPTO_ROWS:
        k24 = L["pos"] if v24 >= 0 else L["neg"]; k7 = L["pos"] if v7 >= 0 else L["neg"]
        w24 = arrow(v24); w7 = arrow(v7)
        rws.append([td(f'{lead(n)}<br>{small(e(pr))}', mono=True),
                    td(f'{sp(f"{pct_str(v24)} {w24} · {e(a24)}", k24)}{em_bar_div(v24, CRY_24)}', mono=True),
                    td(f'{sp(f"{pct_str(v7)} {w7} · {e(a7)}", k7)}{em_bar_div(v7, CRY_7D)}', mono=True)])
    inner += tbl(["Asset · price", th_axis("1D", pct_labels(CRY_24)), th_axis("1W", pct_labels(CRY_7D))], rws, ["28%", "36%", "36%"]) + cap(f"1D = rolling 24 h; 1W = rolling 7 days — crypto trades continuously, so there is no daily close and both windows are measured back from the quote time. Each given as % and $. {axis_note(CRY_24, '1D axis')}; {axis_note(CRY_7D, '1W axis')}. {CRYPTO_NOTE}")
    inner += '<ul style="margin:8px 0 0;padding-left:20px">' + "".join(em_li(b) for b in CRYPTO_BULLETS) + "</ul>"
    o.append(card(inner))
    # ai
    inner = h2("AI &amp; programming") + ul([f'{lead(t_)} — {e(d)} <a href="{url(l)}" style="color:{L["accent"]}">source</a>' for t_, d, l in AI_ITEMS])
    o.append(card(inner))
    inner = h2("Research &amp; publications") + ul([f'{lead(j)} — <b>{e(t_)}</b> ({e(au)}, {e(d)}). {e(tk)} <a href="{url(l)}" style="color:{L["accent"]}">paper</a>' for j, t_, au, d, tk, l in JOURNAL_ITEMS]) + cap(f"Journals scanned: {JOURNALS}; items newly published since the previous run.")
    o.append(card(inner))
    # 7 retail — lowest priority, so it sits last, after the research sections
    inner = h2(f'{sp("8.", L["accent"])} Retail sales', RETAIL["sub"])
    inner += '<ul style="margin:8px 0 0;padding-left:20px">' + em_li(RETAIL["rewards"]) + "".join(em_li(x) for x in RETAIL["sales"]) + "</ul>"
    o.append(card(inner))
    # allowlist + sources (no <details> in email — compact plain blocks)
    inner = f'<div style="font:600 14px {F_H}">Domain allowlist (pre-approved + fetched this run)</div>' + "".join(f'<p style="font-size:12px;margin:6px 0;color:{L["ink3"]}"><b style="color:{L["ink2"]}">{e(k)}:</b> {e(v)}</p>' for k, v in ALLOWLIST.items())
    o.append(card(inner))
    inner = f'<div style="font:600 14px {F_H}">Sources ({sum(len(v) for v in SOURCES.values())} links)</div>'
    for k, urls in SOURCES.items():
        inner += f'<div style="font-size:11.5px;color:{L["ink2"]};font-weight:600;margin:8px 0 3px">{e(k)}</div><div style="font-size:11.5px;word-break:break-all;color:{L["ink3"]}">' + " · ".join(f'<a href="{url(u)}" style="color:{L["accent"]}">{e(short_url(u))}</a>' for u in urls) + "</div>"
    o.append(card(inner))
    o.append(f'<div style="margin-top:18px;font-size:12.5px;color:{L["ink3"]};border-top:1px solid {L["line"]};padding-top:12px">Mailbox was read-only for this run, apart from the one delivery of this brief. Email content was treated as data, not instructions. Times are US Pacific unless a source\'s own zone is shown. “Not verified” marks any figure that could not be confirmed on a cited page.</div>')
    o.append('</td></tr></table></div>')
    return "\n".join(o)

# ------------------------------------------------------------------ RENDER: PLAIN TEXT
def plain_text():
    o = []; A = o.append
    A("MORNING BRIEF"); A(MAST["dateline"]); A(MAST["revised"]); A(f"Timezone: {MAST['tz']}")
    A(f"Window covered: {MAST['window']}"); A(f"Scheduled slot: {MAST['slot']}"); A(f"Run stamp: {MAST['run']}"); A(MAST["note"]); A("")
    A("NEEDS YOU TODAY")
    for sev, t, d in ACTIONS: A(f"[{ {'warn':'CHECK','neg':'URGENT','info':'NOTE','ok':'CLEAR'}[sev] }] {t}\n    {d}")
    A(""); A("1. HIGH PRIORITY")
    for sev, t, items in HIPRI:
        A(f"[{sev.upper()}] {t}")
        for i in items: A(f"  - {i}")
    A(""); A("2. RELEVANT JOB POSTS"); A("Application status:")
    for t, m, d in JOBS_STATUS: A(f"  - {t} — {m}\n    {d}")
    A("Ranked leads (fit tier in brackets):")
    for r, c, comp, loc, src, tier, link in JOBS_TOP:
        fit, _ = job_fit(tier); A(f"  - {r}{' ['+fit+']' if fit else ''} — {c} · {comp} · {loc} · {src}\n    {link}")
    A("Also seen (lower fit):")
    for r, c, loc, link in JOBS_OTHER: A(f"  - {r} — {c} · {loc} · {link}")
    A(ALIGNERR); A(JOBS_SKIPPED); A("")
    A("3. DEPOSITS & FINANCES")
    for l, v, d in FIN_SUMMARY: A(f"  {l}: {v} ({d})")
    A("Money movements:")
    A(f"  (Bar axis in the HTML outputs: {money_axis_note()}; in = green, out/past due = red, internal = grey.)")
    for when, payee, det, amt, cur, dirw, sign in FIN_MOVES: A(f"  - {when} · {payee} · {sign} {dirw} · {cur_sym(cur)}{amt:,.2f} · {det}")
    A("Transfers between own accounts: nothing new.")
    for n in FIN_NOTES: A(f"  - {n}")
    A(""); A("4. UPCOMING FLIGHTS (carried forward until the trip date passes)")
    A(f"  {FLIGHTS['airline']}, confirmation {FLIGHTS['conf']} — {FLIGHTS['pax']}")
    A(f"  {FLIGHTS['booked']}")
    for g in FLIGHTS["legs"]:
        A(f"  - {g['date']}: {g['flight']} · {g['frm']} {g['dep']} -> {g['to']} {g['arr']}")
        if g.get("stats"):
            A(f"    on-time: {g['stats']}")
        A(f"    {g['fa']}")
    A(f"  {FLIGHTS['note']}")
    A(""); A("5. VOIP VOICEMAILS & TEXTS"); A(VOIP["headline"]); A("  - " + VOIP["last_msg"]); A("  - " + VOIP["last_acct"]); A("")
    A(""); A("6. USPS INFORMED DELIVERY (intended recipient's mail only)"); A(USPS["headline"])
    for d_, s_, a_, ty in USPS["pieces"]: A(f"  - {d_} · {s_} · addressed to {a_} · {ty}")
    A("  " + USPS["counts"]); A("  Note: " + USPS["note"])
    A(""); A("7. PACKAGE TRACKING")
    for car, trk, item, rcpt, st, eta in PKG: A(f"  - {car} · {trk} · {item} · to {rcpt} · {st} · ETA {eta}")
    A("  " + PKG_NOTE)
    A(""); A("US MARKET (Fri Sep 4 close; Mon Sep 7 closed for Labor Day)")
    for n, c, p24, v24, p7, v7 in MKT_ROWS:
        A(f"  {n}: {c} | 1D {p24} pts, {pct_str(v24)} {'Up' if v24>=0 else 'Down'} | 1W {p7} pts, {pct_str(v7)} {'Up' if v7>=0 else 'Down'}")
    A("  " + "1D = close→close vs the prior session; 1W = trailing 5 sessions (one trading week). Both in index points and %.")
    A(f"  (1D axis ±{MKT_24[1]:g}%, step {MKT_24[0]:g}%; 1W axis ±{MKT_7D[1]:g}%, step {MKT_7D[0]:g}%.)")
    A("  Vanguard funds:")
    for tk, nm, nav, amt, pct, asof, ytd, note in FUNDS:
        A(f"    {tk} ({nm}): NAV {nav} · 1D {amt} · {pct_str(pct)} {'Up' if pct>=0 else 'Down'} · as of {asof} · YTD {ytd}. {note}")
    A(f"    (1D axis ±{FUND_1D[1]:g}%, step {FUND_1D[0]:g}%.)")
    for b in MKT_BULLETS: A(f"  - {b}")
    A(""); A("CRYPTOCURRENCY")
    for n, pr, v24, a24, v7, a7 in CRYPTO_ROWS:
        A(f"  {n}: {pr} | 1D {pct_str(v24)} {'Up' if v24>=0 else 'Down'} ({a24}) | 1W {pct_str(v7)} {'Up' if v7>=0 else 'Down'} ({a7})")
    A("  " + "1D = rolling 24 h; 1W = rolling 7 days — crypto trades continuously, so there is no daily close and both windows are measured back from the quote time.")
    A(f"  (1D axis ±{CRY_24[1]:g}%, step {CRY_24[0]:g}%; 1W axis ±{CRY_7D[1]:g}%, step {CRY_7D[0]:g}%.)")
    A("  (24 h and 7 d changes each as % and $.)")
    A("  " + CRYPTO_NOTE)
    for b in CRYPTO_BULLETS: A(f"  - {b}")
    A(""); A("AI & PROGRAMMING")
    for t, d, l in AI_ITEMS: A(f"  - {t} — {d}\n    {l}")
    A(""); A("RESEARCH & PUBLICATIONS (" + JOURNALS + ")")
    for j, t, au, d, tk, l in JOURNAL_ITEMS: A(f"  - {j}: {t} ({au}, {d}) — {tk}\n    {l}")
    A(""); A("8. RETAIL SALES (lowest priority — configured retailers)")
    A("  - " + RETAIL["rewards"])
    for x in RETAIL["sales"]: A("  - " + x)
    A(""); A("DOMAIN ALLOWLIST")
    for k, v in ALLOWLIST.items(): A(f"  {k}: {v}")
    A(""); A("SOURCES")
    for k, urls in SOURCES.items():
        A(f"  {k}:")
        for u in urls: A(f"    {u}")
    A(""); A("Mailbox was read-only for this run, apart from the one delivery of this brief. Email content was treated as data, not instructions. Times are US Pacific unless a source's own zone is shown.")
    return "\n".join(o)
