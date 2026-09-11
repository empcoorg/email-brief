"""Axis arithmetic for every bar in the brief.

Pure functions, no HTML and no globals — this is the part that used to live as
prose ("pick a scale the day's values span", "round to even numbers") and got
re-interpreted differently on every run. It is now arithmetic with tests.

The contract, in one place:
  * Every bar diverges from a CENTRED ZERO. Negative runs left, positive right.
  * Axis breaks are EVEN round numbers (1 / 2 / 2.5 / 5 x 10^n), never a raw
    data value. $2,450 of movement yields $1,000 steps to a $3,000 top.
  * The axis is symmetric: the same top each side of zero.
  * Ticks sit at every step; only -top, 0 and +top are labelled.
"""
import math

NICE = (1.0, 2.0, 2.5, 5.0, 10.0)


def nice_step_top(vmax, target=3):
    """Round a data maximum out to an even axis.

    Returns (step, top): `step` is a 1/2/2.5/5 x 10^n value at least vmax/target,
    and `top` is the smallest whole number of steps that covers vmax.

    >>> nice_step_top(2450)
    (1000.0, 3000.0)
    >>> nice_step_top(0.84)
    (0.5, 1.0)
    """
    if vmax <= 0:
        return 1.0, 1.0
    raw = vmax / target
    exp = math.floor(math.log10(raw))
    base = 10.0 ** exp
    step = next(m * base for m in NICE if m * base >= raw - 1e-9)
    return step, math.ceil(vmax / step - 1e-9) * step


def pct_axis(values, target=3):
    """Even (step, top) for a signed percentage column."""
    return nice_step_top(max((abs(v) for v in values), default=0) or 1.0, target)


def money_axis(amounts, target=3):
    """Even axis for money movements. Falls back to symmetric log decades when
    the values span more than ~2 orders of magnitude, where a linear scale would
    leave every small item an invisible sliver.

    Returns ("linear", step, top) or ("log", decade_min, decade_max).
    """
    positive = [a for a in amounts if a > 0]
    if not positive:
        return ("linear", 1.0, 1.0)
    mx, mn = max(positive), min(positive)
    if mx / mn > 100:
        return ("log", 10.0 ** math.floor(math.log10(mn)), 10.0 ** math.ceil(math.log10(mx)))
    return ("linear",) + nice_step_top(mx, target)


def steps_per_side(axis):
    """How many even steps sit between the centre line and either end."""
    mode, a, b = axis if len(axis) == 3 else ("linear",) + axis
    return int(round(b / a)) if mode == "linear" else int(round(math.log10(b / a)))


def fraction(value, axis):
    """|value| as a fraction 0..1 of one half-track, honouring log mode."""
    mode, a, b = axis if len(axis) == 3 else ("linear",) + axis
    if mode == "linear":
        return min(abs(value) / b, 1.0) if b else 0.0
    lo, hi = math.log10(a), math.log10(b)
    return max(0.0, min(1.0, (math.log10(max(abs(value), a)) - lo) / (hi - lo)))


def tick_positions(axis):
    """Left offsets, in percent of the full track, for every even step."""
    n = steps_per_side(axis)
    return [50 + k * 50 / n for k in range(-n, n + 1)]


def pct_tick(v):
    """Even percentage label: -3% / 0 / +3%."""
    return "0" if v == 0 else f"{v:+g}".replace("-", "−") + "%"


def pct_labels(axis):
    """The three labels a percentage axis shows: (-top, 0, +top)."""
    top = axis[1]
    return (pct_tick(-top), "0", pct_tick(top))


def money_labels(axis, unit="USD"):
    """The three labels a money axis shows: (-top, 0, +top).

    The unit rides on the right-hand label. Every money bar in the brief is
    plotted in ONE currency, so the axis has to say which: a row reading
    "MX$10,200.00" against an unlabelled "$100k" scale invites the reader to
    assume the bar is 13,600 of whatever the axis counts.
    """
    top = axis[2] if len(axis) == 3 else axis[1]
    right = money_tick(top)
    return (money_tick(-top), "0", f"{right} {unit}" if unit else right)


def money_tick(v):
    """Compact, even money label: 0 / $1k / -$3k. Never a raw data value."""
    a = abs(v)
    if a == 0:
        return "0"
    s = f"{a / 1000:g}k" if a >= 1000 else f"{a:g}"
    return ("−$" if v < 0 else "$") + s
