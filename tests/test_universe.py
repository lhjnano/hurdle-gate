"""Universe coverage engine tests — calls hurdle.cli.main() directly.

Also the dogfood counterpart of src/hurdle/universe.py: this file is what
keeps the new module gated by hurdle's own scan.
"""

import json
import shutil
from pathlib import Path

import pytest

from hurdle.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures03"

DEMO_STATUS = {
    "Page.navigate": "covered",                   # inline literal in a send call
    "Page.printToPDF": "covered",                 # module-constant literal
    "Page.javascriptDialogOpening": "allowed",    # allowlisted with a reason
    "Page.close": "gap",                          # never used, never excused
    "Runtime.evaluate": "wildcard",               # subscribe("Runtime.*") pattern
    "Runtime.executionContextCreated": "covered", # extra_usage (dynamic composition)
}


def load_report(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def pristine_copy(tmp_path):
    dst = tmp_path / "tree"
    shutil.copytree(FIXTURES, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def test_four_states_and_domain_rollup(tmp_path, capsys):
    out = tmp_path / "u.json"
    assert main(["universe", "demo", str(FIXTURES), "--json", str(out)]) == 0
    data = load_report(out)
    assert {i["name"]: i["status"] for i in data["items"]} == DEMO_STATUS
    assert data["summary"] == {
        "total": 6, "covered": 3, "wildcard": 1, "allowed": 1, "gap": 1,
    }
    assert data["by_domain"]["Page"] == {
        "total": 4, "covered": 2, "wildcard": 0, "allowed": 1, "gap": 1,
    }
    assert data["by_domain"]["Runtime"] == {
        "total": 2, "covered": 1, "wildcard": 1, "allowed": 0, "gap": 0,
    }
    by_name = {i["name"]: i for i in data["items"]}
    assert by_name["Page.javascriptDialogOpening"]["allow_reason"]
    assert by_name["Page.navigate"]["allow_reason"] is None
    assert "hurdle universe: demo" in capsys.readouterr().out


def test_strict_gap_then_allowlist_resolution(tmp_path, capsys):
    tree = pristine_copy(tmp_path)
    assert main(["universe", "demo", str(tree), "--strict"]) == 1
    shutil.copy(FIXTURES / ".hurdle.allowed.json", tree / ".hurdle.json")
    assert main(["universe", "demo", str(tree), "--strict"]) == 0
    assert "gap=0" in capsys.readouterr().out


def test_literal_shape_filters_collection(tmp_path):
    # "page.navigate" IS present as a quoted string in src/core.py, but the
    # default shape (uppercase domain) rejects the capture, so the bare-array
    # universe reports it as a gap.
    src = (FIXTURES / "src" / "core.py").read_text(encoding="utf-8")
    assert '"page.navigate"' in src
    out = tmp_path / "u.json"
    assert main(["universe", "shape-demo", str(FIXTURES), "--json", str(out)]) == 0
    data = load_report(out)
    assert data["summary"] == {
        "total": 1, "covered": 0, "wildcard": 0, "allowed": 0, "gap": 1,
    }
    assert data["items"][0]["domain"] == "page"


def test_unknown_universe_name_exits_2():
    with pytest.raises(SystemExit) as excinfo:
        main(["universe", "nope", str(FIXTURES)])
    assert excinfo.value.code == 2


def test_json_report_schema(tmp_path):
    out = tmp_path / "u.json"
    assert main(["universe", "demo", str(FIXTURES), "--json", str(out)]) == 0
    data = load_report(out)
    assert set(data) == {"universe", "meta", "summary", "by_domain", "items"}
    assert data["universe"] == "demo"
    assert data["meta"]["version"] == "1.0"  # items_file meta passes through
    assert set(data["summary"]) == {"total", "covered", "wildcard", "allowed", "gap"}
    assert all(
        set(i) == {"name", "domain", "status", "allow_reason"} for i in data["items"]
    )
