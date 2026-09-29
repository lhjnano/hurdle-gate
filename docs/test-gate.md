# Test-Existence Gate (`hurdle scan`)

> Core question: "Does this source file have a test?" — existence only, never quality.

## The Problem

As a codebase grows, source files merged without tests accumulate silently. By the time you notice, there are too many to know where to start. Coverage tools help but (1) require execution, (2) are slow, and (3) "0% coverage" and "no test file at all" are different signals.

## The Approach

`hurdle scan` judges source↔test correspondence from **filename conventions alone**. It never runs tests, never measures coverage, never judges quality. It answers exactly one question: "does a corresponding test file exist?"

## Verdict Rules

| Language | Verdict | Confidence |
|---|---|---|
| **Go** | Exact `{stem}_test.go` match wins first; otherwise covered if any `*_test.go` exists in the same package (directory) | exact |
| **Python** | Probes 4 pytest-convention paths (`test_{stem}.py` / `{stem}_test.py` × beside the file / in `tests/`). Variant names `test_{stem}_*.py` and `test_*_{stem}.py` also match via fnmatch | exact |
| **TS/JS** | `{stem}.test.{ext}` / `{stem}.spec.{ext}` conventions | exact |
| **C/shell** | File-to-file mapping is impossible in trees with centralized test directories → module-aggregated heuristic. `module_map` keywords improve accuracy | heuristic |

### Statuses

| Status | Meaning |
|---|---|
| `matched` | Corresponding test file exists |
| `gap` | No test — action needed |
| `unmapped` | Unknown extension (excluded from language totals) |
| `excluded` | Filtered out by config |
| `allowed` | Explicitly allowlisted (reason recorded) |

## Configuration (.hurdle.json)

```jsonc
{
  "exclude": ["vendor/", "**/*_pb.go"],
  "allowlist": {
    "cmd/legacy/main.go": "thin wrapper; covered in pkg/"
  },
  "module_map": {
    "lustre/osd-zfs": ["osd", "conf-sanity"]
  }
}
```

| Key | Format | Description |
|---|---|---|
| `exclude` | `string[]` | Directory (trailing `/`) or fnmatch pattern. Matching sources get `excluded` |
| `allowlist` | `{relpath: reason}` | Not counted as a gap. Reason stays on record in commit history |
| `module_map` | `{module: keywords}` | Feeds the C/shell heuristic. Maps modules to test-suite keywords |
| `test_dirs` | `string[]` | Directory names marking test context (default `["tests","test"]`) |
| `strict_init` | `bool` | When `true`, `__init__.py` is judged as a normal source file |

## The Ratchet Workflow

Existing gaps are frozen; only new gaps are blocked:

```bash
# 1. Capture a baseline — full scan → commit the JSON report
hurdle scan ~/project --json project.json
git add project.json && git commit -m "baseline: freeze existing gaps"

# 2. Classify with config — filter generated code, vendor, and
#    test-support via exclude/allowlist

# 3. CI gate — diff + strict
hurdle scan . --diff origin/main --strict --config .hurdle.json
```

This means:
- Legacy gaps never appear in the diff, so they're ignored
- Only new/modified files are forced to carry tests
- The gap count decreases monotonically

## Diff Mode

`--diff BASE` judges only files added/modified/renamed between BASE and HEAD, plus uncommitted working-tree changes. Test existence matching still uses the full worktree, so existing tests can cover new sources.

```bash
hurdle scan . --diff origin/main --strict
```

| Exit code | Meaning |
|---|---|
| 0 | No gaps (or not `--strict`) |
| 1 | Gaps present + `--strict` |
| 2 | Runtime error (not a git repo, etc.) |

## Universe (`hurdle universe`)

Beyond file existence, enforce completeness of a **defined item set** — "did we miss any?"

```jsonc
"universes": {
  "cdp-commands": {
    "items_file": "universes/cdp-commands.json",
    "include": ["src/**/*.py"],
    "literal_shape": "^[A-Z][A-Za-z0-9]*\\.[a-zA-Z][A-Za-z0-9]+$",
    "wildcard_patterns": ["\\.subscribe\\(\\s*\"({domain})\\.\\*\""],
    "extra_usage": ["Page.javascriptDialogOpening"],
    "allowlist": {"Tracing.*": "out of scope"}
  }
}
```

- Extracts string literals from source → intersects with universe → `covered`
- Wildcard subscriptions (`Domain.*`) → `wildcard`
- Allowlist (reason recorded) → `allowed`
- Everything else → `gap`

```bash
hurdle universe cdp-commands . --strict
```

## Limitations (Honestly)

- It never runs tests. Existence only.
- A thin test (asserts nothing) still passes.
- C/shell heuristics depend on `module_map` accuracy.
- The only escape hatch is the allowlist. Using `exclude` removes files from the scan entirely, breaking gap tracking.
