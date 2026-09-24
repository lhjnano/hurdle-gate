# Changelog

이 프로젝트의 모든 눈에 보이는 변경은 이 파일에 기록한다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를, 버전 매기기는
[SemVer](https://semver.org/lang/ko/)를 따른다.

## [0.1.0] - 2026-09-24

### Added

- `scan` 서브커맨드 — 소스↔테스트 파일 존재 매핑 (go·py·ts/js exact,
  c/셸 module-aggregated heuristic).
- `--diff BASE` / `--strict` 게이트 모드 — 기준점 대비 신규·변경 파일만 판정하고
  갭 존재 시 실패(비-git 경로에서 `--diff`는 exit 2).
- 설정 파일 `.hurdle.json` — `exclude` / `allowlist` / `module_map`,
  스캔 경로 단위 자동 탐색.
- `--json` 기계 판독형 리포트(파일 단위 상태 + 요약).
- 4개 저장소 베이스라인 — kopia·lustre·longhorn-manager·velero
  (`baselines/`, [BASELINES.md](BASELINES.md)).
- GitHub Actions 게이트 템플릿(`ci/test-exist-gate.yml`)과
  pre-commit 훅(`ci/pre-commit-hook.sh`).
