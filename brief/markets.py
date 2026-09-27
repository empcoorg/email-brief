"""Index and crypto quotes, fetched rather than read off a page.

The run used to gather this section by hand: roughly a hundred web searches and
page fetches to find five index levels, their 1D/1W/YTD moves, the same for
crypto, and an intraday series for each trend drawing. Every number arrived
through a model reading a rendered page, which is expensive, slow, and wrong in
a way nothing downstream can detect - a misread digit validates perfectly.

It is also what quietly dropped the trend drawings. Gathering an intraday
series by hand is the most tedious part of the whole run, `SPARKS` is an
OPTIONAL payload key, and on 2026-09-26 a brief shipped with the key missing
entirely and every TREND cell drawing an em dash. A number that is expensive to
fetch is a number that eventually does not get fetched.

So this module fetches them. Two JSON endpoints, both already on the egress
allowlist, both returning the quote AND the series in one call:

    equities/indexes  query1.finance.yahoo.com/v8/finance/chart/<symbol>
    crypto            api.coingecko.com/api/v3/...

Nothing here renders, formats or decides what goes in the brief. It returns the
payload fragment - MKT_ROWS, CRYPTO_ROWS and SPARKS - and the run merges it.

NO NETWORK IS REACHED BY IMPORTING THIS. Every function takes its fetcher as an
argument, defaulting to the real one, so the tests pass recorded payloads in and
never touch the wire.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

# Long enough for a cold CDN, short enough that a dead endpoint cannot hang a
# scheduled run: the brief is due at a fixed time and a missing table beats a
# late brief.
TIMEOUT_S = 12
RETRIES = 3

# What to wait after an HTTP 429 before asking again.
RATE_LIMIT_WAIT_S = 8

# Spacing between calls to one host, so a run does not earn its own 429.
PACE_S = 1.2

UA = "email-brief (+https://github.com/empcoorg/email-brief)"

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
CG_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
CG_CHART = "https://api.coingecko.com/api/v3/coins/{coin}/market_chart"

# How many intraday points a trend drawing gets. The renderer needs at least 3
# and the drawing stops being readable long before it needs hundreds, so a
# full session at 5-minute bars is downsampled to this.
SPARK_POINTS = 40


class FetchError(RuntimeError):
    """A source could not be read. Carries the source name for the report."""

    def __init__(self, source, detail):
        super().__init__(f"{source}: {detail}")
        self.source = source
        self.detail = detail


def fetch_json(url, params=None, timeout=TIMEOUT_S, retries=RETRIES):
    """GET a JSON document. Retries once on a transient failure, then gives up.

    Gives up rather than looping: a scheduled run has a deadline, and a source
    that is down at 10:05 is usually still down at 10:06.
    """
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                return json.loads(fh.read().decode("utf-8"))
        except Exception as ex:                      # noqa: BLE001 - reported, not swallowed
            last = ex
            if attempt + 1 < retries:
                # 429 is not a transient blip, it is a rate limit with a clock
                # on it. CoinGecko's free tier allows a handful of calls a
                # minute and a scheduled run asks for several coins at once, so
                # backing off properly is the difference between a crypto table
                # and an apology.
                rate_limited = getattr(ex, "code", None) == 429
                time.sleep(RATE_LIMIT_WAIT_S if rate_limited else 1.5)
    raise FetchError(urllib.parse.urlparse(url).netloc, f"{type(last).__name__}: {last}")


def _pace(fetch):
    """Space out calls to one host — but only real ones.

    Pacing exists so a run does not earn its own 429. A test passing a recorded
    fetcher has no host to be polite to, and a suite that sleeps is a suite
    people stop running.
    """
    if fetch is fetch_json:
        time.sleep(PACE_S)


def _pct(now, then):
    """Percent change, or None when the baseline cannot support one."""
    if then in (None, 0) or now is None:
        return None
    return (now - then) / then * 100.0


def downsample(values, n=SPARK_POINTS):
    """Thin a series to at most n points, keeping the first and the last.

    The ends carry the meaning - where the session opened and where it is now -
    so they are pinned rather than left to fall where a stride happens to land.
    """
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) <= n:
        return vals
    step = (len(vals) - 1) / (n - 1)
    out = [vals[int(round(i * step))] for i in range(n)]
    out[-1] = vals[-1]
    return out


def _closes(result):
    """(timestamps, closes) out of a Yahoo chart result, gaps dropped.

    Yahoo emits null for a bar with no trade. Carrying those into a series
    draws a line through zero; dropping them draws the session.
    """
    stamps = result.get("timestamp") or []
    quote = (result.get("indicators") or {}).get("quote") or [{}]
    closes = (quote[0] or {}).get("close") or []
    pairs = [(t, c) for t, c in zip(stamps, closes) if isinstance(c, (int, float))]
    return [t for t, _ in pairs], [c for _, c in pairs]


def index_quote(symbol, fetch=fetch_json):
    """One index or equity: the level, its 1D/1W/YTD moves, and today's series.

    Two calls, because they answer different questions: a year of daily closes
    says where the year started and what last week did, and today's 5-minute
    bars are the only thing that can draw a trend for today.
    """
    intraday = fetch(YAHOO_CHART.format(symbol=urllib.parse.quote(symbol)),
                     {"range": "1d", "interval": "5m"})
    daily = fetch(YAHOO_CHART.format(symbol=urllib.parse.quote(symbol)),
                  {"range": "1y", "interval": "1d"})

    def result(doc, which):
        chart = (doc or {}).get("chart") or {}
        if chart.get("error"):
            raise FetchError(symbol, f"{which}: {chart['error']}")
        res = chart.get("result") or []
        if not res:
            raise FetchError(symbol, f"{which}: no result")
        return res[0]

    intr, day = result(intraday, "intraday"), result(daily, "daily")
    meta = intr.get("meta") or {}
    _, series = _closes(intr)
    stamps, closes = _closes(day)

    level = meta.get("regularMarketPrice")
    if level is None:
        level = series[-1] if series else (closes[-1] if closes else None)
    if level is None:
        raise FetchError(symbol, "no price in either range")

    prev = meta.get("chartPreviousClose")
    if prev is None and len(closes) >= 2:
        prev = closes[-2]
    week = closes[-6] if len(closes) >= 6 else (closes[0] if closes else None)

    year = time.gmtime(stamps[-1] if stamps else time.time()).tm_year
    ytd_base = None
    for t, c in zip(stamps, closes):
        if time.gmtime(t).tm_year == year:
            break
        ytd_base = c                       # the last close OF THE PREVIOUS YEAR

    return {
        "level": level,
        "d1": (level - prev) if prev else None, "p1": _pct(level, prev),
        "d7": (level - week) if week else None, "p7": _pct(level, week),
        "dy": (level - ytd_base) if ytd_base else None, "py": _pct(level, ytd_base),
        "series": downsample(series),
        "tz": meta.get("exchangeTimezoneName") or "",
        "stamp": meta.get("regularMarketTime"),
        "currency": meta.get("currency") or "USD",
    }


def crypto_quote(coin_id, fetch=fetch_json):
    """One coin: price, 24h/7d/YTD moves, and a 24-hour series."""
    rows = fetch(CG_MARKETS, {"vs_currency": "usd", "ids": coin_id,
                              "price_change_percentage": "24h,7d,1y"})
    if not rows:
        raise FetchError(coin_id, "not listed")
    row = rows[0]
    _pace(fetch)
    chart = fetch(CG_CHART.format(coin=urllib.parse.quote(coin_id)),
                  {"vs_currency": "usd", "days": "1"})
    series = downsample([p[1] for p in (chart.get("prices") or [])
                         if isinstance(p, (list, tuple)) and len(p) == 2])
    price = row.get("current_price")
    p1 = row.get("price_change_percentage_24h_in_currency")
    p7 = row.get("price_change_percentage_7d_in_currency")
    # CoinGecko has no year-to-date field. Deriving one from the 1y figure
    # would be arithmetic dressed as a fact, so it is left absent and the
    # renderer shows it as missing - which, since 2026-09-26, it does honestly.
    return {"price": price,
            "p1": p1, "d1": _back(price, p1),
            "p7": p7, "d7": _back(price, p7),
            "py": None, "dy": None,
            "series": series,
            "stamp": row.get("last_updated") or ""}


def _back(now, pct):
    """The absolute move implied by a percentage and the current level."""
    if now is None or pct is None:
        return None
    before = now / (1 + pct / 100.0)
    return now - before


def _tz_clock(epoch, tzname):
    """"1:04 PM EDT" in the exchange's own zone, or "" when it cannot be said."""
    if not epoch:
        return ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime.fromtimestamp(epoch, ZoneInfo(tzname)) if tzname else None
        return dt.strftime("%-I:%M %p %Z") if dt else ""
    except Exception:                                # noqa: BLE001 - a stamp is optional
        return ""


def _window(series_len, quote_stamp, tzname):
    """The label under a trend drawing: where the session started and ended."""
    end = _tz_clock(quote_stamp, tzname)
    return f"today → {end}" if end else "today"


def build(indexes=(), cryptos=(), series=(), fetch=fetch_json):
    """The payload fragment: MKT_ROWS, CRYPTO_ROWS and SPARKS.

    `indexes` and `cryptos` are (display name, source id) pairs. A source that
    cannot be read is REPORTED AND SKIPPED, never guessed at: the returned
    "failed" list is what the run puts in front of the owner.

    `series` is for tables this module does not build - funds and large caps,
    whose rows carry names and notes only the run knows. It fetches JUST the
    trend series for those rows, keyed by the name they use in the payload, so
    a table gathered by hand still gets its drawing.
    """
    out = {"MKT_ROWS": [], "CRYPTO_ROWS": [], "SPARKS": {}}
    failed = []
    for name, symbol in indexes:
        try:
            q = index_quote(symbol, fetch=fetch)
        except FetchError as ex:
            failed.append((name, str(ex)))
            continue
        out["MKT_ROWS"].append([
            name, _r(q["level"]),
            _r(q["d1"]), _r(q["p1"]), _r(q["d7"]), _r(q["p7"]),
            _r(q["dy"]), _r(q["py"]),
            _tz_clock(q["stamp"], q["tz"]),
        ])
        if len(q["series"]) >= 3:
            out["SPARKS"][name] = {"series": q["series"],
                                   "window": _window(len(q["series"]), q["stamp"], q["tz"])}
    for n, (name, coin) in enumerate(cryptos):
        if n:
            _pace(fetch)
        try:
            q = crypto_quote(coin, fetch=fetch)
        except FetchError as ex:
            failed.append((name, str(ex)))
            continue
        # CoinGecko states no year-to-date figure. "n/a" in the AMOUNT is what
        # the renderer reads as "no figure" - muted, no arrow, no bar. A 0.0
        # here would draw a flat year, which is a claim, not a gap.
        out["CRYPTO_ROWS"].append([
            name, _r(q["price"]),
            _r(q["p1"]), _r(q["d1"]), _r(q["p7"]), _r(q["d7"]),
            0.0, "n/a",
        ])
        if len(q["series"]) >= 3:
            out["SPARKS"][name] = {"series": q["series"], "window": "last 24 h"}
    for name, symbol in series:
        try:
            q = index_quote(symbol, fetch=fetch)
        except FetchError as ex:
            failed.append((name, str(ex)))
            continue
        if len(q["series"]) >= 3:
            out["SPARKS"][name] = {"series": q["series"],
                                   "window": _window(len(q["series"]), q["stamp"], q["tz"])}
        else:
            failed.append((name, "fewer than 3 points in the session"))
    return out, failed


def _r(v, places=2):
    """A number rounded for the payload, or 0.0 when the source had none.

    The payload contract is NUMBERS, never formatted strings - the renderer
    does every bit of the formatting.
    """
    return 0.0 if v is None else round(float(v), places)
