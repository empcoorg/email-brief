# Working rules for this repository

## 1. NO PERSONAL DATA. EVER. THIS RULE HAS NO EXCEPTIONS.

This repository is **public**. Every value in it — in code, tests, fixtures,
documentation, screenshots, commit messages and commit diffs — must be invented.

This has been violated. Real values were copied out of a pasted screenshot into
`sample_payload.json`, shipped to a public repo, rendered into the README images
and committed across thirteen commits before anyone noticed. Purging it required
rewriting published history. Assume you are about to make the same mistake.

### The failure mode, precisely

The owner pastes a screenshot or an email to explain what is wrong with the
brief. Those values are **evidence, not fixtures**. Read them, diagnose with
them, and then invent different values for anything you write down.

The moment you are about to type a value that came from something the owner
showed you — a name, a booking reference, an account, an amount, an itinerary,
an employer, a nickname — stop and invent one instead.

### The approved vocabulary

Use these and nothing else:

| Kind | Use |
|---|---|
| People | `Alex Sample`, `Alexander Q. Sample`, `Dana Liu`, `Jordan Sample` |
| Email domains | `example.com`, `example.org`, `example.net` (IANA-reserved) |
| Phone numbers | `555-010-####` (the reserved fictional range) |
| Companies | `Acme`, `Northwind`, `Cascade`, `Helixware`, `Bluepine`, `Nortech`, `First Meridian`, `Lakeshore` |
| Booking refs / order ids | must contain `SAMPLE`, `MOCK`, `EXAMPLE`, `TEST`, `DEMO`, `FAKE` |
| Masked account digits | `1234`, `0000`, `1111`, `9999`, `4321`, `5678` |
| Airports / carriers | any, but never the owner's actual route or airline in combination |

Real **public** facts are fine and are not personal data: ticker symbols, index
names (`Russell 2000`), airline IATA/ICAO codes, journal names, domain names of
data sources. The test is whether the value identifies *this owner*.

### Commit metadata counts too

Authorship is personal data. This repo commits as `empcoorg
<empcoorg@users.noreply.github.com>`, set **repo-locally** so it cannot be
forgotten:

    git config --local user.name empcoorg
    git config --local user.email empcoorg@users.noreply.github.com

Rewriting history fixes the commits that exist; the next commit picks the real
identity straight back up from git config unless this is set. That happened
here, twice, minutes after a history rewrite. `tests/test_privacy.py` checks it.

`test_authors_are_anonymous` inspects every commit's author, but skips in CI
because `actions/checkout` is shallow by default. To make it run there, add to
`.github/workflows/tests.yml` under the checkout step (needs a token with
`workflow` scope):

    - uses: actions/checkout@v4
      with:
        fetch-depth: 0

### What enforces it

- `tests/test_privacy.py` — booking references must carry a fiction marker;
  masked digits must be placeholders; email domains must be reserved ones;
  phone numbers must be `555`; the sample payload must declare itself as mock.
- `tests/private_denylist.txt` — **gitignored**, one regex per line, holding the
  owner's own identifiers. The strongest protection available, because it knows
  what the structural checks cannot. Create it; never commit it; never echo its
  contents anywhere.
- The README screenshots are rendered from `sample_payload.json` alone, so a
  clean payload is what keeps the images clean.

These catch shapes. They cannot catch a real name that looks like any other
name. **The rule above is what catches that, and it is on you, not the tests.**

## 2. The design is code, not prose

Every visual decision lives in `brief/`. The Routine prompt says what to gather;
it carries no design spec. If the brief looks wrong, fix the renderer and its
tests — never describe the fix in the prompt.

## 3. Aesthetics are pinned

Colours and fonts live in `brief/theme.py`; no renderer may hardcode one.
`docs/screenshots.lock` fingerprints the rendered HTML, so any visual change
fails CI until the screenshots are regenerated deliberately. Change the look
only when the owner explicitly asks.

## 4. Verify, don't assert

Claims about behavior need evidence: run it, measure it, diff it. "Byte
identical", "aligned", "under budget" are checkable — check them.
