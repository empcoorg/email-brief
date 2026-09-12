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
        skip = {"morning brief", "application status", "ranked leads", "also seen (lower fit)",
                "jobs by sector", "transfers between your own accounts",
                "bills, statements &amp; notices", "large caps", "vanguard funds"}
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


class TestTheDocRuleIsWrittenDown(unittest.TestCase):
    def test_claude_md_requires_docs_with_the_change(self):
        self.assertIn("Documentation is part of the change", CLAUDE_MD)
        for anchor in ("render_screenshots.py", "screenshots.lock"):
            self.assertIn(anchor, CLAUDE_MD, f"CLAUDE.md no longer mentions {anchor}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
