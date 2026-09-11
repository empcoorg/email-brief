"""Unit tests for the pieces that used to be prose.

Axis arithmetic, payload validation and the CLI were all previously described
in the Routine prompt in words ("pick an even scale", "state the amount as a
number") and re-interpreted on every run. They are code now, so they get tests.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from brief.axes import (fraction, money_axis, money_tick, nice_step_top, pct_axis,
                        pct_tick, steps_per_side, tick_positions)
from brief.model import PayloadError, load, validate

SAMPLE = os.path.join(ROOT, "sample_payload.json")


class TestAxisArithmetic(unittest.TestCase):
    def test_breaks_are_even_never_raw_data(self):
        """The bug this replaces: an axis labelled $1,225 because that happened
        to be half the largest movement."""
        for vmax, expect in [(2450, (1000.0, 3000.0)),   # the real case
                             (0.84, (0.5, 1.0)),
                             (2.1, (1.0, 3.0)),
                             (1.8, (1.0, 2.0)),
                             (4.1, (2.0, 6.0)),
                             (97, (50.0, 100.0)),
                             (101, (50.0, 150.0))]:
            self.assertEqual(nice_step_top(vmax), expect, f"nice_step_top({vmax})")

    def test_step_is_always_a_nice_number(self):
        from brief.axes import NICE
        for v in (0.003, 0.07, 1, 7, 42, 386, 2450, 99999):
            step, top = nice_step_top(v)
            mant = step / (10 ** len(str(int(step))) if step >= 1 else 1)
            self.assertTrue(any(abs(step / (10.0 ** k) - m) < 1e-9
                                for m in NICE for k in range(-6, 7)),
                            f"step {step} for {v} is not a 1/2/2.5/5 x 10^n value")

    def test_top_always_covers_the_data(self):
        for v in (0.001, 0.9, 1.0, 2.4999, 2.5, 3.0, 2450, 7777):
            step, top = nice_step_top(v)
            self.assertGreaterEqual(top + 1e-9, v, f"axis top {top} does not cover {v}")
            self.assertAlmostEqual(top / step, round(top / step), places=6,
                                   msg="top must be a whole number of steps")

    def test_zero_and_negative_inputs_do_not_explode(self):
        self.assertEqual(nice_step_top(0), (1.0, 1.0))
        self.assertEqual(nice_step_top(-5), (1.0, 1.0))
        # an empty or all-zero column still gets a sane even axis (+-1%, 0.5 steps)
        self.assertEqual(pct_axis([]), (0.5, 1.0))
        self.assertEqual(pct_axis([0, 0]), (0.5, 1.0))

    def test_money_axis_switches_to_log_on_a_wide_spread(self):
        self.assertEqual(money_axis([2450, 500, 84.2])[0], "linear")
        mode, lo, hi = money_axis([5000, 12])
        self.assertEqual(mode, "log")
        self.assertLessEqual(lo, 12); self.assertGreaterEqual(hi, 5000)

    def test_fraction_is_bounded_and_proportional(self):
        ax = ("linear", 1000.0, 3000.0)
        self.assertAlmostEqual(fraction(3000, ax), 1.0)
        self.assertAlmostEqual(fraction(1500, ax), 0.5)
        self.assertAlmostEqual(fraction(0, ax), 0.0)
        self.assertAlmostEqual(fraction(99999, ax), 1.0, msg="must clamp, not overflow the track")
        self.assertAlmostEqual(fraction(-1500, ax), 0.5, msg="sign is carried by the side, not the length")

    def test_ticks_are_symmetric_about_the_centre(self):
        for ax in (("linear", 1000.0, 3000.0), ("linear", 0.5, 1.0), ("log", 10.0, 10000.0)):
            pos = tick_positions(ax)
            self.assertIn(50.0, pos, "there must be a tick at zero")
            self.assertAlmostEqual(pos[0], 0.0); self.assertAlmostEqual(pos[-1], 100.0)
            self.assertEqual(len(pos), 2 * steps_per_side(ax) + 1)
            for a, b in zip(pos, reversed(pos)):
                self.assertAlmostEqual(a, 100 - b, msg=f"ticks not symmetric: {pos}")

    def test_labels_carry_units_and_compact_thousands(self):
        self.assertEqual(money_tick(0), "0")
        self.assertEqual(money_tick(3000), "$3k")
        self.assertEqual(money_tick(-3000), "−$3k")
        self.assertEqual(money_tick(500), "$500")
        self.assertEqual(pct_tick(0), "0")
        self.assertEqual(pct_tick(1.0), "+1%")
        self.assertEqual(pct_tick(-2.5), "−2.5%")


class TestPayloadValidation(unittest.TestCase):
    def setUp(self):
        self.good = json.load(open(SAMPLE, encoding="utf-8"))

    def test_sample_payload_is_valid(self):
        self.assertIs(validate(self.good), self.good)

    def test_missing_key_names_the_key(self):
        bad = copy.deepcopy(self.good); del bad["MKT_ROWS"]
        with self.assertRaises(PayloadError) as cm:
            validate(bad)
        self.assertIn("MKT_ROWS", str(cm.exception))

    def test_wrong_row_arity_names_the_row(self):
        bad = copy.deepcopy(self.good); bad["PKG"][0] = bad["PKG"][0][:3]
        with self.assertRaises(PayloadError) as cm:
            validate(bad)
        self.assertIn("row 0", str(cm.exception))
        self.assertIn("expected 6", str(cm.exception))

    def test_formatted_money_string_is_rejected(self):
        """A bar cannot be drawn from '$2,450.00' — catching it here is the
        difference between a loud failure and a silently wrong chart."""
        bad = copy.deepcopy(self.good); bad["FIN_MOVES"][0][3] = "$2,450.00"
        with self.assertRaises(PayloadError) as cm:
            validate(bad)
        self.assertIn("must be a number", str(cm.exception))

    def test_formatted_percentage_is_rejected(self):
        for key, idx in (("MKT_ROWS", 3), ("CRYPTO_ROWS", 2)):
            bad = copy.deepcopy(self.good); bad[key][0][idx] = "+0.60%"
            with self.assertRaises(PayloadError) as cm:
                validate(bad)
            self.assertIn("must be a number", str(cm.exception))

    def test_flight_leg_missing_field_is_named(self):
        bad = copy.deepcopy(self.good); del bad["FLIGHTS"]["legs"][0]["fa"]
        with self.assertRaises(PayloadError) as cm:
            validate(bad)
        self.assertIn("leg 0", str(cm.exception)); self.assertIn("fa", str(cm.exception))

    def test_bad_json_reports_the_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not json")
        with self.assertRaises(PayloadError) as cm:
            load(fh.name)
        self.assertIn("not valid JSON", str(cm.exception))


class TestCli(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, "-m", "brief", *args],
                              cwd=ROOT, capture_output=True, text=True)

    def test_validate_succeeds_on_the_sample(self):
        r = self._run("validate", "sample_payload.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("valid", r.stdout)

    def test_validate_fails_loudly_and_exits_nonzero(self):
        bad = json.load(open(SAMPLE, encoding="utf-8")); del bad["FUNDS"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(bad, fh)
        r = self._run("validate", fh.name)
        self.assertEqual(r.returncode, 2)
        self.assertIn("FUNDS", r.stderr)

    def test_render_writes_three_files_and_reports_the_budget(self):
        td = tempfile.mkdtemp()
        r = self._run("render", "sample_payload.json", "--out-dir", td, "--date", "2026-09-07")
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in ("morning-brief-2026-09-07.html", "email.html", "email.txt"):
            self.assertTrue(os.path.isfile(os.path.join(td, name)), f"{name} not written")
        self.assertIn("send budget", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
