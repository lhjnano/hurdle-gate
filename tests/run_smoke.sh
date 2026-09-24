#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TOOL() { PYTHONPATH="$HERE/../src" python3 -m hurdle "$@"; }
FIXTURES="$HERE/fixtures"
CONFIG="$FIXTURES/.hurdle.json"
OUT=/tmp/smoke.json
BASEDIR=$(mktemp -d)
DIFFDIR=$(mktemp -d)
NONGIT=$(mktemp -d)
trap 'rm -rf "$BASEDIR" "$DIFFDIR" "$NONGIT"' EXIT

# --- 1) configless base run (pristine copy without .hurdle.json):
#        original 8 verdicts preserved + new fixtures' configless verdicts
cp -r "$FIXTURES"/. "$BASEDIR"/
find "$BASEDIR" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
rm -f "$BASEDIR/.hurdle.json"
TOOL scan "$BASEDIR" --json "$OUT" >/dev/null

python3 - "$OUT" <<'PYEOF'
import json
import sys

EXPECT = {
    "go/pkg/calc.go": "ok",
    "go/pkg/util.go": "ok",
    "go/pkg/sub/deep.go": "gap",
    "py/app.py": "ok",
    "py/lonely.py": "gap",
    "ts/a.ts": "ok",
    "ts/b.ts": "gap",
    "other/note.txt": "unmapped",
    # new fixtures, configless verdicts:
    "c/mod1/x.c": "ok",         # module name in a C test path (heuristic)
    "c/mod2/y.c": "gap",
    "c/mod3/z.c": "gap",        # module_map not loaded yet
    "excluded/skip.go": "gap",  # exclusion not loaded yet
}

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)

files = {r["path"]: r["status"] for r in data["files"]}
fails = []
for path, want in EXPECT.items():
    got = files.get(path)
    if got != want:
        fails.append("  %s: expected=%s actual=%r" % (path, want, got))
extras = sorted(set(files) - set(EXPECT))
if extras:
    fails.append("  unexpected files in report: %s" % ", ".join(extras))
conf = {r["path"]: r["confidence"] for r in data["files"]}
for path in ("go/pkg/calc.go", "py/lonely.py"):
    if conf.get(path) != "exact":
        fails.append("  %s: confidence expected=exact actual=%r" % (path, conf.get(path)))
for path in ("c/mod1/x.c", "c/mod2/y.c", "c/mod3/z.c"):
    if conf.get(path) != "heuristic":
        fails.append("  %s: confidence expected=heuristic actual=%r" % (path, conf.get(path)))
if data["summary"]["total"] != 12:
    fails.append("  summary total expected=12 actual=%r" % data["summary"]["total"])
if fails:
    print("SMOKE FAIL (base)")
    print("\n".join(fails))
    sys.exit(1)
PYEOF

# --- 2) config run via AUTO-DISCOVERY (PATH/.hurdle.json):
#        excluded / allowed(+reason) / module_map keyword in test content
TOOL scan "$FIXTURES" --json "$OUT" >/dev/null

python3 - "$OUT" <<'PYEOF'
import json
import sys

EXPECT = {
    "excluded/skip.go": "excluded",
    "py/lonely.py": "allowed",
    "c/mod1/x.c": "ok",
    "c/mod2/y.c": "gap",
    "c/mod3/z.c": "ok",  # module_map keyword found in killer.c content
}

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)

by = {r["path"]: r for r in data["files"]}
fails = []
for path, want in EXPECT.items():
    got = (by.get(path) or {}).get("status")
    if got != want:
        fails.append("  %s: expected=%s actual=%r" % (path, want, got))
if (by.get("py/lonely.py") or {}).get("reason") != "deliberately untested fixture":
    fails.append("  py/lonely.py: reason wrong: %r" % (by.get("py/lonely.py") or {}).get("reason"))
if (by.get("c/mod3/z.c") or {}).get("matched_test") != "c/tests/killer.c":
    fails.append("  c/mod3/z.c: matched_test wrong: %r" % (by.get("c/mod3/z.c") or {}).get("matched_test"))
s = data["summary"]
if s["excluded"] != 1 or s["allowed"] != 1 or s["gap"] < 1:
    fails.append("  summary wrong: %r" % s)
if not (data.get("config") or "").endswith(".hurdle.json"):
    fails.append("  config auto-discovery failed: %r" % data.get("config"))
if data.get("mode") != "full":
    fails.append("  mode expected=full actual=%r" % data.get("mode"))
if fails:
    print("SMOKE FAIL (config)")
    print("\n".join(fails))
    sys.exit(1)
PYEOF

# --- 3) --diff mode: temp git repo, modify one file, only it is judged
cp -r "$FIXTURES"/. "$DIFFDIR"/
find "$DIFFDIR" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
rm -f "$DIFFDIR/.hurdle.json"
git -C "$DIFFDIR" init -q >/dev/null 2>&1
git -C "$DIFFDIR" add -A
git -C "$DIFFDIR" -c user.email=hurdle@example.com -c user.name=hurdle commit -qm init
printf '// touched\n' >> "$DIFFDIR/ts/b.ts"

TOOL scan "$DIFFDIR" --diff HEAD --json "$OUT" >/dev/null

python3 - "$OUT" <<'PYEOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
by = {r["path"]: r for r in data["files"]}
fails = []
if set(by) != {"ts/b.ts"}:
    fails.append("  diff judged wrong file set: %r" % sorted(by))
r = by.get("ts/b.ts") or {}
if r.get("status") != "gap":
    fails.append("  ts/b.ts: expected=gap actual=%r" % r.get("status"))
if data.get("mode") != "diff" or data.get("base") != "HEAD":
    fails.append("  meta wrong: mode=%r base=%r" % (data.get("mode"), data.get("base")))
if fails:
    print("SMOKE FAIL (diff)")
    print("\n".join(fails))
    sys.exit(1)
PYEOF

# --- 4) --diff on a non-git directory must exit 2
printf 'package x\n' > "$NONGIT/a.go"
set +e
TOOL scan "$NONGIT" --diff HEAD >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 2 ]; then
  echo "SMOKE FAIL: --diff on non-git expected exit 2, got $rc" >&2
  exit 1
fi

# --- 5) --strict still exits 1 when a gap exists (gaps remain under config)
set +e
TOOL scan "$FIXTURES" --strict >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "SMOKE FAIL: --strict expected exit 1, got $rc" >&2
  exit 1
fi

echo "SMOKE PASS"
