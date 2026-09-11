"""Who a mailpiece is addressed to.

The USPS digest shows scans of everything arriving at an address, including
other people's mail. The brief details ONLY the intended recipient's pieces;
everyone else is counted and never named. That rule is the repo's sharpest
privacy commitment, and it used to live as a paragraph of prose that the run
re-interpreted from scratch on every scan:

    "the printed addressee matches the owner (any order/case; initials and
     middle names fine; a bare first name or a matching surname with a
     different first name does not count)"

Deciding what a scan says still needs vision. Deciding what the printed name
MEANS is a pure function, and this is it.

Erring toward exclusion is deliberate: a piece wrongly excluded costs the owner
one line of detail, while a piece wrongly included publishes a neighbour's mail.
"""
import re
import unicodedata

# Addressed to the household rather than a person. Detailing these is harmless
# but pointless, so they are counted separately from real people's mail.
GENERIC_ADDRESSEES = (
    "current resident", "resident", "current occupant", "occupant",
    "homeowner", "home owner", "householder", "postal customer",
    "our neighbors", "our neighbours", "neighbor", "neighbour",
    "current owner", "or current resident", "local postal customer",
    "friends and neighbors", "residential customer",
)

# Dropped before comparing names.
_TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "rev", "sir", "madam"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v", "md", "phd", "dds", "esq"}

RECIPIENT, OTHER_NAMED, GENERIC = "recipient", "other_named", "generic"


def _fold(text):
    """Lower-case, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _tokens(name):
    """Meaningful name parts: titles and suffixes removed."""
    return [t for t in _fold(name).split()
            if t not in _TITLES and t not in _SUFFIXES]


def is_generic_addressee(printed):
    """True when the piece is addressed to the household, not to a person.

    >>> is_generic_addressee("CURRENT RESIDENT")
    True
    >>> is_generic_addressee("Alex Q Sample")
    False
    """
    folded = _fold(printed)
    if not folded:
        return False
    return any(g == folded or g in folded for g in GENERIC_ADDRESSEES)


def _initial_match(a, b):
    """An initial matches a full name that starts with it: "q" vs "quentin"."""
    if a == b:
        return True
    if len(a) == 1 and b.startswith(a):
        return True
    if len(b) == 1 and a.startswith(b):
        return True
    return False


def name_forms(owner):
    """The accepted spellings of the owner's name.

    Senders do not agree on what to call someone: a bank prints the legal name,
    a shop prints the nickname it was given at signup, a magazine prints a
    maiden name. Demanding one exact string means the owner's own mail gets
    filed under "someone else" and reduced to a count.

    So the owner may list several forms, separated by SEMICOLONS:

        "Alexander Q. Sample; Lex Sample; A. Sample"

    A comma cannot be the separator because a mailpiece itself often reads
    "Sample, Alexander". Each form is still matched strictly - first name and
    surname both - so listing forms widens what counts as the owner without
    ever widening it to a different person.
    """
    if isinstance(owner, (list, tuple)):
        forms = list(owner)
    else:
        forms = str(owner or "").split(";")
    return [f.strip() for f in forms if f.strip()]


def addressee_matches(printed, owner):
    """Does the printed addressee name the owner?

    Order and case are ignored, initials count as their full name, and extra
    middle names on either side are fine. What does NOT count: a bare first
    name, or a shared surname with a different first name - the classic way a
    relative's mail gets published as the owner's.

    >>> addressee_matches("SAMPLE, ALEX Q", "Alex Q. Sample")
    True
    >>> addressee_matches("A. Sample", "Alex Q. Sample")
    True
    >>> addressee_matches("Jordan Sample", "Alex Q. Sample")
    False
    >>> addressee_matches("Alex", "Alex Q. Sample")
    False
    >>> addressee_matches("Lex Sample", "Alex Q. Sample; Lex Sample")
    True
    """
    return any(_matches_one(printed, form) for form in name_forms(owner))


def _matches_one(printed, owner):
    want, got = _tokens(owner), _tokens(printed)
    if len(want) < 2 or len(got) < 2:
        # a single token can never be an identification - "Alex" or "Sample"
        # alone is exactly the ambiguity this filter exists to refuse
        return False
    surname = want[-1]
    if surname not in got:
        return False
    first = want[0]
    # the first name must appear too, allowing an initial in either direction
    return any(_initial_match(first, g) for g in got if g != surname or got.count(surname) > 1)


def classify_addressee(printed, owner):
    """One of RECIPIENT, OTHER_NAMED or GENERIC.

    Generic is checked first: "Alex Sample or Current Resident" is addressed to
    the household, and detailing it would leak nothing but says more than the
    mailpiece does.

    >>> classify_addressee("Current Resident", "Alex Q. Sample")
    'generic'
    >>> classify_addressee("ALEX SAMPLE", "Alex Q. Sample")
    'recipient'
    >>> classify_addressee("Dana Liu", "Alex Q. Sample")
    'other_named'
    """
    if is_generic_addressee(printed):
        return GENERIC
    return RECIPIENT if addressee_matches(printed, owner) else OTHER_NAMED


def counts(printed_names, owner):
    """Bucket a run's scans. Returns {RECIPIENT: n, OTHER_NAMED: n, GENERIC: n}."""
    out = {RECIPIENT: 0, OTHER_NAMED: 0, GENERIC: 0}
    for name in printed_names:
        out[classify_addressee(name, owner)] += 1
    return out
