# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versioning follows [SemVer](https://semver.org/).

## [0.4.0] - 2026-09-30

### Added

- `ai-gate` subcommand — AI best-practice pattern verification for
  LLM-calling code: built-in default gates (`llm-basic`, `function-calling`,
  `agent-loop`, `rag-integrity`, `ai-resilience`) from the AI Native study
  guide, user-defined gates via `.hurdle.json` (`ai_gates`), per-file
  allowlisting, `--defaults`/`--strict`/`--json` modes, and the paired
  `tool_call_id_correlation` check (tool_calls without tool_call_id).
- JS/TS variant test lookup for `scan` — mirrors `py_variant_test` (v0.2.0)
  for the common separate-test-dir layout (vitest/jest): `src/domain.ts` now
  maps to `test/domain.test.ts`, and prefix variants with a required `-`/`_`
  separator keep stems on word boundaries (`test/tui-render.test.ts` maps
  `src/tui.tsx` but not `src/tui-logic.ts`). Sibling extensions are tried
  (ts↔tsx, js↔jsx).

### Fixed

- `ai-gate` agent-loop detect false positives: the `while ... keyword` span
  is now bounded to 200 chars (an unbounded `[\s\S]*` matched a directory
  walk's `while stack:` plus argparse `action="store_true"` hundreds of
  lines apart); `ReAct` is matched case-sensitively (scoped `(?-i:...)`) so
  the "react" framework name in dependency tables no longer trips it; the
  `agent` keyword excludes the `User-Agent` HTTP header via lookbehind.

## [0.3.0] - 2026-09-24

### Added

- `universe` subcommand — coverage of a defined universe of items against
  actual source usage, enforcing "no silent gaps": every item must be
  covered, wildcard-covered, or allowlisted with a reason.
  - Universe = a JSON list of items (e.g. every CDP command/event); usage
    is extracted as shape-matched string literals from `include` globs and
    intersected with the universe (universe membership disambiguates
    commands vs events sharing the same `Domain.name` shape).
  - `wildcard_patterns` recognize `Domain.*`-style subscriptions;
    `extra_usage` is the escape hatch for dynamically built names.
  - Per-domain summary on the console, full `--json` report,
    `--strict` fails on any unallowlisted gap.
- Config section `universes` in `.hurdle.json`.

## [0.2.0] - 2026-09-24

### Changed

- Python test matching now also accepts variant names `tests/test_{stem}_*.py`
  and `tests/test_*_{stem}.py` (word-bounded) in addition to the exact
  `test_{stem}.py` candidates — discovered while gating cdpbrowser, where
  modules were tested as `test_recorder_unit.py` / `test_gapfill_library.py`.

### Added

- `__init__.py` is treated as a package marker (excluded with a visible
  reason) instead of an untested source; set `strict_init: true` in the
  config to judge it as a regular source again.
- Non-test `.py` files under configured `test_dirs` (default `["tests",
  "test"]`) are excluded as test-support modules instead of gaps.
- Unit tests for all of the above (`tests/fixtures02`).

### Fixed

- Gate template (`ci/test-exist-gate.yml`) install step now uses
  `pip install git+…@ref` — the previous `sudo install` referenced the
  pre-packaging root executable that no longer exists.

## [0.1.0] - 2026-09-24

### Added

- `scan` subcommand — source↔test file existence mapping (go·py·ts/js exact,
  c/shell module-aggregated heuristic).
- `--diff BASE` / `--strict` gate modes — judge only new/changed files against
  a base point and fail when gaps exist (`--diff` outside a git repository
  exits 2).
- `.hurdle.json` config file — `exclude` / `allowlist` / `module_map`, with
  auto-discovery per scan path.
- `--json` machine-readable report (per-file status + summary).
- Baselines for 4 repositories — kopia·lustre·longhorn-manager·velero
  (`baselines/`, [BASELINES.md](BASELINES.md)).
- GitHub Actions gate template (`ci/test-exist-gate.yml`) and a pre-commit
  hook (`ci/pre-commit-hook.sh`).
