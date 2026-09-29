#!/usr/bin/env python3
"""hurdle — minimal test gap scanner (stdlib only).

hurdle scan PATH [--json FILE] [--strict] [--config FILE] [--diff BASE]
Maps source files to their conventional test counterparts and reports gaps.
Go: *_test.go in the same directory (package-level convention).
Python: test_{stem}.py / {stem}_test.py next to the file, tests/test_{stem}.py
relative to the file's directory or the scan root; variant names
tests/test_{stem}_*.py and tests/test_*_{stem}.py match via fnmatch (the
required '_' separators keep {stem} on word boundaries). "__init__.py" is a
package marker (excluded) unless strict_init=true; non-test .py files under a
configured test_dirs directory (default ["tests","test"]) are excluded as
test-support modules.
JS/TS: {stem}.test.{ext} / {stem}.spec.{ext} next to the file.
C/shell (.c .h .cc .cpp .sh): module-aggregated heuristic mode. The module is
the directory holding the source file; a module is ok (confidence=heuristic)
when a registered module_map keyword appears in some C test file path or
content (content read with errors='replace', files up to 1MB only), or the
module name appears in some C test file path. Files named test_*/..._test or
living under tests/, test/ or kunit/ are C test files, not sources.
Config (--config FILE; default: PATH/.hurdle.json when present):
  exclude:   trailing "/" matches a directory name anywhere in the path;
             otherwise fnmatch glob matched against the relpath and the file
             name. Matching sources get status=excluded (counted, not gaps).
  allowlist: {"rel/path": "reason"} — exact relpath match; status=allowed
              with the reason shown in the report (wins over exclude).
  test_dirs:  directory names marking test context (default ["tests","test"]);
              non-test .py files under them are excluded as test-support.
  strict_init: when true, __init__.py is judged as a normal source file
              instead of a package marker.
  module_map: {"module-relpath-or-name": ["keyword", ...]} for the C heuristic.
--diff BASE: only judge files added/modified/renamed between BASE and HEAD,
plus uncommitted working-tree changes vs BASE; test existence matching still
uses the full worktree. PATH must be a git work tree (exit 2 otherwise).
Unmappable extensions are reported separately as "unmapped", not gaps.
"""

import argparse
import datetime
import fnmatch
import json
import os
import subprocess
import sys

JS_EXTS = {"ts", "tsx", "js", "jsx"}
C_EXTS = {"c", "h", "cc", "cpp", "sh"}
C_TEST_DIR_COMPONENTS = {"tests", "test", "kunit"}
MAX_CONTENT_BYTES = 1024 * 1024
DEFAULT_CONFIG_NAME = ".hurdle.json"


def die(msg):
    print("hurdle: %s" % msg, file=sys.stderr)
    sys.exit(2)


class Config:
    """Parsed .hurdle.json content; all keys optional."""

    def __init__(self, data):
        data = data or {}
        self.exclude = list(data.get("exclude") or [])
        self.allowlist = dict(data.get("allowlist") or {})
        self.module_map = dict(data.get("module_map") or {})
        self.strict_init = bool(data.get("strict_init", False))
        self.test_dirs = list(data.get("test_dirs") or ["tests", "test"])

    def exclusion_hit(self, rel):
        parts = rel.split("/")
        base = parts[-1]
        for pat in self.exclude:
            if pat.endswith("/"):
                if pat[:-1] in parts:
                    return True
            elif fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(base, pat):
                return True
        return False

    def allow_reason(self, rel):
        return self.allowlist.get(rel)

    def under_test_dir(self, rel):
        return any(p in self.test_dirs for p in rel.split("/"))

    def module_keywords(self, module_rel, module_name):
        kws = self.module_map.get(module_rel)
        if kws is None:
            kws = self.module_map.get(module_name)
        if kws is None:
            return []
        if isinstance(kws, str):
            kws = [kws]
        return list(kws)


def load_config(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return Config(json.load(fh))
    except (OSError, ValueError) as exc:
        die("cannot load config %s: %s" % (path, exc))


def classify(name, rel=None):
    """Return (lang, kind); kind is one of source/test/other."""
    root, ext = os.path.splitext(name)
    ext = ext.lstrip(".").lower()
    if ext == "go":
        return ("go", "test" if root.endswith("_test") else "source")
    if ext == "py":
        if name == "conftest.py" or root.startswith("test_") or root.endswith("_test"):
            return ("py", "test")
        if name == "__init__.py":
            return ("py", "marker")
        return ("py", "source")
    if ext in JS_EXTS:
        if root.endswith(".test") or root.endswith(".spec"):
            return (ext, "test")
        return (ext, "source")
    if ext in C_EXTS:
        parts = (rel or name).split("/")
        if (
            root.startswith("test_")
            or root.endswith("_test")
            or any(p in C_TEST_DIR_COMPONENTS for p in parts[:-1])
        ):
            return ("c", "test")
        return ("c", "source")
    return (ext, "other")


def walk(root):
    """Recursively collect file paths under root, skipping symlinks and hidden entries."""
    files = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if e.name.startswith(".") or e.is_symlink():
                continue
            if e.is_dir(follow_symlinks=False):
                stack.append(e.path)
            elif e.is_file(follow_symlinks=False):
                files.append(e.path)
    return sorted(files)


def go_tests_in_dir(d):
    try:
        return sorted(
            e.name
            for e in os.scandir(d)
            if e.name.endswith("_test.go") and e.is_file(follow_symlinks=False)
        )
    except OSError:
        return []


def test_candidates(path, lang, scan_root):
    d, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    if lang == "py":
        return [
            os.path.join(d, "test_" + stem + ".py"),
            os.path.join(d, stem + "_test.py"),
            os.path.join(d, "tests", "test_" + stem + ".py"),
            os.path.join(scan_root, "tests", "test_" + stem + ".py"),
        ]
    if lang in JS_EXTS:
        return [
            os.path.join(d, stem + ".test" + ext),
            os.path.join(d, stem + ".spec" + ext),
        ]
    return []


def py_variant_test(d, stem, scan_root, cfg, listing):
    """Variant test lookup for Python sources (v0.2.0).

    Matches tests/test_{stem}_*.py and tests/test_*_{stem}.py via fnmatch
    inside the configured test dirs next to the file (d) and at the scan
    root; the required '_' separators keep {stem} on word boundaries.
    Returns the matched absolute path or None.
    """
    patterns = ("test_%s_*.py" % stem, "test_*_%s.py" % stem)
    seen = set()
    for base in (d, scan_root):
        for td in cfg.test_dirs:
            tdir = os.path.normpath(os.path.join(base, td))
            if tdir in seen:
                continue
            seen.add(tdir)
            for fname in listing(tdir):
                if any(fnmatch.fnmatch(fname, p) for p in patterns):
                    return os.path.join(tdir, fname)
    return None


def c_module_status(rel, c_tests, read_content, cfg):
    """Heuristic verdict for one C/shell source file. Returns (status, matched_test)."""
    d = os.path.dirname(rel)
    module_rel = d if d else "."
    module_name = os.path.basename(d) if d else os.path.splitext(os.path.basename(rel))[0]
    for kw in cfg.module_keywords(module_rel, module_name):
        for t in c_tests:
            if kw in t:
                return "ok", t
        for t in c_tests:
            content = read_content(t)
            if content and kw in content:
                return "ok", t
    for t in c_tests:
        if module_name and module_name in t:
            return "ok", t
    return "gap", None


def check_git_repo(path):
    proc = subprocess.run(
        ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        die("%s is not a git work tree" % path)


def changed_files(path, base):
    """AMR files changed BASE...HEAD, plus uncommitted working-tree changes vs BASE."""
    cmds = (
        ["git", "-C", path, "diff", "--name-only", "--relative", "--diff-filter=AMR", base + "...HEAD"],
        ["git", "-C", path, "diff", "--name-only", "--relative", "--diff-filter=AMR", base],
    )
    changed = set()
    for cmd in cmds:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            die("git diff failed (%s): %s" % (base, proc.stderr.strip()))
        changed.update(line for line in proc.stdout.splitlines() if line)
    return changed


def scan(path, cfg=None, diff_base=None):
    root = os.path.abspath(path)
    if cfg is None:
        cfg = Config({})
    results = []
    go_cache = {}
    c_tests = []  # C/shell test relpaths, collected in pass 1
    c_contents = {}  # C test relpath -> content str, or None if too big/unreadable

    def read_c_test_content(rel):
        if rel not in c_contents:
            full = os.path.join(root, *rel.split("/"))
            try:
                if os.path.getsize(full) <= MAX_CONTENT_BYTES:
                    with open(full, "r", encoding="utf-8", errors="replace") as fh:
                        c_contents[rel] = fh.read()
                else:
                    c_contents[rel] = None
            except OSError:
                c_contents[rel] = None
        return c_contents[rel]

    # Pass 1: collect the C/shell test universe so module judgment sees it all.
    for f in walk(root):
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        lang, kind = classify(os.path.basename(f), rel)
        if kind == "test":
            if lang == "c":
                c_tests.append(rel)
            continue

    # Pass 2: judge every non-test file.
    py_dir_cache = {}

    def tests_dir_listing(dirpath):
        if dirpath not in py_dir_cache:
            try:
                py_dir_cache[dirpath] = sorted(
                    e.name
                    for e in os.scandir(dirpath)
                    if e.is_file(follow_symlinks=False) and e.name.endswith(".py")
                )
            except OSError:
                py_dir_cache[dirpath] = []
        return py_dir_cache[dirpath]

    for f in walk(root):
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        lang, kind = classify(os.path.basename(f), rel)
        if kind == "test":
            continue
        if kind == "marker" and cfg.strict_init:
            kind = "source"
        if kind == "source" and lang == "py" and cfg.under_test_dir(rel):
            kind = "support"
        entry = {"path": rel, "lang": lang}
        if kind == "other":
            entry.update(status="unmapped", matched_test=None, confidence="exact")
            results.append(entry)
            continue
        reason = cfg.allow_reason(rel)
        if reason is not None:
            entry.update(
                status="allowed", matched_test=None, confidence="exact", reason=reason
            )
            results.append(entry)
            continue
        if kind in ("marker", "support"):
            entry.update(
                status="excluded",
                matched_test=None,
                confidence="exact",
                reason=(
                    "package marker (__init__.py)"
                    if kind == "marker"
                    else "test-support module under test dir"
                ),
            )
            results.append(entry)
            continue
        if cfg.exclusion_hit(rel):
            entry.update(status="excluded", matched_test=None, confidence="exact")
            results.append(entry)
            continue
        if lang == "c":
            status, matched = c_module_status(rel, c_tests, read_c_test_content, cfg)
            entry.update(status=status, matched_test=matched, confidence="heuristic")
            results.append(entry)
            continue
        d, name = os.path.split(f)
        status, matched = "gap", None
        if lang == "go":
            if d not in go_cache:
                go_cache[d] = go_tests_in_dir(d)
            tests = go_cache[d]
            if tests:
                status = "ok"
                matched = name[:-3] + "_test.go" if (name[:-3] + "_test.go") in tests else tests[0]
        else:
            for cand in test_candidates(f, lang, root):
                if os.path.isfile(cand) and not os.path.islink(cand):
                    status = "ok"
                    matched = os.path.relpath(cand, root).replace(os.sep, "/")
                    break
            if status == "gap" and lang == "py":
                stem = os.path.splitext(name)[0]
                hit = py_variant_test(d, stem, root, cfg, tests_dir_listing)
                if hit:
                    status = "ok"
                    matched = os.path.relpath(hit, root).replace(os.sep, "/")
        entry.update(status=status, matched_test=matched, confidence="exact")
        results.append(entry)

    if diff_base is not None:
        changed = changed_files(root, diff_base)
        results = [r for r in results if r["path"] in changed]
    return root, results


def summarize(results):
    by_lang = {}
    ok = gap = unmapped = excluded = allowed = 0
    for r in results:
        st = r["status"]
        if st == "unmapped":
            unmapped += 1
            continue
        if st == "excluded":
            excluded += 1
        elif st == "allowed":
            allowed += 1
        elif st == "ok":
            ok += 1
        else:
            gap += 1
        cnt = by_lang.setdefault(
            r["lang"], {"ok": 0, "gap": 0, "excluded": 0, "allowed": 0}
        )
        cnt[st] += 1
    return {
        "total": len(results),
        "ok": ok,
        "gap": gap,
        "unmapped": unmapped,
        "excluded": excluded,
        "allowed": allowed,
        "by_lang": by_lang,
    }


def report(root, results, summary, mode="full", base=None, config_path=None):
    print("hurdle scan: %s" % root)
    meta = "mode=%s" % mode
    if mode == "diff" and base:
        meta += " (base=%s)" % base
    if config_path:
        meta += " config=%s" % config_path
    print(meta)
    print(
        "total=%(total)d ok=%(ok)d gap=%(gap)d unmapped=%(unmapped)d"
        " excluded=%(excluded)d allowed=%(allowed)d" % summary
    )
    for lang in sorted(summary["by_lang"]):
        c = summary["by_lang"][lang]
        line = "  %s: ok=%d gap=%d" % (lang, c["ok"], c["gap"])
        if c["excluded"]:
            line += " excluded=%d" % c["excluded"]
        if c["allowed"]:
            line += " allowed=%d" % c["allowed"]
        print(line)
    allowed = [r for r in results if r["status"] == "allowed"]
    if allowed:
        print("allowed (allowlisted):")
        for r in allowed[:20]:
            print("  %s — %s" % (r["path"], r.get("reason", "")))
    gaps = [r for r in results if r["status"] == "gap"]
    if gaps:
        dirs = {}
        for r in gaps:
            d = os.path.dirname(r["path"]) or "."
            dirs[d] = dirs.get(d, 0) + 1
        print("gap Top 10 directories:")
        ranked = sorted(dirs.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        for d, n in ranked:
            print("  %4d  %s" % (n, d))
        print("gap files (up to 50 of %d):" % len(gaps))
        for r in gaps[:50]:
            print("  %s" % r["path"])


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="hurdle", description="minimal test gap scanner"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    scan_p = sub.add_parser("scan", help="scan PATH for untested source files")
    scan_p.add_argument("path", help="directory tree to scan")
    scan_p.add_argument("--json", dest="json_out", metavar="FILE", help="write JSON report")
    scan_p.add_argument(
        "--strict", action="store_true", help="exit 1 when at least one gap exists"
    )
    scan_p.add_argument(
        "--config",
        metavar="FILE",
        help="config file (default: PATH/.hurdle.json when present)",
    )
    scan_p.add_argument(
        "--diff",
        metavar="BASE",
        help="only judge files added/modified/renamed vs BASE (git; exit 2 if not a repo)",
    )
    uni_p = sub.add_parser(
        "universe",
        help="check universe coverage — every item covered, wildcarded or allowlisted",
    )
    uni_p.add_argument(
        "name", help="universe name defined under 'universes' in .hurdle.json"
    )
    uni_p.add_argument(
        "path", nargs="?", default=".", help="scan root (default: current directory)"
    )
    uni_p.add_argument("--json", dest="json_out", metavar="FILE", help="write JSON report")
    uni_p.add_argument(
        "--strict", action="store_true", help="exit 1 when at least one gap exists"
    )
    ai_p = sub.add_parser(
        "ai-gate",
        help="check AI best-practice patterns — LLM calls must have safety guards",
    )
    ai_p.add_argument(
        "path", nargs="?", default=".", help="scan root (default: current directory)"
    )
    ai_p.add_argument("--json", dest="json_out", metavar="FILE", help="write JSON report")
    ai_p.add_argument(
        "--strict", action="store_true", help="exit 1 when at least one gap exists"
    )
    ai_p.add_argument("--config", metavar="FILE", help="explicit config path")
    ai_p.add_argument(
        "--defaults", action="store_true",
        help="use built-in AI Native gate definitions (5 tiers) — no config needed",
    )
    args = parser.parse_args(argv)

    if args.command == "universe":
        from hurdle import universe

        return universe.run(
            args.name, args.path, json_out=args.json_out, strict=args.strict
        )

    if args.command == "ai-gate":
        from hurdle import ai_gate

        return ai_gate.run(
            args.path, json_out=args.json_out, strict=args.strict,
            config=args.config, defaults=args.defaults,
        )

    config_path = args.config
    if config_path is None:
        auto = os.path.join(os.path.abspath(args.path), DEFAULT_CONFIG_NAME)
        config_path = auto if os.path.isfile(auto) else None
    cfg = load_config(config_path) if config_path else Config({})
    if args.diff:
        check_git_repo(args.path)

    root, results = scan(args.path, cfg, diff_base=args.diff)
    summary = summarize(results)
    report(
        root,
        results,
        summary,
        mode="diff" if args.diff else "full",
        base=args.diff,
        config_path=config_path,
    )

    if args.json_out:
        payload = {
            "path": root,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "mode": "diff" if args.diff else "full",
            "base": args.diff,
            "config": config_path,
            "summary": summary,
            "files": results,
        }
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    return 1 if args.strict and summary["gap"] >= 1 else 0


if __name__ == "__main__":
    sys.exit(main())
