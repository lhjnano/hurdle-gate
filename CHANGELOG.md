# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versioning follows [SemVer](https://semver.org/).

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
