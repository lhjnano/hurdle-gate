"""run_smoke.sh 판정의 pytest 이식 — subprocess 대신 hurdle.cli.main()을 직접 호출한다.

원본 fixtures는 오염시키지 않는다(사본 사용은 run_smoke.sh의 pristine-copy 패턴 참조).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hurdle.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# 무설정 베이스 판정 — 스모크 1단계와 동일한 기대표(원본 8종 + configless 신규 4종).
CONFIGLESS_EXPECT = {
    "go/pkg/calc.go": "ok",
    "go/pkg/util.go": "ok",
    "go/pkg/sub/deep.go": "gap",
    "py/app.py": "ok",
    "py/lonely.py": "gap",
    "ts/a.ts": "ok",
    "ts/b.ts": "gap",
    "other/note.txt": "unmapped",
    "c/mod1/x.c": "ok",  # 모듈명이 C 테스트 경로에 등장 (heuristic)
    "c/mod2/y.c": "gap",
    "c/mod3/z.c": "gap",  # module_map 미로딩
    "excluded/skip.go": "gap",  # exclude 미로딩
}


def pristine_copy(tmp_path):
    """원본 fixtures의 사본에서 .hurdle.json을 제거해 무설정 상태를 만든다."""
    dst = tmp_path / "tree"
    shutil.copytree(FIXTURES, dst)
    (dst / ".hurdle.json").unlink()
    return dst


def load_report(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_configless_base_verdicts(tmp_path, capsys):
    tree = pristine_copy(tmp_path)
    out = tmp_path / "report.json"
    assert main(["scan", str(tree), "--json", str(out)]) == 0
    data = load_report(out)
    # 8파일 기존 판정(+신규 4종) 일치, 그리고 예상 밖 파일 없음
    assert {r["path"]: r["status"] for r in data["files"]} == CONFIGLESS_EXPECT
    assert data["summary"]["total"] == 12
    conf = {r["path"]: r["confidence"] for r in data["files"]}
    assert conf["go/pkg/calc.go"] == "exact"
    assert conf["py/lonely.py"] == "exact"
    for path in ("c/mod1/x.c", "c/mod2/y.c", "c/mod3/z.c"):
        assert conf[path] == "heuristic"
    assert "total=12" in capsys.readouterr().out


def test_config_autodiscovery(tmp_path):
    out = tmp_path / "report.json"
    assert main(["scan", str(FIXTURES), "--json", str(out)]) == 0
    data = load_report(out)
    by = {r["path"]: r for r in data["files"]}
    assert by["excluded/skip.go"]["status"] == "excluded"
    assert by["py/lonely.py"]["status"] == "allowed"
    assert by["py/lonely.py"]["reason"] == "deliberately untested fixture"
    assert by["c/mod1/x.c"]["status"] == "ok"
    assert by["c/mod2/y.c"]["status"] == "gap"
    # module_map 키워드가 C 테스트 파일 내용(killer.c)에서 발견된 경로
    assert by["c/mod3/z.c"]["status"] == "ok"
    assert by["c/mod3/z.c"]["matched_test"] == "c/tests/killer.c"
    summary = data["summary"]
    assert (summary["excluded"], summary["allowed"]) == (1, 1)
    assert summary["gap"] >= 1
    assert Path(data["config"]).name == ".hurdle.json"  # PATH/.hurdle.json 자동 탐색
    assert data["mode"] == "full"


def test_strict_returns_1_when_gap_exists():
    assert main(["scan", str(FIXTURES), "--strict"]) == 1


def test_strict_returns_0_when_no_gap(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.go").write_text("package pkg\n")
    (pkg / "a_test.go").write_text("package pkg\n")
    assert main(["scan", str(tmp_path), "--strict"]) == 0


def test_diff_on_non_git_path_exits_2(tmp_path):
    (tmp_path / "a.go").write_text("package x\n")
    with pytest.raises(SystemExit) as excinfo:
        main(["scan", str(tmp_path), "--diff", "HEAD"])
    assert excinfo.value.code == 2


def test_json_report_schema(tmp_path):
    tree = pristine_copy(tmp_path)
    out = tmp_path / "report.json"
    assert main(["scan", str(tree), "--json", str(out)]) == 0
    data = load_report(out)
    assert set(data) >= {
        "path", "generated_at", "mode", "base", "config", "summary", "files",
    }
    assert set(data["summary"]) == {
        "total", "ok", "gap", "unmapped", "excluded", "allowed", "by_lang",
    }
    assert data["files"] and all(set(r) >= {"path", "lang", "status"} for r in data["files"])


def test_diff_judges_only_changed_files(tmp_path):
    tree = pristine_copy(tmp_path)
    git = ["git", "-C", str(tree)]
    for cmd in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=hurdle@example.com", "-c", "user.name=hurdle", "commit", "-qm", "init"],
    ):
        subprocess.run(git + cmd, check=True, capture_output=True)
    with open(tree / "ts" / "b.ts", "a") as fh:  # 커밋되지 않은 수정 1건
        fh.write("// touched\n")
    out = tmp_path / "diff.json"
    assert main(["scan", str(tree), "--diff", "HEAD", "--json", str(out)]) == 0
    data = load_report(out)
    by = {r["path"]: r for r in data["files"]}
    assert set(by) == {"ts/b.ts"}
    assert by["ts/b.ts"]["status"] == "gap"
    assert data["mode"] == "diff"
    assert data["base"] == "HEAD"
