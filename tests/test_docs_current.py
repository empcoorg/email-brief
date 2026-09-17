"""Documentation must describe the code that exists.

The screenshots already have a mechanical guard: docs/screenshots.lock
fingerprints the rendered HTML, so a UI change cannot merge while the README
shows the old one. Prose had no such guard, and it drifted repeatedly — the
README described jobs as section 1 long after High priority took that slot, and
listed modules that had since gained siblings.

Prose cannot be auto-written, but staleness can be DERIVED: anything the README
claims about the code's surface is checked against the code itself. A change
that adds a module, a CLI command, a test file or a section therefore fails CI
until the README mentions it.
"""
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

README = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
CLAUDE_MD = open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf-8").read()
TEMPLATE = open(os.path.join(ROOT, "ROUTINE_PROMPT.template.md"), encoding="utf-8").read()


class TestReadmeDescribesTheCode(unittest.TestCase):
    def test_every_cli_command_is_documented(self):
        main = open(os.path.join(ROOT, "brief", "__main__.py"), encoding="utf-8").read()
        commands = set(re.findall(r'sub\.add_parser\("(\w+)"', main))
        self.assertTrue(commands, "no CLI subcommands found — did the parser move?")
        missing = sorted(c for c in commands if f"brief {c}" not in README)
        self.assertEqual(missing, [], f"README does not document: python3 -m brief {missing}")

    def test_every_module_is_listed(self):
        mods = {f for f in os.listdir(os.path.join(ROOT, "brief"))
                if f.endswith(".py") and not f.startswith("__")}
        missing = sorted(m for m in mods if m not in README)
        self.assertEqual(missing, [], f"README's repo table omits: {missing}")

    def test_every_test_file_is_listed(self):
        tests = {f for f in os.listdir(os.path.join(ROOT, "tests")) if f.startswith("test_")}
        missing = sorted(t for t in tests if t not in README)
        self.assertEqual(missing, [], f"README omits test files: {missing}")

    def test_every_rendered_section_is_described(self):
        """If the brief grows a section, the README's description of what a brief
        contains has to grow with it."""
        from brief import load, render_all
        page = render_all(load(os.path.join(ROOT, "sample_payload.json")))[0]
        headings = re.findall(r'<h[23]>(?:<span class="num">\d+\.</span> )?([^<]+)', page)
        blurb = README.split("## What a brief contains")[1].split("## ")[0].lower()
        # Sub-headings inside a section the blurb already describes.
        skip = {"morning brief", "application status", "ranked leads", "also seen (lower fit)",
                "jobs by sector", "transfers between your own accounts",
                "bills, statements &amp; notices", "large caps", "vanguard funds",
                "flights", "stays &amp; other bookings", "ai services — billed year to date"}
        missing = sorted({h.strip() for h in headings
                          if h.strip().lower() not in skip
                          and h.strip().lower().replace("&amp;", "&") not in blurb})
        self.assertEqual(missing, [],
                         f"README's 'What a brief contains' omits: {missing}")

    def test_screenshot_captions_match_the_sections_they_show(self):
        """Captions name section numbers; those move when sections are reordered."""
        for img in re.findall(r"!\[[^\]]*\]\((docs/[^)]+)\)", README):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, img)), f"missing {img}")
        self.assertIn("screenshots.lock", README,
                      "the README must explain that screenshot currency is enforced")


class TestEgressAllowlist(unittest.TestCase):
    """The list pasted into the environment must carry what the prompt reads.

    The prompt's domain list says which sources to PREFER; it cannot grant
    access. If the two drift, a run follows the prompt to a domain the proxy
    refuses, and the section comes out empty with nobody the wiser.
    """

    PATH = os.path.join(ROOT, "docs", "egress-allowlist.txt")

    def domains(self):
        with open(self.PATH, encoding="utf-8") as fh:
            return [l.strip() for l in fh if l.strip() and not l.startswith("#")]

    def prompt_domains(self):
        block = TEMPLATE.split("PRE-APPROVED DOMAINS")[1].split("KNOWN-DIFFICULT")[0]
        found = []
        for line in block.splitlines():
            if ":" in line and "\u00b7" in line:
                found += [d.strip() for d in line.split(":", 1)[1].split("\u00b7") if "." in d]
        return found

    def test_every_domain_the_prompt_prefers_is_in_the_list(self):
        listed, wanted = set(self.domains()), self.prompt_domains()
        self.assertTrue(wanted, "the template no longer names its sources")
        missing = sorted(d for d in wanted if d not in listed)
        self.assertEqual(missing, [], f"the allowlist omits sources the prompt reads: {missing}")

    def test_every_apex_domain_also_lists_its_www_host(self):
        """The proxy matches the exact hostname, not the registered domain.

        With only "coingecko.com" listed, a fetch of www.coingecko.com came back
        EGRESS_BLOCKED, while stockanalysis.com - which serves at the apex -
        went through. Measured in the Routine's own environment, 2026-09-18.
        """
        listed = set(self.domains())
        multi = (".co.uk", ".com.au", ".co.jp", ".org.uk", ".ac.uk")

        def apex(d):
            return d.count(".") == (2 if any(d.endswith(m) for m in multi) else 1)

        missing = sorted(f"www.{d}" for d in listed if apex(d) and f"www.{d}" not in listed)
        self.assertEqual(missing, [], f"hosts the proxy would still refuse: {missing}")

    def test_the_list_is_finite_boring_and_free_of_wildcards(self):
        doms = self.domains()
        self.assertEqual(sorted(doms), sorted(set(doms)), "a domain is listed twice")
        for d in doms:
            self.assertNotIn("*", d, f"{d}: a wildcard widens this far past what a brief reads")
            self.assertNotIn("/", d, f"{d}: a domain, not a URL")
            self.assertRegex(d, r"^[a-z0-9.-]+\.[a-z]{2,}$", f"{d} is not a bare domain")

    def test_the_file_says_what_it_is_and_what_it_costs(self):
        with open(self.PATH, encoding="utf-8") as fh:
            head = fh.read().split("# Markets")[0]
        self.assertIn("EGRESS_BLOCKED", head, "it must say why the prompt's own list is not enough")
        self.assertIn("Network access", head, "it must say where the list is pasted")
        self.assertIn("mailbox", head, "it must say what widening egress costs")

    def test_the_readme_points_at_the_file(self):
        self.assertIn("docs/egress-allowlist.txt", README)


class TestTheDocRuleIsWrittenDown(unittest.TestCase):
    def test_claude_md_requires_docs_with_the_change(self):
        self.assertIn("Documentation is part of the change", CLAUDE_MD)
        for anchor in ("render_screenshots.py", "screenshots.lock"):
            self.assertIn(anchor, CLAUDE_MD, f"CLAUDE.md no longer mentions {anchor}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
