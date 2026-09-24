# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versioning follows [SemVer](https://semver.org/).

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
