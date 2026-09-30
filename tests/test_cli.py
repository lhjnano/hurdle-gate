"""pytest port of the run_smoke.sh verdicts — calls hurdle.cli.main() directly instead of a subprocess.

The original fixtures are left untouched (for the pristine-copy pattern, see run_smoke.sh).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from hurdle.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Configless base verdicts — the same expectation table as smoke stage 1 (8 original entries + 4 new configless ones).
CONFIGLESS_EXPECT = {
    "go/pkg/calc.go": "ok",
    "go/pkg/util.go": "ok",
    "go/pkg/sub/deep.go": "gap",
    "py/app.py": "ok",
    "py/lonely.py": "gap",
    "ts/a.ts": "ok",
    "ts/b.ts": "gap",
    "other/note.txt": "unmapped",
    "c/mod1/x.c": "ok",  # module name appears in the C test path (heuristic)
    "c/mod2/y.c": "gap",
    "c/mod3/z.c": "gap",  # module_map not loaded
    "excluded/skip.go": "gap",  # exclude not loaded
}


def pristine_copy(tmp_path):
    """Remove .hurdle.json from a copy of the original fixtures to produce a configless state."""
    dst = tmp_path / "tree"
    shutil.copytree(FIXTURES, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
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
    # The 8 original verdicts (+ 4 new ones) match, with no unexpected files
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
    # Path matched via a module_map keyword found in the C test file contents (killer.c)
    assert by["c/mod3/z.c"]["status"] == "ok"
    assert by["c/mod3/z.c"]["matched_test"] == "c/tests/killer.c"
    summary = data["summary"]
    assert (summary["excluded"], summary["allowed"]) == (1, 1)
    assert summary["gap"] >= 1
    assert Path(data["config"]).name == ".hurdle.json"  # PATH/.hurdle.json autodiscovery
    assert data["mode"] == "full"


def test_strict_returns_1_when_gap_exists():
    assert main(["scan", str(FIXTURES), "--strict"]) == 1


def test_v020_marker_support_and_variant(tmp_path, capsys):
    """v0.2.0 refinements on an isolated tree (cdpbrowser-style findings)."""
    tree = os.path.join(os.path.dirname(__file__), "fixtures02")
    out = tmp_path / "report.json"
    assert main(["scan", str(tree), "--json", str(out)]) == 0
    data = load_report(out)
    by = {r["path"]: r for r in data["files"]}
    # __init__.py is a package marker by default -> excluded, not a gap
    assert by["pkg/__init__.py"]["status"] == "excluded"
    assert "marker" in by["pkg/__init__.py"]["reason"]
    # non-test .py under tests/ is test-support -> excluded
    assert by["tests/helper_util.py"]["status"] == "excluded"
    assert "support" in by["tests/helper_util.py"]["reason"]
    # mod.py has no tests/test_mod.py, but tests/test_mod_extra.py is a
    # variant name (test_{stem}_*.py) -> ok with that match reported
    assert by["pkg/mod.py"]["status"] == "ok"
    assert by["pkg/mod.py"]["matched_test"] == "tests/test_mod_extra.py"
    assert data["summary"]["gap"] == 0


def test_strict_init_config_reincludes_marker(tmp_path):
    cfg = tmp_path / ".hurdle.json"
    cfg.write_text(json.dumps({"strict_init": True}))
    tree = os.path.join(os.path.dirname(__file__), "fixtures02")
    assert main(["scan", str(tree), "--config", str(cfg), "--json",
                 str(tmp_path / "r.json")]) == 0
    data = load_report(tmp_path / "r.json")
    by = {r["path"]: r for r in data["files"]}
    assert by["pkg/__init__.py"]["status"] == "gap"  # re-treated as source


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
    with open(tree / "ts" / "b.ts", "a") as fh:  # one uncommitted modification
        fh.write("// touched\n")
    out = tmp_path / "diff.json"
    assert main(["scan", str(tree), "--diff", "HEAD", "--json", str(out)]) == 0
    data = load_report(out)
    by = {r["path"]: r for r in data["files"]}
    assert set(by) == {"ts/b.ts"}
    assert by["ts/b.ts"]["status"] == "gap"
    assert data["mode"] == "diff"
    assert data["base"] == "HEAD"


# ─── JS/TS variant test lookup (v0.3.0) ─────────────────────────────


def _mk(tmp_path, rel, content="export const x = 1;\n"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_js_variant_test_dir_exact_match(tmp_path):
    """src/domain.ts ↔ test/domain.test.ts (separate test-dir layout) → ok."""
    _mk(tmp_path, "src/domain.ts")
    _mk(tmp_path, "test/domain.test.ts")
    out = tmp_path / "r.json"
    assert main(["scan", str(tmp_path), "--json", str(out)]) == 0
    by = {r["path"]: r for r in load_report(out)["files"]}
    assert by["src/domain.ts"]["status"] == "ok"
    assert by["src/domain.ts"]["matched_test"] == "test/domain.test.ts"


def test_js_variant_prefix_match_and_no_cross_match(tmp_path):
    """test/tui-render.test.ts maps src/tui.tsx (prefix variant) but must NOT
    claim src/tui-logic.ts — the separator keeps {stem} on word boundaries."""
    _mk(tmp_path, "src/tui.tsx")
    _mk(tmp_path, "src/tui-logic.ts")
    _mk(tmp_path, "test/tui-render.test.ts")
    out = tmp_path / "r.json"
    assert main(["scan", str(tmp_path), "--strict", "--json", str(out)]) == 1  # tui-logic gap
    by = {r["path"]: r for r in load_report(out)["files"]}
    assert by["src/tui.tsx"]["status"] == "ok"
    assert by["src/tui.tsx"]["matched_test"] == "test/tui-render.test.ts"
    assert by["src/tui-logic.ts"]["status"] == "gap"


def test_js_colocated_still_preferred(tmp_path, capsys):
    """Colocated tests keep working; variant lookup is only a fallback."""
    _mk(tmp_path, "src/util.ts")
    _mk(tmp_path, "src/util.test.ts")
    _mk(tmp_path, "test/util.test.ts")
    out = tmp_path / "r.json"
    assert main(["scan", str(tmp_path), "--json", str(out)]) == 0
    by = {r["path"]: r for r in load_report(out)["files"]}
    assert by["src/util.ts"]["status"] == "ok"
    assert by["src/util.ts"]["matched_test"] == "src/util.test.ts"
