# hurdle Baselines — 2026-09-24

4개 저장소 전수 스캔(기존 코드 전체 포함) 결과. `--config`로 생성 코드/테스트 지원 코드를 분류했고,
남은 `gap`은 "정말 대응 테스트가 없는 파일"의 베이스라인이다.

| 저장소 | total | ok | gap | excluded | allowed | unmapped | 주 언어 |
|---|---|---|---|---|---|---|---|
| kopia | 876 | 601 | **41** | 68 | 21 | 145 | go |
| lustre | 2,129 | 345 | **165** | 297 | 1 | 1,321 | c (module-aggregated) |
| longhorn-manager | 7,776 | 200 | **215** | 6,633 | 0 | 728 | go |
| velero | 3,535 | 415 | **284** | 0 | 0 | 2,836 | go |

비고: `~/study/longhorn`은 차트/배포/문서 저장소(Go 소스 없음)여서 실제 Go 코드가 있는
`~/study/longhorn-manager`로 대체했다.

각주: 표의 `gap`은 전체 언어 합계(longhorn-manager 215 = go 213 + c 2, velero 284 = go 262 + c 20 + js 2).
아래 저장소별 섹션의 수치는 주 언어 기준.

---

## kopia — `kopia.json` (config: `kopia.hurdle.json`)

- go: ok=601 / gap=41 (93.6%), js: 7파일 allowlist 흡수(v2 스냅샷)
- exclude: `*.pb.go`(protobuf), `tests/`, `*.sh` + allowlist 21건(main.go, internal/testutil·mockfs·testlogging 등 테스트 지원 패키지, app/public/*.js Electron 엔트리 — 표본 검증으로 사유 확정)
- gap Top 5: `internal/mount`(8), `internal/passwordpersist`(5), `internal/volumesizeinfo`(4), `internal/timetrack`(3), `internal/fault`(2)
- 표본 검증: 5건 전부 정탐(같은 디렉토리에 *_test.go 부재 확인)
- 남은 과제: 없음 — 게이트 즉시 적용 가능 상태

## lustre — `lustre.json` (config: `lustre.hurdle.json`)

- c: ok=345 / gap=165 (heuristic, module-aggregated), unmapped 1,321(커널 빌드 파일 등 비소스)
- exclude: `contrib/`, `*.h` + allowlist: autogen.sh
- module_map 11개 핵심 모듈 등록: osd-zfs, osd-ldiskfs, mdt, mgs, mdc, osc, llite, lov, obdclass, ldlm, ptlrpc → 대표 슈트 키워드(sanity, conf-sanity, osd 등)로 `lustre/tests/`·`kunit/` 매핑
- gap Top 5: `lustre/utils/gss`(20), `lustre/ptlrpc/gss`(13), `lustre/target`(12), `lustre/ofd`(11), `lustre/mdd`(10)
- 해석: GSS/보안 계열과 target/ofd/mdd 서버측 모듈이 히트맵 G(보안)·D(리커버리) 열의 약한 커버리지와 정확히 일치 — 히트맵 분석의 정성 판단과 교차 검증됨
- 남은 과제: module_map을 22개 전체 컴포넌트로 확장하면 히트맵 행(컴포넌트)과 1:1 대응 가능

## longhorn-manager — `longhorn-manager.json` (config: `longhorn-manager.hurdle.json`)

- go: ok=200 / gap=213 (48.4%), excluded 6,633 = vendor/ 6,374 + k8s 코드젠 235(k8s/pkg/client/* — "Code generated" 헤더 235건 확인) + zz_generated*
- gap Top 5: `client`(90), `k8s/pkg/apis/longhorn/v1beta2`(30), `metrics_collector`(16), `webhook/admission`(5), `webhook/server`(5)
- 해석: `client/`는 hand-generated 아님(헤더 무음) → 실질 갭. k8s API 타입 정의(v1beta2)도 업스트림이 테스트하지 않는 영역
- 남은 과제: v1beta2 타입 정의를 exclude할지 allowlist로 사유 등록할지 정책 결정

## velero — `velero.json` (튜닝 전 원본)

- go: ok=415 / gap=262 (61.3%), config 미적용
- gap Top 5: `pkg/test`(18), `test/util/k8s`(17), `hack`(15), `pkg/plugin/generated`(13), `pkg/cmd/cli/schedule`(8)
- 남은 과제: `pkg/test`, `test/util`, `hack`, `pkg/plugin/generated` 등 테스트 지원/코드젠 디렉토리 config 분류 필요 — kopia와 동일 패턴으로 1회 처리 예정

---

## 다음 단계

이 JSON들이 diff 게이트의 **베이스라인(사실상의 allowlist)**이 된다. `hurdle scan --diff origin/main --strict`
조합은 이번에 바뀐 파일만 판정하므로, 레거시 gap 41~284개는 게이트 대상이 아니고 **신규·수정 파일에 테스트가
따라붙는 것만 강제**된다. velero config 튜닝 후 4개 저장소 전부 게이트 가동 가능.
