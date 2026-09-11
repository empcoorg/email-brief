"""Unit tests for the pieces that used to be prose.

Axis arithmetic, payload validation and the CLI were all previously described
in the Routine prompt in words ("pick an even scale", "state the amount as a
number") and re-interpreted on every run. They are code now, so they get tests.
"""
import copy
import json
import os
import re
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

    def test_ticks_are_symmetric_about_the_center(self):
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


class TestEveningSignificance(unittest.TestCase):
    """The evening send happens only when something earned it.

    This was going to be a sentence in the prompt ("only if there are important
    updates"). A second email that says nothing teaches the reader to ignore the
    sender, so the bar is a rule with tests rather than a judgement call made
    fresh each evening.
    """

    def setUp(self):
        from brief.significance import is_significant, reasons
        self.is_significant, self.reasons = is_significant, reasons
        self.quiet = json.load(open(SAMPLE, encoding="utf-8"))
        for key in ("ACTIONS", "HIPRI", "FIN_MOVES", "JOBS_STATUS", "PKG"):
            self.quiet[key] = []
        self.quiet["USPS"]["pieces"] = []
        self.quiet["VOIP"]["messages"] = []
        self.quiet["FLIGHTS"]["legs"] = []

    def test_a_quiet_window_is_skipped(self):
        self.assertFalse(self.is_significant(self.quiet))
        self.assertEqual(self.reasons(self.quiet), [])

    def test_urgent_action_or_high_priority_sends(self):
        for key in ("ACTIONS", "HIPRI"):
            for sev in ("neg", "warn"):
                p = copy.deepcopy(self.quiet)
                p[key] = [[sev, "Something", ["detail"] if key == "HIPRI" else "detail"]]
                self.assertTrue(self.is_significant(p), f"{key} [{sev}] must send")

    def test_informational_severities_do_not_send(self):
        for sev in ("info", "ok"):
            p = copy.deepcopy(self.quiet)
            p["ACTIONS"] = [[sev, "FYI", "detail"]]
            self.assertFalse(self.is_significant(p), f"[{sev}] must not send")

    def test_past_due_always_sends(self):
        p = copy.deepcopy(self.quiet)
        p["FIN_MOVES"] = [["t", "Utility", "d", 12.0, "USD", 12.0, "Past due", "−"]]
        self.assertTrue(self.is_significant(p), "a past-due bill sends at any size")

    def test_money_threshold(self):
        from brief.significance import MATERIAL_USD
        for usd, expect in ((MATERIAL_USD - 0.01, False), (MATERIAL_USD, True),
                            (5000.0, True)):
            p = copy.deepcopy(self.quiet)
            p["FIN_MOVES"] = [["t", "Someone", "d", usd, "USD", usd, "In", "+"]]
            self.assertEqual(self.is_significant(p), expect, f"${usd}")

    def test_foreign_charge_judged_on_its_usd_value(self):
        """10,000 MXN is ~$540 — material. The raw number must not decide it."""
        p = copy.deepcopy(self.quiet)
        p["FIN_MOVES"] = [["t", "Shop", "d", 10000.0, "MXN", 540.0, "Out", "−"]]
        self.assertTrue(self.is_significant(p))
        p["FIN_MOVES"] = [["t", "Shop", "d", 10000.0, "MXN", 54.0, "Out", "−"]]
        self.assertFalse(self.is_significant(p), "a small charge in a big-number currency")

    def test_status_changes_and_events_send(self):
        cases = [("JOBS_STATUS", [["Acme", "offer", "detail"]]),
                 ("PKG", [["UPS", "1Z", "item", "me", "Delivered 4:02 PM", "today"]])]
        for key, rows in cases:
            p = copy.deepcopy(self.quiet); p[key] = rows
            self.assertTrue(self.is_significant(p), key)

    def test_routine_shipment_progress_does_not_send(self):
        p = copy.deepcopy(self.quiet)
        p["PKG"] = [["UPS", "1Z", "item", "me", "In transit", "Fri"]]
        self.assertFalse(self.is_significant(p), "ordinary transit is not news")

    def test_cli_exit_codes(self):
        import subprocess, sys, tempfile
        for payload_obj, expect in ((json.load(open(SAMPLE, encoding="utf-8")), 0),
                                    (self.quiet, 3)):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                json.dump(payload_obj, fh)
            r = subprocess.run([sys.executable, "-m", "brief", "significant", fh.name],
                               cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, expect, r.stdout + r.stderr)


class TestAttachmentCeiling(unittest.TestCase):
    """The send path truncates an oversized attachment SILENTLY — it ships half
    a JPEG with grey below and reports success. So the size is checked before
    sending rather than discovered by reading the message back."""

    def setUp(self):
        from brief import attachments
        self.a = attachments

    def test_base64_length_arithmetic(self):
        self.assertEqual(self.a.b64_chars(3), 4)
        self.assertEqual(self.a.b64_chars(15_000), 20_000)
        self.assertEqual(self.a.b64_chars(0), 0)
        # never under-report: a partial group still costs a full quad
        self.assertEqual(self.a.b64_chars(1), 4)
        self.assertEqual(self.a.b64_chars(4), 8)

    def test_max_bytes_round_trips_under_the_limit(self):
        for limit in (self.a.SAFE_B64_CHARS, self.a.CEILING_B64_CHARS, 4000):
            n = self.a.max_bytes(limit)
            self.assertLessEqual(self.a.b64_chars(n), limit, f"limit {limit}")
            self.assertGreater(self.a.b64_chars(n + 3), limit, "should be the largest that fits")

    def test_verdicts_at_the_boundaries(self):
        safe = self.a.max_bytes()
        self.assertTrue(self.a.fits(safe))
        self.assertFalse(self.a.fits(safe + 3))
        # past the real ceiling the message must say so explicitly
        over = self.a.max_bytes(self.a.CEILING_B64_CHARS) + 3
        ok, _chars, msg = self.a.check(over)
        self.assertFalse(ok)
        self.assertIn("truncation ceiling", msg)
        self.assertIn("WILL ship half an image", msg)

    def test_verify_sent_detects_truncation(self):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(b"x" * 10_000)
        ok, msg = self.a.verify_sent(fh.name, 10_000)
        self.assertTrue(ok); self.assertIn("intact", msg)
        ok, msg = self.a.verify_sent(fh.name, 5_000)
        self.assertFalse(ok)
        self.assertIn("TRUNCATED", msg)
        self.assertIn("Do not resend", msg, "the one-send rule still stands")

    def test_cli_reports_and_exits(self):
        import subprocess, sys, tempfile
        small = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        small.write(b"x" * 9_000); small.close()
        big = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        big.write(b"x" * 40_000); big.close()

        r = subprocess.run([sys.executable, "-m", "brief", "attachment", small.name],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("OK", r.stdout)

        r = subprocess.run([sys.executable, "-m", "brief", "attachment", small.name, big.name],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 4, "an oversized attachment must fail the command")
        self.assertIn("OVER", r.stdout)
        self.assertIn("truncated", r.stderr)

    def test_cli_reports_a_missing_file_without_crashing(self):
        import subprocess, sys
        r = subprocess.run([sys.executable, "-m", "brief", "attachment", "/nope/missing.jpg"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 4)
        self.assertIn("missing.jpg", r.stderr)


class TestSpecCoversWhatTheRendererReads(unittest.TestCase):
    """The payload SPEC is advertised to the run as THE contract. It was not:
    render.py read MAST["revised"] and VOIP["last_msg"]/["last_acct"], none of
    which SPEC required, so a payload that validated still crashed with KeyError
    and had to be patched by hand mid-run.

    Deriving the requirement from the source means the contract cannot drift
    from the code again without this failing.
    """

    SOURCE = open(os.path.join(ROOT, "brief", "render.py"), encoding="utf-8").read()

    def _keys_read(self, name):
        """Keys render.py reads off a payload dict, by subscript or .get()."""
        subs = set(re.findall(name + r'\["(\w+)"\]', self.SOURCE))
        gets = set(re.findall(name + r'\.get\("(\w+)"', self.SOURCE))
        return subs | gets

    def test_every_key_the_renderer_reads_is_required(self):
        from brief.model import SPEC
        for name in ("MAST", "VOIP", "USPS", "RETAIL", "FLIGHTS"):
            required = set(SPEC[name][1])
            read = self._keys_read(name)
            # .get() with a default is an optional read, so only subscripts are
            # strictly required; treat both as required unless defaulted
            optional = set(re.findall(name + r'\.get\("(\w+)",', self.SOURCE))
            missing = read - optional - required
            self.assertEqual(missing, set(),
                             f"{name}: render.py reads {sorted(missing)} but SPEC does not "
                             "require it — a valid payload would crash")

    def test_no_required_key_is_unused(self):
        """A required key the renderer never reads is a tax on every run."""
        from brief.model import SPEC
        for name in ("MAST", "VOIP", "RETAIL"):
            required = set(SPEC[name][1])
            unused = required - self._keys_read(name)
            self.assertEqual(unused, set(),
                             f"{name}: SPEC requires {sorted(unused)} but nothing reads it")

    def test_the_sample_payload_satisfies_the_derived_requirement(self):
        payload = json.load(open(SAMPLE, encoding="utf-8"))
        for name in ("MAST", "VOIP", "USPS", "RETAIL"):
            for key in self._keys_read(name):
                if re.search(name + r'\.get\("' + key + r'",', self.SOURCE):
                    continue
                self.assertIn(key, payload[name], f"sample payload {name} lacks {key!r}")
