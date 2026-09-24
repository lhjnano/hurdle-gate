# hurdle

A source ↔ test **existence mapping** tool. A single-file executable that finds
source files added without tests (Python 3 standard library only, zero external
dependencies).

**What it does** — decides from filename/path conventions alone whether each
source file has a corresponding test, and reports the gaps (untested sources).
Text is the default output; `--json` produces a machine-readable report.

**What it does not do**
- Does not **run** tests — existence only; whether tests pass is out of scope.
- Does not measure **coverage** — this is a different (and far cheaper) signal
  than line/branch coverage: "does this file have any test at all?"
- Does not judge code **quality** — a test file that exists but is thin will
  not be caught.

## Installation

```bash
# Recommended: isolated install via pipx
pipx install .

# Development: venv + editable install (includes dev extras)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# Environments where pip is unavailable (PEP 668 etc.): runs without installing
PYTHONPATH=src python3 -m hurdle scan .
```

## Quick start

```bash
# 1) Full scan — gap report for the whole repository (use this to create a baseline)
hurdle scan ~/study/kopia --json kopia.json

# 2) diff mode — evaluate only sources new/changed vs. a base point (core of the local/CI gate)
hurdle scan . --diff origin/main

# 3) strict mode — fail (non-zero exit code) if any evaluated file has a gap
hurdle scan . --diff origin/main --strict --config .hurdle.json
```

Reading the output: the report shows a per-file status (`matched` / `gap` /
`unmapped` — files with unknown extensions are counted only as `unmapped` and
excluded from language totals), each file's matching test and confidence
(`exact`/`heuristic`), and per-language totals. Exit codes under `--strict`:
no gaps = 0, gaps present = failure, runtime error (e.g. `--diff` outside a
git repository) = 2. CI decides pass/fail from the strict-mode exit code.

## Verdict rules (per language)

| Language | Test-existence verdict | confidence |
|---|---|---|
| **go** | Package-level: an exact `{stem}_test.go` match wins first; otherwise covered if any `*_test.go` exists in the same package (directory) | exact |
| **py** | Probes 4 pytest-convention candidate paths — beside the file / in a `tests/` directory × `test_{stem}.py` / `{stem}_test.py` combinations — plus variant names `tests/test_{stem}_*.py` and `tests/test_*_{stem}.py` (v0.2.0). `__init__.py` counts as a package marker and non-test files under `test_dirs` (default `tests`, `test`) count as test-support — both excluded rather than gapped (config: `strict_init`, `test_dirs`) | exact |
| **ts/js** | Naming conventions: the `*.test.ts(x)` / `*.spec.ts(x)` families | exact |
| **c / shell** | File-to-file mapping is impossible in trees like lustre (centralized `lustre/tests/` + `kunit/`), so coverage is aggregated per module/directory (heuristic). Listing module→test keywords in `module_map` improves accuracy | heuristic |

## Configuration (.hurdle.json)

Passed via `--config`. See `.hurdle.example.json` in this repository for a
minimal example and `baselines/*.hurdle.json` for real-world ones.

```jsonc
{
  "exclude": ["vendor/", "**/*_pb.go"],        // kept out of the scan
  "allowlist": { "cmd/legacy/main.go": "thin wrapper; covered in pkg/" },
  "module_map": { "lustre/osd-zfs": ["osd", "conf-sanity"] }
}
```

| Key | Format | Description |
|---|---|---|
| `exclude` | array of strings | Directories are excluded wholesale with a trailing `/` in the name (`vendor/`). Everything else is an fnmatch pattern matched against full paths/filenames (`**/*_pb.go`) |
| `allowlist` | relpath → reason string | Do not count this file as a gap (escape hatch). Checked **before exclude**, so a file with an explicit reason survives even broad exclude patterns. The reason stays on record in commit history |
| `module_map` | module relpath → keyword array | Feeds the C/shell heuristic. List the test-suite keywords that cover a module (e.g. `["sanity", "conf-sanity"]`) and module coverage is looked up in the centralized tests/ directory |

## Baseline → gate workflow

The core design is a **ratchet**: existing gaps are frozen, and only new gaps
are blocked.

1. **Capture a baseline** — run a full scan, commit the resulting JSON gap
   report (covering all existing code) to the repository. This becomes a
   de-facto allowlist. The actual results of doing this for the kopia/lustre/
   longhorn-manager/velero repositories are in [BASELINES.md](BASELINES.md)
   and `baselines/*.json`.
2. **Classify with config** — filter generated code (`*_pb.go` etc.), vendor,
   and test-support code (`internal/testutil` etc.) via `exclude`/`allowlist`
   so that only files with genuinely no corresponding test remain in the
   baseline.
3. **diff + strict gate** — in CI, `--diff origin/<base> --strict` judges only
   the files changed now. Legacy gaps never show up in the diff and are
   ignored; only new/modified files are forced to carry tests. The gap count
   decreases monotonically.

## CI integration

Copy `ci/test-exist-gate.yml` to `.github/workflows/test-exist-gate.yml` in the
target repository and follow the 4 steps in the comment block at the top of
the file (swap the URL, commit the config, mark the check as required). The
flow: `fetch-depth: 0` checkout → install hurdle → run
`scan . --diff origin/base --strict --config .hurdle.json --json` → upload the
report artifact even on failure (`if: always()`).

## pre-commit local hook

Copy `ci/pre-commit-hook.sh` to `.git/hooks/pre-commit`, or use this minimal
3-line form:

```bash
#!/bin/sh
[ -n "$(git diff --name-only --diff-filter=ACMR HEAD)" ] || exit 0
exec hurdle scan . --diff HEAD --strict
```

## Limitations (honestly)

- **It only checks file existence.** It never sees whether tests run, pass, or
  assert anything meaningful. It is a minimal gate against "source added with
  no test" — not a coverage replacement.
- **Heuristic module verdicts can over- and under-count.** The module-aggregated
  C/shell verdict depends on `module_map` keywords: keywords that are too
  broad over-report coverage; a missing per-module suite under-reports it.
  Treat the report's confidence markers as the trust boundary.
- **The only escape hatch is the allowlist.** When a rule misjudges a file,
  allowlisting it with a reason is the sole exception path — hiding it with
  exclude removes it from the scan entirely and breaks gap tracking.

## License

Apache-2.0 — see the [LICENSE](LICENSE) file for the full text.

## Universe coverage (`hurdle universe`)

Beyond per-file test existence, hurdle can enforce coverage of a
**defined universe** — a complete set of items every one of which must be
either used, wildcard-covered, or explicitly allowlisted. The motivating
case: CDP protocol commands/events (`protocol.json` defines the complete
universe, so "missing something" is well-defined).

```jsonc
// .hurdle.json
"universes": {
  "cdp-commands": {
    "items_file": "universes/cdp-commands.json",   // bare array or {"items":[], "meta":{}}
    "include": ["src/**/*.py"],
    "literal_shape": "^[A-Z][A-Za-z0-9]*\\.[a-zA-Z][A-Za-z0-9]+$",
    "wildcard_patterns": ["\\.subscribe\\(\\s*\"({domain})\\.\\*\""],
    "extra_usage": ["Page.javascriptDialogOpening"],
    "allowlist": {"Tracing.*": "out of scope — low-level tracing"}
  }
}
```

```bash
hurdle universe cdp-commands . --strict --json report.json
```

- Usage extraction collects shape-matched string literals (module
  constants are picked up at their definition site) and intersects them
  with the universe — universe membership itself disambiguates commands
  vs events that share the `Domain.name` shape.
- Statuses: `covered` / `wildcard` (a `Domain.*` subscription) /
  `allowed` (fnmatch on item names, reason recorded) / `gap`.
- `--strict` exits 1 on any gap that is not allowlisted — newly added
  universe items cannot appear silently.
