# hurdle

소스 파일 ↔ 테스트 파일의 **존재 매핑** 도구. 테스트 없이 추가된 소스 파일을 찾아내는
단일 실행 파일이다 (Python 3 표준 라이브러리 전용, 외부 의존성 0).

**하는 것** — 파일명/경로 규칙으로 각 소스에 대응하는 테스트의 존재를 판정하고, 갭(무테스트
소스)을 리포트로 출력한다. 텍스트가 기본이고 `--json`으로 기계 판독형 리포트도 낸다.

**하지 않는 것**
- 테스트 **실행**은 하지 않는다 — 존재만 확인하며, 테스트가 통과하는지는 보지 않는다.
- **커버리지** 측정은 하지 않는다 — 라인/브랜치 커버리지가 아니라 "테스트가 아예 없는가"라는
  별개의(그리고 훨씬 싼) 신호다.
- 코드 **품질** 판정은 하지 않는다 — 테스트 파일이 존재해도 내용이 빈약하면 잡아내지 못한다.

## 설치 (Install)

```bash
# 권장: pipx로 격리 설치
pipx install .

# 개발용: venv + 편집 가능 설치(dev 의존성 포함)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# pip을 쓸 수 없는 환경(PEP 668 등)에서는 설치 없이도 실행된다:
PYTHONPATH=src python3 -m hurdle scan .
```

## 빠른 시작

```bash
# 1) 전수 스캔 — 리포지토리 전체의 갭 리포트 (베이스라인 생성용)
hurdle scan ~/study/kopia --json kopia.json

# 2) diff 모드 — 기준점 대비 신규·변경된 소스만 평가 (로컬/CI 게이트의 핵심)
hurdle scan . --diff origin/main

# 3) strict 모드 — 평가 대상 중 갭이 하나라도 있으면 실패(0이 아닌 종료 코드)
hurdle scan . --diff origin/main --strict --config .hurdle.json
```

출력 해석: 리포트는 파일 단위 상태(`matched` / `gap` / `unmapped` — 확장자를 모르는 파일은
`unmapped`로만 집계되고 언어 합계에서 제외)와 각 파일의 매칭 테스트·신뢰도(`exact`/`heuristic`),
언어별 요계를 보여준다. `--strict`에서의 종료 코드: 갭 없음=0, 갭 존재=실패, 런타임 오류
(예: git 저장소 밖에서 `--diff`)=2. CI는 strict 모드의 종료 코드로 실패/성공을 판정한다.

## 판정 규칙 (언어별)

| 언어 | 테스트 존재 판정 | confidence |
|---|---|---|
| **go** | 패키지 단위: 정확한 `{stem}_test.go`가 있으면 그것이 1순위, 없으면 같은 패키지(디렉터리) 내 `*_test.go` 존재로 커버 판정 | exact |
| **py** | pytest 관례 후보 4경로 탐색 — 파일 옆/`tests/` 디렉터리 × `test_{stem}.py`/`{stem}_test.py` 조합 | exact |
| **ts/js** | 명명 규칙: `*.test.ts(x)` / `*.spec.ts(x)` 계열 | exact |
| **c / 셸** | 파일 1:1 매핑이 불가능한 구조(lustre처럼 `lustre/tests/` 중앙집중 + `kunit/`)라 모듈/디렉터리 단위 집계(heuristic). `module_map`에 모듈→테스트 키워드를 명시하면 정확도가 올라간다 | heuristic |

## 설정 (.hurdle.json)

`--config`로 지정. 최소 예시는 저장소의 `.hurdle.example.json`, 실사용 예는
`baselines/*.hurdle.json`을 참고.

```jsonc
{
  "exclude": ["vendor/", "**/*_pb.go"],        // 스캔 대상에서 제외
  "allowlist": { "cmd/legacy/main.go": "thin wrapper; pkg/ 에서 커버" },
  "module_map": { "lustre/osd-zfs": ["osd", "conf-sanity"] }
}
```

| 키 | 형식 | 설명 |
|---|---|---|
| `exclude` | 문자열 배열 | 디렉터리는 이름에 `/` 접미사(`vendor/`)로 쓰면 해당 디렉터리 전체 제외. 그 외는 fnmatch 패턴으로 전체 경로/파일명 매칭(`**/*_pb.go`) |
| `allowlist` | relpath → 사유 문자열 | 이 파일은 갭으로 세지 않는다(escape hatch). **exclude보다 먼저 검사**되므로, 명시적 사유가 있는 파일은 광범위한 exclude 패턴에 걸려도 살아남는다. 사유는 커밋 기록으로 남는다 |
| `module_map` | 모듈 relpath → 키워드 배열 | C/셸 heuristic 판정용. 해당 모듈을 커버하는 테스트 슈트 키워드(예: `["sanity", "conf-sanity"]`)를 나열하면 중앙집중식 tests/ 디렉터리에서 모듈 커버를 찾는다 |

## 베이스라인 → 게이트 워크플로우

핵심 설계는 **래칫(ratchet)**: 기존 갭은 고정하고, 새 갭의 발생만 막는다.

1. **베이스라인 확보** — 전수 스캔으로 기존 코드 전체를 포함한 갭 리포트 JSON을 만들어
   저장소에 커밋한다. 이것이 사실상의 allowlist가 된다. 실제로 kopia/lustre/
   longhorn-manager/velero 4개 저장소에 대해 수행한 결과는 [BASELINES.md](BASELINES.md)와
   `baselines/*.json` 참조.
2. **config로 분류** — generated 코드(`*_pb.go` 등), vendor, 테스트 지원 코드(`internal/testutil`
   등)를 `exclude`/`allowlist`로 걸러 "정말 대응 테스트가 없는 파일"만 베이스라인에 남긴다.
3. **diff + strict 게이트** — CI에서 `--diff origin/<base> --strict`로 이번에 바뀐 파일만
   판정한다. 레거시 갭은 diff에 잡히지 않아 무시되고, 신규·수정 파일에 테스트가 따라붙는 것만
   강제된다. 갭 수는 단조 감소한다.

## CI 통합

`ci/test-exist-gate.yml`을 대상 저장소의 `.github/workflows/test-exist-gate.yml`로 복사하고
파일 상단 주석의 4단계(URL 교체, config 커밋, required check 지정)를 따르면 된다.
`fetch-depth: 0` checkout → hurdle 설치 → `scan . --diff origin/base --strict --config
.hurdle.json --json` 실행 → 실패해도 리포트 아티팩트 업로드(`if: always()`) 순서다.

## pre-commit 로컬 훅

`ci/pre-commit-hook.sh`를 `.git/hooks/pre-commit`으로 복사하거나, 최소 형태는 다음 3줄이다:

```bash
#!/bin/sh
[ -n "$(git diff --name-only --diff-filter=ACMR HEAD)" ] || exit 0
exec hurdle scan . --diff HEAD --strict
```

## 한계 (정직하게)

- **파일 존재만 확인한다.** 테스트가 실행되는지, 통과하는지, 의미 있는 단언을 하는지는 전혀
  보지 못한다. "테스트 없이 소스만 추가"를 잡는 최소 게이트이지 커버리지 대체품이 아니다.
- **heuristic 모듈 판정은 과대/과소 모두 가능하다.** C/셸의 module-aggregated 판정은
  `module_map` 키워드에 의존하므로, 키워드가 너무 넓으면 커버로 과대평가, 모듈별 슈트가
  누락되면 과소평가된다. 리포트의 confidence 표기를 신뢰 기준으로 삼라.
- **escape hatch는 allowlist뿐이다.** 규칙이 잘못 판정하는 파일은 사유와 함께 allowlist에
  등록하는 것이 유일한 예외 경로다 — exclude로 숨기면 아예 스캔에서 사라져 갭 추적이
  끊긴다.

## License

Apache-2.0 — 전문은 [LICENSE](LICENSE) 파일 참조.
