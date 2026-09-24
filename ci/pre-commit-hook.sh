#!/usr/bin/env bash
# hurdle pre-commit hook — block untested files among the sources being committed (vs HEAD).
# Install: cp ci/pre-commit-hook.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
set -euo pipefail
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  [ -n "$(git diff --name-only --diff-filter=ACMR HEAD)" ] || { echo "hurdle: no changed sources — skipping"; exit 0; }
fi
# Outside a git repository, --diff ends with an error (exit 2) — that is expected behavior.
exec hurdle scan . --diff HEAD --strict
