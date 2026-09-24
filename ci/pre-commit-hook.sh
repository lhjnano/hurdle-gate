#!/usr/bin/env bash
# hurdle pre-commit hook — 커밋 대상(HEAD 대비) 소스 중 무테스트 신규 파일을 차단.
# 설치: cp ci/pre-commit-hook.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
set -euo pipefail
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  [ -n "$(git diff --name-only --diff-filter=ACMR HEAD)" ] || { echo "hurdle: 변경 소스 없음 — 스킵"; exit 0; }
fi
# git 저장소 밖이면 --diff 가 오류(exit 2)로 끝난다 — 정상 동작이다.
exec hurdle scan . --diff HEAD --strict
