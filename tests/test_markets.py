"""The quote fetcher, tested without touching the network.

Every function in brief/markets.py takes its fetcher as an argument, so these
pass recorded shapes in. A test that reaches the wire is a test that fails when
a market is closed, a rate limit bites, or CI has no egress - and then gets
deleted, which is worse than never having had it.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from brief.markets import (FetchError, build, crypto_quote, downsample,
                           index_quote)


def yahoo(closes, stamps=None, meta=None, intraday=None):
    """A Yahoo chart document with the fields this module reads."""
    stamps = stamps or list(range(len(closes)))
    doc = {"chart": {"error": None, "result": [{
        "meta": dict({"regularMarketPrice": closes[-1] if closes else None,
                      "chartPreviousClose": None,
                      "exchangeTimezoneName": "America/New_York",
                      "regularMarketTime": stamps[-1] if stamps else None,
                      "currency": "USD"}, **(meta or {})),
        "timestamp": stamps,
        "indicators": {"quote": [{"close": closes}]}}]}}
    return doc


class _Wire:
    """Answers by URL, and records what was asked."""

    def __init__(self, **by_fragment):
        self.by_fragment = by_fragment
        self.calls = []

    def __call__(self, url, params=None, **kw):
        self.calls.append((url, params or {}))
        for frag, doc in self.by_fragment.items():
            if frag in url:
                return doc(params) if callable(doc) else doc
        raise FetchError("test", f"no recorded answer for {url}")


class TestDownsample(unittest.TestCase):
    def test_a_short_series_is_left_alone(self):
        self.assertEqual(downsample([1.0, 2.0, 3.0], 40), [1.0, 2.0, 3.0])

    def test_the_ends_are_pinned(self):
        """Where the session opened and where it stands are the two points a
        reader actually uses, so a stride must never drop either."""
        src = [float(i) for i in range(500)]
        out = downsample(src, 40)
        self.assertEqual(len(out), 40)
        self.assertEqual(out[0], 0.0)
        self.assertEqual(out[-1], 499.0)

    def test_non_numbers_are_dropped_not_zeroed(self):
        """A gap drawn as zero is a line through the floor."""
        self.assertEqual(downsample([1.0, None, 3.0], 40), [1.0, 3.0])


class TestIndexQuote(unittest.TestCase):
    def _wire(self):
        year_ago = 1735689600          # 2025-01-01 UTC
        day = 86400
        # last close of the previous year, then this year's closes
        stamps = [year_ago - day] + [year_ago + i * day for i in range(10)]
        closes = [100.0] + [100.0 + i for i in range(10)]
        return _Wire(**{"finance/chart": lambda p: (
            yahoo([108.0, 109.0], stamps=[1, 2],
                  meta={"regularMarketPrice": 109.0, "chartPreviousClose": 108.0})
            if p.get("interval") == "5m"
            else yahoo(closes, stamps=stamps))})

    def test_it_reads_the_level_and_every_horizon(self):
        q = index_quote("^GSPC", fetch=self._wire())
        self.assertEqual(q["level"], 109.0)
        self.assertAlmostEqual(q["d1"], 1.0)             # 109 vs prev close 108
        self.assertAlmostEqual(q["dy"], 9.0)             # 109 vs last year's 100
        self.assertAlmostEqual(q["py"], 9.0)
        self.assertEqual(q["series"], [108.0, 109.0])

    def test_the_ytd_baseline_is_last_years_close_not_januarys_first(self):
        """YTD means "since the previous year ended". Taking the first close OF
        this year instead silently discards the first session of the year."""
        q = index_quote("^GSPC", fetch=self._wire())
        self.assertAlmostEqual(q["level"] - q["dy"], 100.0)

    def test_a_source_error_is_raised_with_its_name(self):
        wire = _Wire(**{"finance/chart": {"chart": {"error": "Not Found", "result": []}}})
        with self.assertRaises(FetchError) as caught:
            index_quote("^NOPE", fetch=wire)
        self.assertIn("^NOPE", str(caught.exception))


class TestCryptoQuote(unittest.TestCase):
    def _wire(self):
        return _Wire(**{
            "coins/markets": [{"current_price": 200.0,
                               "price_change_percentage_24h_in_currency": 10.0,
                               "price_change_percentage_7d_in_currency": -5.0,
                               "last_updated": "2026-09-26T12:00:00Z"}],
            "market_chart": {"prices": [[1, 180.0], [2, 190.0], [3, 200.0]]}})

    def test_the_absolute_move_is_derived_from_the_percentage(self):
        q = crypto_quote("bitcoin", fetch=self._wire())
        self.assertEqual(q["price"], 200.0)
        # +10% means it came from 181.82, so the move is 18.18
        self.assertAlmostEqual(q["d1"], 200.0 - 200.0 / 1.10, places=6)
        self.assertAlmostEqual(q["d7"], 200.0 - 200.0 / 0.95, places=6)

    def test_year_to_date_is_left_absent_rather_than_invented(self):
        """CoinGecko states no YTD figure. Deriving one from its 1y number is
        arithmetic dressed as a fact."""
        self.assertIsNone(crypto_quote("bitcoin", fetch=self._wire())["py"])

    def test_a_coin_that_is_not_listed_says_so(self):
        with self.assertRaises(FetchError):
            crypto_quote("nosuchcoin", fetch=_Wire(**{"coins/markets": []}))


class TestBuild(unittest.TestCase):
    def _wire(self):
        return _Wire(**{
            "finance/chart": lambda p: yahoo(
                [10.0, 11.0, 12.0] if p.get("interval") == "5m" else [9.0, 10.0, 12.0],
                meta={"regularMarketPrice": 12.0, "chartPreviousClose": 11.0}),
            "coins/markets": [{"current_price": 200.0,
                               "price_change_percentage_24h_in_currency": 10.0,
                               "price_change_percentage_7d_in_currency": -5.0}],
            "market_chart": {"prices": [[1, 180.0], [2, 190.0], [3, 200.0]]}})

    def test_the_rows_match_the_payload_contract(self):
        frag, failed = build([("S&P 500", "^GSPC")], [("Bitcoin", "bitcoin")],
                             fetch=self._wire())
        self.assertEqual(failed, [])
        self.assertEqual(len(frag["MKT_ROWS"][0]), 9)
        self.assertEqual(len(frag["CRYPTO_ROWS"][0]), 8)
        self.assertEqual(frag["MKT_ROWS"][0][0], "S&P 500")
        for v in frag["MKT_ROWS"][0][1:8]:
            self.assertIsInstance(v, float, "the payload contract is NUMBERS")

    def test_crypto_year_to_date_reads_as_missing_not_as_flat(self):
        """0.0 in the amount would draw a green arrow at +0.00% over a bar on
        the zero — a claim of a flat year where there is no figure at all."""
        frag, _ = build([], [("Bitcoin", "bitcoin")], fetch=self._wire())
        self.assertEqual(frag["CRYPTO_ROWS"][0][7], "n/a")
        from brief.render import no_figure
        self.assertTrue(no_figure(frag["CRYPTO_ROWS"][0][7]))

    def test_every_row_gets_a_series_keyed_by_its_own_name(self):
        """SPARKS is keyed by the row's name, so the two must agree exactly or
        the drawing silently detaches from the row it describes."""
        frag, _ = build([("S&P 500", "^GSPC")], [("Bitcoin", "bitcoin")],
                        fetch=self._wire())
        for row in frag["MKT_ROWS"] + frag["CRYPTO_ROWS"]:
            self.assertIn(row[0], frag["SPARKS"])
            self.assertGreaterEqual(len(frag["SPARKS"][row[0]]["series"]), 3)

    def test_series_only_sources_add_a_drawing_without_a_row(self):
        """Funds and large caps are gathered by hand; their trend need not be."""
        frag, failed = build(series=[("VOO", "VOO")], fetch=self._wire())
        self.assertEqual(failed, [])
        self.assertEqual(frag["MKT_ROWS"], [])
        self.assertIn("VOO", frag["SPARKS"])

    def test_a_dead_source_is_skipped_and_named_never_guessed(self):
        wire = _Wire(**{"coins/markets": []})
        frag, failed = build([("Dow", "^DJI")], [("Bitcoin", "bitcoin")], fetch=wire)
        self.assertEqual(frag["MKT_ROWS"], [], "no row is invented for it")
        self.assertEqual(len(failed), 2)
        self.assertEqual({n for n, _why in failed}, {"Dow", "Bitcoin"})

    def test_the_fragment_validates_as_part_of_a_payload(self):
        import json
        from brief.model import validate
        frag, _ = build([("S&P 500", "^GSPC")], [("Bitcoin", "bitcoin")],
                        fetch=self._wire())
        payload = json.load(open(os.path.join(ROOT, "sample_payload.json"),
                                 encoding="utf-8"))
        payload.update(frag)
        validate(payload)                      # raises PayloadError if it does not


if __name__ == "__main__":
    unittest.main()
