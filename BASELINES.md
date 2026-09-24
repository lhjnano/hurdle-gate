# hurdle Baselines — 2026-09-24

Full-scan results (covering all existing code) for 4 repositories. Generated
code and test-support code were classified out with `--config`; the remaining
`gap`s form the baseline of "files with genuinely no corresponding test".

| Repository | total | ok | gap | excluded | allowed | unmapped | Primary language |
|---|---|---|---|---|---|---|---|
| kopia | 876 | 601 | **41** | 68 | 21 | 145 | go |
| lustre | 2,129 | 345 | **165** | 297 | 1 | 1,321 | c (module-aggregated) |
| longhorn-manager | 7,776 | 200 | **215** | 6,633 | 0 | 728 | go |
| velero | 3,535 | 415 | **284** | 0 | 0 | 2,836 | go |

Note: `~/study/longhorn` is a chart/deploy/docs repository (no Go sources), so
it was replaced with `~/study/longhorn-manager`, which holds the actual Go
code.

Footnote: the `gap` column sums all languages (longhorn-manager 215 = go 213 +
c 2; velero 284 = go 262 + c 20 + js 2). The numbers in the per-repository
sections below are by primary language.

---

## kopia — `kopia.json` (config: `kopia.hurdle.json`)

- go: ok=601 / gap=41 (93.6%); js: 7 files absorbed into the allowlist (v2 snapshots)
- exclude: `*.pb.go` (protobuf), `tests/`, `*.sh` + 21 allowlist entries (main.go, test-support packages such as internal/testutil·mockfs·testlogging, app/public/*.js Electron entries — reasons confirmed by spot-checking)
- gap Top 5: `internal/mount` (8), `internal/passwordpersist` (5), `internal/volumesizeinfo` (4), `internal/timetrack` (3), `internal/fault` (2)
- Spot-check: all 5 true positives (confirmed no *_test.go in the same directories)
- Remaining work: none — ready for the gate as-is

## lustre — `lustre.json` (config: `lustre.hurdle.json`)

- c: ok=345 / gap=165 (heuristic, module-aggregated), unmapped 1,321 (kernel build files and other non-sources)
- exclude: `contrib/`, `*.h` + allowlist: autogen.sh
- module_map registers 11 core modules: osd-zfs, osd-ldiskfs, mdt, mgs, mdc, osc, llite, lov, obdclass, ldlm, ptlrpc → mapped to representative suite keywords (sanity, conf-sanity, osd, …) against `lustre/tests/`·`kunit/`
- gap Top 5: `lustre/utils/gss` (20), `lustre/ptlrpc/gss` (13), `lustre/target` (12), `lustre/ofd` (11), `lustre/mdd` (10)
- Interpretation: GSS/security code and the target/ofd/mdd server-side modules line up exactly with the weak coverage of heatmap columns G (security) and D (recovery) — cross-validated against the qualitative judgment of the heatmap analysis
- Remaining work: extending module_map to all 22 components would give a 1:1 mapping to heatmap rows (components)

## longhorn-manager — `longhorn-manager.json` (config: `longhorn-manager.hurdle.json`)

- go: ok=200 / gap=213 (48.4%), excluded 6,633 = vendor/ 6,374 + k8s codegen 235 (k8s/pkg/client/* — 235 files verified to carry the "Code generated" header) + zz_generated*
- gap Top 5: `client` (90), `k8s/pkg/apis/longhorn/v1beta2` (30), `metrics_collector` (16), `webhook/admission` (5), `webhook/server` (5)
- Interpretation: `client/` is not code-generated (no header) → a genuine gap. The k8s API type definitions (v1beta2) are also territory upstream does not test
- Remaining work: decide the policy — exclude the v1beta2 type definitions, or register them in the allowlist with a reason

## velero — `velero.json` (untuned original)

- go: ok=415 / gap=262 (61.3%), no config applied
- gap Top 5: `pkg/test` (18), `test/util/k8s` (17), `hack` (15), `pkg/plugin/generated` (13), `pkg/cmd/cli/schedule` (8)
- Remaining work: test-support/codegen directories such as `pkg/test`, `test/util`, `hack`, `pkg/plugin/generated` need config classification — planned as one pass, same pattern as kopia

---

## Next steps

These JSONs become the diff gate's **baseline (a de-facto allowlist)**.
`hurdle scan --diff origin/main --strict` judges only the files changed now, so
the 41–284 legacy gaps are never gate targets — **only new/modified files are
forced to carry tests**. Once the velero config is tuned, all 4 repositories
can turn the gate on.
