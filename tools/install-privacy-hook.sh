#!/bin/sh
# Install the pre-commit hook that keeps the owner's own data out of this
# public repository. Run once per clone:
#
#     sh tools/install-privacy-hook.sh
#
# The hook checks staged content against tests/private_denylist.txt (gitignored,
# one regex per line) and, when $BRIEF_PRIVATE_DIR points at your filled-in
# Routine prompts, against the identifiers it finds there - so the values you
# already keep in one private place do not have to be listed twice.
#
#     export BRIEF_PRIVATE_DIR="$HOME/email-brief-prompts"
set -e
root=$(git rev-parse --show-toplevel)
hook="$root/.git/hooks/pre-commit"
cat > "$hook" <<'HOOK'
#!/bin/sh
exec python3 "$(git rev-parse --show-toplevel)/tools/privacy_precommit.py"
HOOK
chmod +x "$hook"
echo "installed $hook"
if [ ! -f "$root/tests/private_denylist.txt" ]; then
  echo "note: $root/tests/private_denylist.txt does not exist yet."
  echo "      Create it (it is gitignored) with one regex per line: your name,"
  echo "      employers, booking references, card last-fours, phone numbers."
fi
