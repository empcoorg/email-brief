"""Phone numbers are printed so they can be dialled from the phone reading them.

The risk runs both ways: a number left as "1 (555) 010-6200" has to be retyped
before it can be dialled, and an over-eager rewrite turns a tracking number or
an order reference into nonsense. Both directions are pinned here.
Stdlib unittest; no browser needed.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from brief import render_all  # noqa: E402
from brief.phones import DEFAULT_CC, dialable, normalize  # noqa: E402

SAMPLE = os.path.join(ROOT, "sample_payload.json")


def payload(**overrides):
    with open(SAMPLE, encoding="utf-8") as fh:
        p = json.load(fh)
    p.update(overrides)
    return p


class TestRewriting(unittest.TestCase):
    def test_every_shape_a_booking_email_writes_becomes_one_dialable_form(self):
        for written in ("1 (555) 010-6200", "(555) 010-6200", "555-010-6200",
                        "555.010.6200", "555 010 6200", "1-555-010-6200"):
            self.assertEqual(dialable(f"property phone {written}"),
                             "property phone +1-555-010-6200", written)

    def test_a_number_that_already_carries_its_country_code_is_left_alone(self):
        for done in ("+1-555-010-6200", "+44-20-7946-0958"):
            self.assertEqual(dialable(f"call {done}"), f"call {done}", done)

    def test_an_international_number_keeps_its_country_code_and_grouping(self):
        self.assertEqual(dialable("+44 20 7946 0958"), "+44-20-7946-0958")
        self.assertEqual(dialable("+52 55 1234 5678"), "+52-55-1234-5678")

    def test_several_numbers_in_one_line(self):
        self.assertEqual(dialable("desk (555) 010-0001, fax 555.010.0002"),
                         "desk +1-555-010-0001, fax +1-555-010-0002")

    def test_the_default_country_code_is_stated_not_assumed_in_passing(self):
        self.assertEqual(DEFAULT_CC, "+1")

    def test_what_must_never_be_rewritten(self):
        """Everything else in a brief that is digits but not a number to dial."""
        for kept in ("UPS 1Z999AA10123456784",
                     "USPS 9400 1000 0000 0000 0000 00",
                     "order 5550106200",                       # a bare ten digits
                     "Springfield ST 00000-0000",              # ZIP+4
                     "Visa ···1234 · statement 2026-03-27",
                     "9,800.00 fee + 400.00 service MXN",
                     "Row H, seats 4-5 · doors 7:15 PM",
                     "NW 412 · 8:05 AM MDT",
                     "invoice #241 paid · bill #88213"):
            self.assertEqual(dialable(kept), kept, kept)


class TestAcrossThePayload(unittest.TestCase):
    def test_a_number_anywhere_in_the_brief_is_rewritten_once(self):
        p = payload()
        p["TRAVEL"] = [["Hotel", "Northwind Harbor Hotel", "Fri Mar 6",
                        "front desk 1 (555) 010-6200", "SAMPLE-HTL-4471", ""]]
        p["FIN_NOTES"] = ["Lakeshore Power & Light — billing line (555) 010-0044."]
        for doc in render_all(p):
            self.assertIn("+1-555-010-6200", doc)
            self.assertIn("+1-555-010-0044", doc)
            self.assertNotIn("(555) 010-6200", doc)
            self.assertNotIn("+1-+1", doc)

    def test_the_voip_section_is_left_exactly_as_it_was(self):
        """The owner's explicit choice: that section prints what the provider wrote."""
        p = payload()
        numbers = {row[1] for row in p["VOIP"]["messages"]} | {row[2] for row in p["VOIP"]["messages"]}
        self.assertTrue(numbers, "the sample must carry VoIP messages for this test to mean anything")
        f, em, tx = render_all(p)
        for number in numbers:
            for doc in (f, em, tx):
                self.assertIn(number, doc, number)
                self.assertNotIn(f"{DEFAULT_CC}-{number}", doc)

    def test_a_mailpiece_scan_is_never_touched(self):
        """Its base64 can contain runs that look like numbers; rewriting one corrupts the image."""
        p = payload()
        before = json.dumps(p["USPS_SCANS"])
        self.assertEqual(json.dumps(normalize(p)["USPS_SCANS"]), before)
        self.assertIn(p["USPS_SCANS"][0][0][:60], render_all(p)[0])

    def test_links_and_tracking_rows_survive_verbatim(self):
        p = payload()
        f, em, tx = render_all(p)
        for carrier, tracking, *_rest in p["PKG"]:
            for doc in (f, em, tx):
                self.assertIn(tracking, doc, tracking)
        for _r, _c, _comp, _loc, _src, _tier, link in p["JOBS_TOP"]:
            self.assertIn(link, f, link)

    def test_normalize_does_not_mutate_the_payload_it_is_given(self):
        p = payload()
        p["FIN_NOTES"] = ["desk (555) 010-0044"]
        before = json.dumps(p, sort_keys=True)
        normalize(p)
        self.assertEqual(json.dumps(p, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
