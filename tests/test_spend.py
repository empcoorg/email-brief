"""AI billing, year to date: carried forward, never back-dated, reset on 1 January.

The total lives in the brief, not in the repo and not in the mailbox: each brief
prints a machine-readable line and the next run reads it back. That makes three
ways to get it wrong - losing the total, double-counting a charge, or carrying
last year's figure into January - so each has a test. Stdlib unittest.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from brief import render_all  # noqa: E402
from brief.model import PayloadError, validate  # noqa: E402
from brief.spend import accumulate, format_line, parse_line, rows  # noqa: E402

SAMPLE = os.path.join(ROOT, "sample_payload.json")
BASIS = {"Acme AI": 412.50}


def payload(**overrides):
    with open(SAMPLE, encoding="utf-8") as fh:
        p = json.load(fh)
    p.update(overrides)
    return p


class TestTheCarriedLine(unittest.TestCase):
    def test_round_trip(self):
        totals = {"Acme AI": 412.50, "Northwind AI": 1250.5}
        self.assertEqual(parse_line(format_line("2026", totals)), ("2026", totals))

    def test_it_is_found_indented_in_a_brief_and_survives_quoting(self):
        for line in ("  AI spend YTD 2026: Acme AI $12.00",
                     "> AI spend YTD 2026: Acme AI $12.00"):
            self.assertEqual(parse_line(line), ("2026", {"Acme AI": 12.0}), line)

    def test_the_newest_line_wins(self):
        """A brief that quotes an older one must not resurrect the older total."""
        text = ("AI spend YTD 2026: Acme AI $10.00\nsomething\n"
                "AI spend YTD 2026: Acme AI $30.00\n")
        self.assertEqual(parse_line(text)[1], {"Acme AI": 30.0})

    def test_thousands_and_a_service_name_with_spaces(self):
        self.assertEqual(parse_line("AI spend YTD 2026: Cascade Speech API $1,250.50")[1],
                         {"Cascade Speech API": 1250.5})

    def test_no_line_is_not_an_error_and_a_damaged_one_is(self):
        self.assertEqual(parse_line("a brief with no such line"), (None, {}))
        with self.assertRaises(ValueError):
            parse_line("AI spend YTD 2026: Acme AI 12.00")      # no $, so no amount

    def test_an_empty_year_says_so_and_reads_back_empty(self):
        self.assertEqual(format_line("2026", {}), "AI spend YTD 2026: nothing yet")
        self.assertEqual(parse_line(format_line("2026", {})), ("2026", {}))


class TestAccumulating(unittest.TestCase):
    def test_the_first_run_starts_at_zero_and_counts_what_arrived(self):
        year, totals, carried = accumulate("", [("Acme AI", 20.0)], "2026-09-15")
        self.assertEqual((year, totals, carried), ("2026", {"Acme AI": 20.0}, None))

    def test_the_next_run_carries_the_total_and_adds_only_new_charges(self):
        first = format_line("2026", {"Acme AI": 20.0})
        _, totals, carried = accumulate(first, [("Acme AI", 5.5), ("Northwind AI", 9.0)],
                                        "2026-09-16")
        self.assertEqual(totals, {"Acme AI": 25.5, "Northwind AI": 9.0})
        self.assertEqual(carried, "2026")

    def test_a_run_with_no_charges_keeps_the_total_exactly(self):
        line = format_line("2026", {"Acme AI": 25.5})
        self.assertEqual(accumulate(line, [], "2026-09-17")[1], {"Acme AI": 25.5})

    def test_the_basis_applies_once_and_is_then_carried_not_re_added(self):
        """Re-adding an opening balance every morning would inflate it daily."""
        _, first, _ = accumulate("", [], "2026-01-05", BASIS, "2026")
        self.assertEqual(first, BASIS)
        _, second, _ = accumulate(format_line("2026", first), [("Acme AI", 20.0)],
                                  "2026-01-06", BASIS, "2026")
        self.assertEqual(second, {"Acme AI": 432.50})

    def test_the_basis_is_ignored_outside_its_year(self):
        _, totals, _ = accumulate("", [("Acme AI", 20.0)], "2027-01-02", BASIS, "2026")
        self.assertEqual(totals, {"Acme AI": 20.0})

    def test_january_first_resets_every_service(self):
        last_year = format_line("2026", {"Acme AI": 900.0, "Northwind AI": 120.0})
        year, totals, carried = accumulate(last_year, [], "2027-01-01")
        self.assertEqual((year, totals, carried), ("2027", {}, None))

    def test_totals_are_rounded_to_cents(self):
        _, totals, _ = accumulate("", [("Acme AI", 0.1), ("Acme AI", 0.2)], "2026-09-15")
        self.assertEqual(totals, {"Acme AI": 0.3})

    def test_a_bad_date_is_refused(self):
        for bad in ("yesterday", "2026-13-40", ""):
            with self.assertRaises(ValueError, msg=bad):
                accumulate("", [], bad)

    def test_rows_are_largest_first_with_each_service_share(self):
        self.assertEqual(rows({"Northwind AI": 40.0, "Acme AI": 120.0}),
                         [["Acme AI", 120.0, "75% of AI spend this year"],
                          ["Northwind AI", 40.0, "25% of AI spend this year"]])
        self.assertEqual(rows({}), [])


class TestRenderedIntoTheBrief(unittest.TestCase):
    BLOCK = {"year": "2026",
             "rows": [["Acme AI", 120.0, "75% of AI spend this year"],
                      ["Northwind AI", 40.0, "25% of AI spend this year"]],
             "note": "Acme AI carries an opening balance agreed for 2026."}

    def test_it_sits_inside_deposits_and_finances(self):
        f, em, tx = render_all(payload(AI_SPEND=self.BLOCK))
        for doc, finances, after in ((f, "Deposits &amp; finances", "Upcoming flights"),
                                     (em, "Deposits &amp; finances", "Upcoming flights"),
                                     (tx, "DEPOSITS & FINANCES", "UPCOMING FLIGHTS")):
            here = doc.index("AI services")
            self.assertGreater(here, doc.index(finances))
            self.assertLess(here, doc.index(after), "it must not spill into the next section")

    def test_every_output_carries_the_figures_and_the_total(self):
        f, em, tx = render_all(payload(AI_SPEND=self.BLOCK))
        for doc in (f, em, tx):
            self.assertIn("$120.00", doc)
            self.assertIn("$40.00", doc)
            self.assertIn("$160.00", doc, "the caption totals the services")
            self.assertIn("1 January", doc, "the reader is told when it resets")
            self.assertIn("not back-dated", doc)

    def test_the_text_copy_ends_the_section_with_the_machine_line(self):
        """This line is the only reason tomorrow's total is not zero."""
        _, _, tx = render_all(payload(AI_SPEND=self.BLOCK))
        self.assertIn("AI spend YTD 2026: Acme AI $120.00; Northwind AI $40.00", tx)
        self.assertEqual(parse_line(tx), ("2026", {"Acme AI": 120.0, "Northwind AI": 40.0}))

    def test_a_payload_without_the_key_renders_exactly_as_before(self):
        p = payload()
        del p["AI_SPEND"]
        for doc in render_all(p):
            self.assertNotIn("AI services", doc)
            self.assertNotIn("AI spend YTD", doc)
        self.assertIn("Deposits &amp; finances", render_all(p)[0])

    def test_an_empty_block_draws_no_heading(self):
        for block in ({"year": "2026", "rows": []}, {}):
            for doc in render_all(payload(AI_SPEND=block)):
                self.assertNotIn("AI services", doc, block)

    def test_the_contract_refuses_a_block_that_cannot_be_added_up(self):
        for bad in ({"year": "2026", "rows": [["Acme AI", "120.00", "note"]]},
                    {"year": "26", "rows": []},
                    {"year": "2026", "rows": [["Acme AI", 120.0]]},
                    {"rows": []},
                    "not an object"):
            with self.assertRaises(PayloadError, msg=repr(bad)):
                validate(payload(AI_SPEND=bad))


class TestAiSpendCli(unittest.TestCase):
    def run_cli(self, *args, previous=None):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "ai_spend.json")
            argv = [sys.executable, "-m", "brief", "ai-spend", "-o", out, *args]
            if previous is not None:
                path = os.path.join(d, "previous.txt")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(previous)
                argv += ["--previous", path]
            res = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
            block = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else None
        return res, block

    def test_it_writes_a_block_the_payload_accepts(self):
        res, block = self.run_cli("--today", "2026-09-15", "--add", "Acme AI=20.00",
                                  "--note", "counted from today")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(block, {"year": "2026", "rows": [["Acme AI", 20.0, "100% of AI spend this year"]],
                                 "note": "counted from today"})
        validate(payload(AI_SPEND=block))

    def test_a_full_year_in_sequence(self):
        """Basis, a charge, a quiet day, then January: the way it will actually run."""
        res, block = self.run_cli("--today", "2026-02-01", "--basis", "Acme AI=412.50",
                                  "--basis-year", "2026")
        line = [l for l in res.stdout.splitlines() if l.startswith("AI spend YTD")][0]
        res, block = self.run_cli("--today", "2026-02-02", "--add", "Acme AI=20.00",
                                  "--add", "Northwind AI=8.00", "--basis", "Acme AI=412.50",
                                  "--basis-year", "2026", previous=line)
        self.assertEqual({r[0]: r[1] for r in block["rows"]},
                         {"Acme AI": 432.50, "Northwind AI": 8.0})
        line = [l for l in res.stdout.splitlines() if l.startswith("AI spend YTD")][0]
        res, block = self.run_cli("--today", "2026-02-03", previous=line)
        self.assertEqual({r[0]: r[1] for r in block["rows"]},
                         {"Acme AI": 432.50, "Northwind AI": 8.0}, "a quiet day changes nothing")
        line = [l for l in res.stdout.splitlines() if l.startswith("AI spend YTD")][0]
        _, block = self.run_cli("--today", "2027-01-01", "--basis", "Acme AI=412.50",
                                "--basis-year", "2026", previous=line)
        self.assertEqual(block["rows"], [], "the new year starts at zero")

    def test_it_says_whether_anything_was_carried_forward(self):
        res, _ = self.run_cli("--today", "2026-09-15")
        self.assertIn("nothing carried forward", res.stdout)
        res, _ = self.run_cli("--today", "2026-09-15",
                              previous=format_line("2026", {"Acme AI": 5.0}))
        self.assertIn("carried forward from the previous brief", res.stdout)

    def test_a_malformed_charge_is_refused_rather_than_guessed(self):
        for bad in ("Acme AI", "Acme AI=lots", "=12.00"):
            res, _ = self.run_cli("--today", "2026-09-15", "--add", bad)
            self.assertEqual(res.returncode, 2, bad)
            self.assertIn("--add", res.stderr)

    def test_a_missing_previous_file_is_an_error_not_a_silent_reset(self):
        res = subprocess.run([sys.executable, "-m", "brief", "ai-spend", "--today", "2026-09-15",
                              "--previous", "/no/such/brief.txt"], cwd=ROOT,
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("cannot read", res.stderr)


if __name__ == "__main__":
    unittest.main()
