# 기여 가이 (CONTRIBUTING)

## 개발 환경

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Python 3.9+ 표준 라이브러리만 사용한다(런타임 외부 의존성 0). dev 의존성은 pytest뿐이다.

## 검증

```bash
make test    # pytest (tests/test_cli.py)
make smoke   # bash tests/run_smoke.sh — 판정 회귀 스모크
make check   # dogfood — hurdle scan . --strict (자기 자신을 게이트)
```

## 언어 컨벤션 추가

새 언어의 "테스트 존재" 규칙을 추가하는 절차:

1. `src/hurdle/cli.py`의 `classify()`에 확장자 → `(lang, kind)` 분기를,
   `test_candidates()`에 매핑 후보 경로를 추가한다.
2. `tests/fixtures/`에 최소 케이스(covered / gap 최소 1개씩)를 추가한다.
3. `tests/test_cli.py`의 기대표(`CONFIGLESS_EXPECT`)에 판정 단언을 추가한다.

C/셸처럼 파일 1:1 매핑이 불가능한 구조는 `module_map` 키워드 기반
module-aggregated heuristic으로 판정하고, confidence는 `heuristic`을 유지한다.

## config 스키마 변경

`.hurdle.json` 스키마(`exclude` / `allowlist` / `module_map`)를 바꾸면
`.hurdle.example.json`과 README의 설정표를 같이 갱신해야 한다.

## PR 체크리스트

- [ ] `pytest` 통과
- [ ] `bash tests/run_smoke.sh` 통과
- [ ] `hurdle scan . --strict` 통과
- [ ] 사용자에게 보이는 변경이면 `CHANGELOG.md`에 항목 추가
