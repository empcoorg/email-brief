"""Personal data must never reach this repository.

The repo is public and ships a worked example, so every value in it has to be
invented. That was a stated policy enforced by two generic detectors - phone
numbers and email domains - and it was not enough: a real airline confirmation
code, a real card's last four digits and a real itinerary were copied out of a
pasted screenshot into sample_payload.json and shipped, because nothing looked
for those shapes.

These tests look for the shapes. They cannot know the owner's actual details -
naming them here would itself be the leak - so they work two ways:

  1. STRUCTURAL: identifiers of a kind that are only ever sensitive (booking
     references, masked account digits) must be drawn from an obviously
     fictional vocabulary. A real one fails even though the test has never seen
     it before. This is what runs in CI.
  2. DENYLIST: tests/private_denylist.txt (gitignored) holds the owner's own
     identifiers as regexes. Anything matching fails. This catches what
     structure cannot, and never enters the repository itself.
"""
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DENYLIST = os.path.join(ROOT, "tests", "private_denylist.txt")

# Anything standing in for a booking reference, order number or account must
# carry one of these, so a real code cannot pass by looking plausible.
FICTION_MARKERS = ("SAMPLE", "MOCK", "EXAMPLE", "TEST", "DEMO", "FAKE", "PLACEHOLDER")

# Masked account/card digits allowed in mock data. Real last-four digits are
# never in this set, so copying one in fails.
PLACEHOLDER_DIGITS = {"1234", "0000", "1111", "9999", "4321", "5678"}

SKIP_BINARY = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2")


def tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout.split()
    return [f for f in out if not f.lower().endswith(SKIP_BINARY)]


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


class TestNoRealIdentifiers(unittest.TestCase):
    def test_confirmation_codes_are_obviously_fictional(self):
        """A booking reference plus a surname is enough to open someone's
        reservation, so a real PNR in a public repo is a live credential."""
        # the label may be any case, but a booking reference is UPPERCASE and
        # mixes letters with digits — matching case-insensitively here turns
        # ordinary words like "emails" into false positives
        pat = re.compile(r"(?i:confirmation|conf\.?|booking|record locator|PNR)"
                         r"[^A-Za-z0-9]{0,12}\b([A-Z0-9]{5,8})\b")
        hits = []
        for f in tracked_text_files():
            for code in pat.findall(read(f)):
                if not (any(c.isdigit() for c in code) and any(c.isalpha() for c in code)):
                    continue                      # not the shape of a PNR
                if not any(m in code for m in FICTION_MARKERS):
                    hits.append(f"{f}: {code}")
        self.assertEqual(hits, [], "confirmation code that does not look invented "
                                   f"(must contain one of {FICTION_MARKERS}): {hits}")

    def test_masked_account_digits_are_placeholders(self):
        """Mock data may show a masked account, but only with placeholder digits."""
        pat = re.compile(r"(?:[·.…]{2,}|x{3,}|\*{3,}|ending in\s*)(\d{4})\b", re.I)
        hits = []
        for f in tracked_text_files():
            for digits in pat.findall(read(f)):
                if digits not in PLACEHOLDER_DIGITS:
                    hits.append(f"{f}: ···{digits}")
        self.assertEqual(hits, [], "masked account digits outside the placeholder set "
                                   f"{sorted(PLACEHOLDER_DIGITS)}: {hits}")

    def test_sample_payload_declares_itself_as_mock(self):
        """The worked example must say it is fictional, where a reader sees it."""
        payload = read("sample_payload.json")
        self.assertIn("mock data", payload.lower())
        self.assertIn("Alex Sample", payload)

    def test_readme_screenshots_come_only_from_the_sample_payload(self):
        """The README images are rendered from sample_payload.json, so if the
        payload is clean the screenshots are too. That link is what makes the
        other tests here sufficient to cover the images, which cannot be
        text-scanned."""
        script = read("docs/render_screenshots.py")
        self.assertIn("sample_payload.json", script)
        self.assertNotIn("payload.json\"", script.replace("sample_payload.json", ""))


class TestTheRuleIsWrittenDown(unittest.TestCase):
    """The structural checks catch shapes. They cannot catch a real name that
    looks like any other name — only the rule does that, and only if whoever is
    editing the repo reads it. So the rule has to exist, in the file an agent
    working here loads automatically."""

    def test_claude_md_states_the_rule(self):
        path = os.path.join(ROOT, "CLAUDE.md")
        self.assertTrue(os.path.isfile(path), "CLAUDE.md is missing")
        body = open(path, encoding="utf-8").read()
        self.assertIn("NO PERSONAL DATA", body.upper())
        for anchor in ("public", "invented", "private_denylist.txt"):
            self.assertIn(anchor, body, f"CLAUDE.md no longer explains {anchor!r}")

    def test_readme_points_at_the_rule(self):
        readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertIn("CLAUDE.md", readme,
                      "the README must point contributors at the data rule")


class TestCommitMetadata(unittest.TestCase):
    """Commit authorship is personal data too, and it is the easiest kind to
    forget: rewriting history fixes the commits that exist, while the NEXT
    commit quietly picks the real name back up from git config. That happened
    here, twice, minutes after a history rewrite."""

    APPROVED_AUTHORS = {"empcoorg", "Claude"}

    def _authors(self):
        r = subprocess.run(["git", "log", "--format=%an|%ae"], cwd=ROOT,
                           capture_output=True, text=True)
        return [l for l in r.stdout.splitlines() if l.strip()]

    def test_authors_are_anonymous(self):
        entries = self._authors()
        if len(entries) <= 1:
            self.skipTest("shallow checkout — no history to inspect")
        bad = sorted({e for e in entries if e.split("|")[0] not in self.APPROVED_AUTHORS})
        self.assertEqual(bad, [], f"commit author outside {sorted(self.APPROVED_AUTHORS)}: {bad}")

    def test_author_emails_leak_no_hostname(self):
        """A default git identity ending in .local publishes the machine name."""
        entries = self._authors()
        if len(entries) <= 1:
            self.skipTest("shallow checkout — no history to inspect")
        bad = sorted({e for e in entries if e.split("|")[1].endswith(".local")})
        self.assertEqual(bad, [], f"author email exposes a hostname: {bad}")

    def test_local_identity_if_configured_is_anonymous(self):
        """The repo-local identity is what stops the NEXT commit regressing, but
        it lives in a checkout's config rather than in the repo, so CI cannot
        have one. Check it when present; the authorship test above is the guard
        that actually runs everywhere."""
        r = subprocess.run(["git", "config", "--local", "user.name"], cwd=ROOT,
                           capture_output=True, text=True)
        name = r.stdout.strip()
        if not name:
            self.skipTest("no repo-local user.name (expected in CI); set it locally "
                          "with: git config --local user.name empcoorg")
        self.assertIn(name, self.APPROVED_AUTHORS)


class TestPrivateDenylist(unittest.TestCase):
    """The owner's own identifiers, kept out of the repository.

    Put one regex per line in tests/private_denylist.txt - real name, employers,
    booking references, card last-fours, street, phone numbers, anything that
    should never appear here. The file is gitignored, so the denylist itself
    never becomes the leak.
    """

    def test_denylist_is_never_committed(self):
        tracked = subprocess.run(["git", "ls-files", "tests/private_denylist.txt"],
                                 cwd=ROOT, capture_output=True, text=True).stdout.strip()
        self.assertEqual(tracked, "", "private_denylist.txt must stay untracked")

    def test_no_denylisted_string_appears_anywhere(self):
        if not os.path.isfile(DENYLIST):
            self.skipTest("no tests/private_denylist.txt — create one with your own "
                          "identifiers (one regex per line) for local protection; "
                          "the structural checks above still run in CI")
        patterns = []
        for line in open(DENYLIST, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(re.compile(line, re.I))
        self.assertTrue(patterns, "private_denylist.txt is empty")
        hits = []
        for f in tracked_text_files():
            if f == "tests/private_denylist.txt":
                continue
            body = read(f)
            for rx in patterns:
                if rx.search(body):
                    hits.append(f"{f}: matches /{rx.pattern}/")
        self.assertEqual(hits, [], f"denylisted personal data in tracked files: {hits}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
