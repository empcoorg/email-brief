"""Tests for the two modules that used to be recipes in the prompt.

brief/links.py was a paragraph telling the run how to base64-decode and gunzip
an Indeed token, and a table of IATA-to-ICAO codes to recall. brief/postal.py
was a description of when a printed name counts as the owner's - the repo's
sharpest privacy rule, restated in prose on every run.
"""
import base64
import gzip
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from brief.links import (canonical_job_url, flight_ident, flightaware_url,
                         indeed_job_url, linkedin_job_url)
from brief.postal import (GENERIC, LIKELY, OTHER_NAMED, RECIPIENT,
                          addressee_matches, classify_addressee, counts,
                          is_generic_addressee)

OWNER = "Alex Q. Sample"


def indeed_token(dest):
    raw = gzip.compress(json.dumps({"u": dest}).encode())
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class TestIndeed(unittest.TestCase):
    def test_decodes_a_tracking_redirect_to_the_posting(self):
        tok = indeed_token("https://www.indeed.com/viewjob?jk=eed0f6941ab2c3d4&from=serp")
        self.assertEqual(indeed_job_url(f"https://cts.indeed.com/v3/{tok}/sig123"),
                         "https://www.indeed.com/viewjob?jk=eed0f6941ab2c3d4")

    def test_survives_missing_base64_padding(self):
        for dest in (f"https://www.indeed.com/viewjob?jk={'a' * 16}",
                     f"https://www.indeed.com/viewjob?jk={'b' * 16}&x=1&y=2"):
            tok = indeed_token(dest)
            self.assertIsNotNone(indeed_job_url(f"https://cts.indeed.com/v3/{tok}/s"))

    def test_direct_indeed_links_are_normalised(self):
        self.assertEqual(
            indeed_job_url("https://www.indeed.com/viewjob?jk=0123456789abcdef&tk=spam"),
            "https://www.indeed.com/viewjob?jk=0123456789abcdef")

    def test_garbage_returns_none_rather_than_raising(self):
        """A link that cannot be recovered is reported as such; it must never
        take the run down."""
        for bad in (None, "", "not a url", "https://cts.indeed.com/v3/!!!!/sig",
                    "https://cts.indeed.com/v3/" + base64.urlsafe_b64encode(b"not gzip").decode(),
                    "https://cts.indeed.com/v3/" + indeed_token("https://example.com/no-jk")):
            self.assertIsNone(indeed_job_url(bad), f"{bad!r} should yield None")


class TestLinkedIn(unittest.TestCase):
    def test_strips_tracking_query(self):
        self.assertEqual(
            linkedin_job_url("https://www.linkedin.com/jobs/view/4453595708/?trk=x&lipi=y"),
            "https://www.linkedin.com/jobs/view/4453595708/")

    def test_handles_the_comm_alert_path(self):
        self.assertEqual(
            linkedin_job_url("https://www.linkedin.com/comm/jobs/view/4463779360?refId=z"),
            "https://www.linkedin.com/jobs/view/4463779360/")

    def test_recovers_id_from_a_query_parameter(self):
        self.assertEqual(
            linkedin_job_url("https://www.linkedin.com/jobs/search/?currentJobId=4451267671"),
            "https://www.linkedin.com/jobs/view/4451267671/")

    def test_non_linkedin_returns_none(self):
        self.assertIsNone(linkedin_job_url("https://example.com/jobs/view/123/"))

    def test_canonical_dispatches_to_either_decoder(self):
        self.assertIn("linkedin.com", canonical_job_url(
            "https://www.linkedin.com/jobs/view/42/?trk=x"))
        tok = indeed_token("https://www.indeed.com/viewjob?jk=aaaabbbbccccdddd")
        self.assertIn("indeed.com", canonical_job_url(f"https://cts.indeed.com/v3/{tok}/s"))
        self.assertIsNone(canonical_job_url("https://boards.greenhouse.io/acme/jobs/1"))


class TestFlightAware(unittest.TestCase):
    def test_iata_to_icao(self):
        for flight, ident in (("DL 1816", "DAL1816"), ("DL1816", "DAL1816"),
                              ("dl 1816", "DAL1816"), ("UA 55", "UAL55"),
                              ("AA 100", "AAL100"), ("WN 44", "SWA44"),
                              ("B6 20", "JBU20"), ("AS 3", "ASA3")):
            self.assertEqual(flight_ident(flight), ident, flight)

    def test_leading_zeros_are_dropped(self):
        self.assertEqual(flight_ident("DL 0651"), "DAL651")

    def test_unknown_carrier_returns_none_rather_than_a_wrong_url(self):
        """Guessing an ident would link to somebody else's flight."""
        for unknown in ("ZZ 1", "QQ 100", "", None, "1816", "DELTA 1816"):
            self.assertIsNone(flight_ident(unknown), f"{unknown!r}")
            self.assertIsNone(flightaware_url(unknown))

    def test_url_shape(self):
        self.assertEqual(flightaware_url("DL 1816"),
                         "https://www.flightaware.com/live/flight/DAL1816")


class TestGenericAddressee(unittest.TestCase):
    def test_household_forms(self):
        for g in ("Current Resident", "CURRENT RESIDENT", "resident",
                  "Homeowner", "Postal Customer", "Our Neighbors",
                  "Current Occupant", "  Residential Customer  "):
            self.assertTrue(is_generic_addressee(g), g)

    def test_real_names_are_not_generic(self):
        for n in ("Alex Q Sample", "Dana Liu", "Sample Family", ""):
            self.assertFalse(is_generic_addressee(n), n)


class TestAddresseeMatching(unittest.TestCase):
    def test_matches_regardless_of_order_case_and_punctuation(self):
        for printed in ("Alex Q. Sample", "ALEX SAMPLE", "Sample, Alex Q",
                        "alex quentin sample", "Mr. Alex Sample Jr.",
                        "A. Q. Sample", "ALEX Q SAMPLE"):
            self.assertTrue(addressee_matches(printed, OWNER), printed)

    def test_refuses_the_ambiguous_cases(self):
        """These are the ways a neighbour's or relative's mail gets published."""
        for printed in ("Alex", "Sample", "Jordan Sample", "Alex Jordan",
                        "Dana Liu", "Q. Sample", "", "The Sample Family"):
            self.assertFalse(addressee_matches(printed, OWNER), printed)

    def test_accented_and_unicode_names(self):
        self.assertTrue(addressee_matches("JOSÉ GARCÍA", "Jose Garcia"))
        self.assertTrue(addressee_matches("Jose Garcia", "José García"))

    def test_classification_buckets(self):
        self.assertEqual(classify_addressee("ALEX SAMPLE", OWNER), RECIPIENT)
        self.assertEqual(classify_addressee("Dana Liu", OWNER), OTHER_NAMED)
        self.assertEqual(classify_addressee("Current Resident", OWNER), GENERIC)

    def test_generic_wins_over_a_name_match(self):
        """"Alex Sample or Current Resident" is addressed to the household."""
        self.assertEqual(classify_addressee("Alex Sample or Current Resident", OWNER), GENERIC)

    def test_counts_bucket_a_whole_run(self):
        got = counts(["Alex Q Sample", "ALEX SAMPLE", "Dana Liu",
                      "Current Resident", "Homeowner"], OWNER)
        self.assertEqual(got, {RECIPIENT: 2, LIKELY: 0, OTHER_NAMED: 1, GENERIC: 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestMultipleNameForms(unittest.TestCase):
    """Senders disagree about what to call someone. Listing forms widens what
    counts as the owner without ever widening it to a different person."""

    OWNER = "Alexander Q. Sample; Lex Sample"

    def test_each_listed_form_matches(self):
        for printed in ("ALEXANDER Q SAMPLE", "Sample, Alexander", "A. Sample",
                        "Lex Sample", "LEX SAMPLE", "Mr. Lex Sample"):
            self.assertTrue(addressee_matches(printed, self.OWNER), printed)

    def test_an_unlisted_variant_does_not_match(self):
        """An unlisted spelling is not assumed — add it as a form if a sender
        uses it."""
        self.assertFalse(addressee_matches("Lexington Sample", self.OWNER))

    def test_a_different_person_never_matches(self):
        for printed in ("Dana Sample", "Lex Johnson", "Sample", "Lex",
                        "Alexander Johnson"):
            self.assertFalse(addressee_matches(printed, self.OWNER), printed)

    def test_forms_accept_a_list_too(self):
        self.assertTrue(addressee_matches("Lex Sample", ["Alex Q. Sample", "Lex Sample"]))

    def test_a_comma_is_not_a_separator(self):
        """Mail reads "Sample, Alex" — splitting on commas would turn one name
        into two half-names and match far too much."""
        from brief.postal import name_forms
        self.assertEqual(name_forms("Sample, Alex Q"), ["Sample, Alex Q"])
        self.assertTrue(addressee_matches("Alex Q Sample", "Sample, Alex Q"))
        self.assertFalse(addressee_matches("Alex Johnson", "Sample, Alex Q"))

    def test_single_form_behaviour_is_unchanged(self):
        self.assertTrue(addressee_matches("ALEX SAMPLE", "Alex Q. Sample"))
        self.assertFalse(addressee_matches("Jordan Sample", "Alex Q. Sample"))


class TestLikelyVariants(unittest.TestCase):
    """A third outcome between "yours" and "someone else's".

    Losing your own mail to a spelling variant is a real cost, and the old
    binary filter did exactly that: "Alex Sample" was reduced to a bare count.
    But a shared surname alone cannot mean "yours" — a relative at the same
    address has that too — so a probable match is INCLUDED and LABELLED rather
    than silently claimed or silently dropped.
    """

    OWNER = "Alexander Q. Sample"

    def test_exact_forms_are_the_recipient(self):
        for printed in ("ALEXANDER Q SAMPLE", "Sample, Alexander", "A. Sample",
                        "Alexander Quentin Sample", "Sample, Alexander Quentin",
                        "Alexander Q Sample", "Mr. Alexander Sample Jr."):
            self.assertEqual(classify_addressee(printed, self.OWNER), RECIPIENT, printed)

    def test_variants_are_likely_not_lost(self):
        for printed in ("Alex Sample", "Xander Sample", "Alexandr Sample",
                        "Alex Quentin Sample"):
            self.assertEqual(classify_addressee(printed, self.OWNER), LIKELY, printed)

    def test_a_different_first_name_is_still_someone_else(self):
        """The whole point of the filter. A relative shares the surname."""
        for printed in ("Dana Sample", "Maria Sample", "Quentin Sample",
                        "Robert Sample", "Susan Sample"):
            self.assertEqual(classify_addressee(printed, self.OWNER), OTHER_NAMED, printed)

    def test_surname_is_always_the_anchor(self):
        """A matching first name with a different surname is never included —
        otherwise everyone sharing a first name qualifies."""
        for printed in ("Alexander Johnson", "Alex Smith", "Alexander Q Public"):
            self.assertEqual(classify_addressee(printed, self.OWNER), OTHER_NAMED, printed)

    def test_first_name_relation_cases(self):
        from brief.postal import first_name_relation as rel
        self.assertEqual(rel("alexander", "alexander"), "exact")
        self.assertEqual(rel("alexander", "a"), "exact")
        self.assertEqual(rel("alexander", "alex"), "likely")   # nickname table
        self.assertEqual(rel("alexander", "xander"), "likely") # nickname table
        self.assertEqual(rel("alexander", "alexandr"), "likely")  # spelling variant
        self.assertEqual(rel("katherine", "kate"), "likely")
        self.assertEqual(rel("alexander", "dana"), "different")
        self.assertEqual(rel("robert", "richard"), "different")

    def test_short_names_do_not_collapse_into_each_other(self):
        """Edit distance is only trusted on names long enough for it to mean
        something: "Ann" and "Dan" are two letters apart and two people."""
        from brief.postal import first_name_relation as rel
        self.assertEqual(rel("ann", "dan"), "different")
        self.assertEqual(rel("jon", "ron"), "different")

    def test_counts_report_the_likely_bucket_separately(self):
        got = counts(["Alexander Q Sample", "Alex Sample", "Dana Sample",
                      "Current Resident"], self.OWNER)
        self.assertEqual(got, {RECIPIENT: 1, LIKELY: 1, OTHER_NAMED: 1, GENERIC: 1})

    def test_listing_a_form_promotes_a_variant_to_exact(self):
        """If a sender always uses the nickname, list it and it stops being a
        guess."""
        self.assertEqual(classify_addressee("Alex Sample", self.OWNER), LIKELY)
        self.assertEqual(
            classify_addressee("Alex Sample", "Alexander Q. Sample; Alex Sample"),
            RECIPIENT)
