#!/usr/bin/env python3
"""Refuse a commit that carries the owner's real data into a public repo.

The repository's tests catch SHAPES - a booking reference, masked digits, a
non-reserved email domain. They cannot catch a real name that looks like any
other name, or a real flight number, or a real brokerage. Those got in anyway,
copied out of screenshots the owner pasted to explain what was wrong with the
brief, and were noticed only after they had been published.

So this hook checks the staged content against the two things that DO know:

  1. tests/private_denylist.txt - one regex per line, gitignored, the owner's
     own identifiers.
  2. The owner's filled-in Routine prompts, if $BRIEF_PRIVATE_DIR points at
     them. Those files are the one place the personal values already live -
     mailbox addresses, phone numbers, an opening balance, a delivery address -
     so the denylist can be DERIVED from them rather than maintained twice.
     Nothing from those files is ever printed here; only the fact that a staged
     line matched, and where.

Install it with tools/install-privacy-hook.sh. It exits non-zero to stop the
commit, and `git commit --no-verify` remains available for the case where the
match is a false positive - the hook says which line, so that is a decision
rather than a shrug.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DENYLIST = os.path.join(ROOT, "tests", "private_denylist.txt")
# What is worth deriving from a filled-in prompt: things that identify a person
# rather than words. A bare word from the prompt ("Gmail", "daily") would match
# everything; these shapes do not.
DERIVED = (
    r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",                        # an address
    r"(?<!\d)(?:\+?\d{1,2}[-. ]*)?\(?\d{3}\)?[-. ]*\d{3}[-. ]*\d{4}(?!\d)",  # a phone number
    r"\b(?=[A-Z0-9]{5,8}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{5,8}\b",  # a booking reference
    r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b",                       # an amount
    r"·{2,}\d{4}\b",                                   # masked card digits
)
ALLOW = {"empcoorg@users.noreply.github.com", "noreply@anthropic.com"}
# A prompt is also full of the template's OWN examples, and those belong in the
# repo. Deriving them would block every commit that touches the documentation,
# which is how a hook gets uninstalled. So the reserved and invented shapes are
# dropped: they identify nobody.
FICTION = ("SAMPLE", "MOCK", "EXAMPLE", "TEST", "DEMO", "FAKE", "PLACEHOLDER")
PLACEHOLDER_DIGITS = ("1234", "0000", "1111", "9999", "4321", "5678")
RESERVED_DOMAINS = (".example.com", ".example.org", ".example.net", "@example.com",
                    "@example.org", "@example.net", ".invalid", ".test", ".localhost")


def identifying(value):
    """Is this value the owner's, or the template's own example?

    >>> identifying("you@example.com"), identifying("555-010-0001")
    (False, False)
    >>> identifying("MOCKR1"), identifying("\u00b7\u00b7\u00b71234")
    (False, False)
    """
    low = value.lower()
    if any(m in value.upper() for m in FICTION):
        return False
    if any(d in low for d in RESERVED_DOMAINS):
        return False
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 7 and ("555" in digits[:6]):
        return False                              # the reserved fictional range
    if value.lstrip("\u00b7.") in PLACEHOLDER_DIGITS:
        return False
    return True


def staged_files():
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                         cwd=ROOT, capture_output=True, text=True).stdout.split()
    return [f for f in out if not f.lower().endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".lock"))]


def staged_text(path):
    r = subprocess.run(["git", "show", f":{path}"], cwd=ROOT,
                       capture_output=True)
    return r.stdout.decode("utf-8", "ignore") if r.returncode == 0 else ""


def denylist_patterns():
    if not os.path.exists(DENYLIST):
        return []
    with open(DENYLIST, encoding="utf-8") as fh:
        return [l.strip() for l in fh
                if l.strip() and not l.lstrip().startswith("#")]


def derived_patterns():
    """Literal values lifted out of the owner's own filled-in prompts."""
    private = os.environ.get("BRIEF_PRIVATE_DIR", "")
    if not private or not os.path.isdir(os.path.expanduser(private)):
        return []
    values = set()
    for name in sorted(os.listdir(os.path.expanduser(private))):
        path = os.path.join(os.path.expanduser(private), name)
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for shape in DERIVED:
            for hit in re.findall(shape, text):
                if hit not in ALLOW and len(hit) > 5 and identifying(hit):
                    values.add(hit)
    return [re.escape(v) for v in sorted(values)]


def main():
    patterns = [(p, "your denylist") for p in denylist_patterns()]
    patterns += [(p, "your Routine prompt") for p in derived_patterns()]
    if not patterns:
        print("privacy hook: no denylist and no $BRIEF_PRIVATE_DIR — nothing to "
              "check against. See tools/install-privacy-hook.sh.", file=sys.stderr)
        return 0
    compiled = []
    for pat, source in patterns:
        try:
            compiled.append((re.compile(pat), source))
        except re.error as ex:
            print(f"privacy hook: bad pattern in denylist ({ex}); fix it or the "
                  "hook is checking less than you think.", file=sys.stderr)
            return 1
    hits = []
    for path in staged_files():
        text = staged_text(path)
        for n, line in enumerate(text.splitlines(), 1):
            for rx, source in compiled:
                if rx.search(line):
                    hits.append(f"  {path}:{n} matches a value from {source}")
                    break
    if hits:
        print("COMMIT REFUSED — this repository is public and the staged change "
              "carries your own data:\n" + "\n".join(sorted(set(hits)))
              + "\n\nReplace the value with an invented one (see CLAUDE.md for the "
                "approved vocabulary). If it really is a false positive, commit "
                "with --no-verify.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
