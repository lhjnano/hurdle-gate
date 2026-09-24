"""hurdle universe — completeness gate over a defined item set (stdlib only).

hurdle universe NAME [PATH] [--json FILE] [--strict]

A "universe" is a set of items whose completeness is defined externally
(e.g. every command and event of a protocol). The check extracts a usage
set from string literals in the configured sources and computes
intersection coverage. Gate rule: every item must be covered, covered via
a domain wildcard, or allowlisted with a reason — a silent gap is the
failure mode this command exists to catch.

Usage set extraction (literal-intersection strategy):
  1. every file whose relpath matches an include pattern is read whole
     (errors='replace', at most cli.MAX_CONTENT_BYTES, like scan);
  2. every quoted string literal of up to 120 characters whose text
     matches literal_shape is collected (one regex, quote-paired single/
     double variants);
  3. collected literals ∩ items = covered — universe membership itself
     separates commands from events because their literal shapes are
     identical;
  4. wildcard_patterns: substituting {domain} with each item's domain
     (the part before the first '.') yields a regex; a content match
     marks that domain's items status=wildcard;
  5. extra_usage: explicit declarations, the escape hatch for methods
     composed dynamically (missed by literal extraction) — an exact name
     counts as covered, a glob such as "Runtime.*" as wildcard.

Status precedence: covered > wildcard > allowed > gap (usage evidence
outranks an excuse; an excuse outranks silence). The universe is defined
under the "universes" key of .hurdle.json (auto-discovered at
PATH/.hurdle.json, the same rule as scan):

  "universes": {
    "cdp-commands": {
      "items_file": "universes/cdp-commands.json",
      "include": ["src/**/*.py"],
      "literal_shape": "^[A-Z][A-Za-z0-9]*\\.[a-zA-Z][A-Za-z0-9]+$",
      "wildcard_patterns": ["\\.subscribe\\(\\s*\"({domain})\\.\\*\""],
      "extra_usage": ["Page.javascriptDialogOpening"],
      "allowlist": {"Tracing.*": "out of scope"}
    }
  }

items_file holds a bare JSON array or {"items": [...], "meta": {...}}
(meta passes through to the report); its path is relative to the scan
root. include patterns are fnmatch globs matched against the relpath —
"**/" additionally matches zero directories, and the global exclude /
allowlist config is deliberately NOT applied to this scan. literal_shape,
wildcard_patterns, extra_usage and allowlist are optional (the shape
shown above is the default; allowlist values are the reasons, matched
with fnmatch against item names).

--strict exits 1 when at least one gap remains. Config, items-file or
regex errors exit 2 via die(), including an unknown universe name.
"""

import fnmatch
import json
import os
import re

from .cli import DEFAULT_CONFIG_NAME, MAX_CONTENT_BYTES, die, walk

LITERAL_RE = re.compile(
    r'"([^"\n]{1,120})"' + r"|" + r"'([^'\n]{1,120})'"
)
DEFAULT_LITERAL_SHAPE = r"^[A-Z][A-Za-z0-9]*\.[a-zA-Z][A-Za-z0-9]+$"


def _domain(item):
    return item.split(".", 1)[0]


def _glob_match(rel, pattern):
    """fnmatch on the relpath; '**/' additionally matches zero directories."""
    if fnmatch.fnmatch(rel, pattern):
        return True
    return "**/" in pattern and fnmatch.fnmatch(rel, pattern.replace("**/", ""))


def _compile(pattern, what, name):
    try:
        return re.compile(pattern)
    except re.error as exc:
        die("universe '%s': invalid %s %r: %s" % (name, what, pattern, exc))


def _str_list(setting, key, name, required=False):
    """Read key as a list of non-empty strings; a lone string is wrapped."""
    val = setting.get(key)
    if val is None:
        if required:
            die("universe '%s': %s is required" % (name, key))
        return []
    if isinstance(val, str):
        return [val]
    if not isinstance(val, list) or not all(
        isinstance(v, str) and v for v in val
    ):
        die("universe '%s': %s must be a list of non-empty strings" % (name, key))
    return list(val)


def _settings(raw_cfg, cfg_path, name):
    universes = raw_cfg.get("universes") or {}
    if not isinstance(universes, dict):
        die("config %s: 'universes' must be an object" % cfg_path)
    if name not in universes:
        known = ", ".join(sorted(universes)) or "none defined"
        die("universe '%s' not found in %s (known: %s)" % (name, cfg_path, known))
    setting = universes[name]
    if not isinstance(setting, dict):
        die("universe '%s': definition must be an object" % name)
    return setting


def _load_items(root, setting, name):
    """Return (ordered unique items, meta) from the items_file."""
    rel = setting.get("items_file")
    if not isinstance(rel, str) or not rel:
        die("universe '%s': items_file is required" % name)
    full = os.path.join(root, rel)
    try:
        with open(full, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        die("cannot load items_file %s: %s" % (rel, exc))
    if isinstance(data, dict):
        meta = data.get("meta")
        items = data.get("items")
    else:
        meta = None
        items = data
    if not isinstance(items, list) or not items:
        die(
            "items_file %s: expected a non-empty JSON array or"
            " {'items': [...], 'meta': {...}}" % rel
        )
    ordered = []
    seen = set()
    for item in items:
        if not isinstance(item, str) or not item:
            die("items_file %s: items must be non-empty strings (got %r)" % (rel, item))
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered, meta


def _collect_literals(root, include, shape_re):
    """Scan include-matched files; return (shape-valid literals, contents, file count)."""
    literals = set()
    contents = []
    files = 0
    for f in walk(root):
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        if not any(_glob_match(rel, p) for p in include):
            continue
        files += 1
        try:
            if os.path.getsize(f) > MAX_CONTENT_BYTES:
                continue
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        contents.append(text)
        for m in LITERAL_RE.finditer(text):
            s = m.group(1) or m.group(2)
            if shape_re.fullmatch(s):
                literals.add(s)
    return literals, contents, files


def _wildcard_domains(contents, patterns, domains, name):
    """Domains whose wildcard pattern matches any scanned content."""
    hits = set()
    for pat in patterns:
        for dom in sorted(domains):
            cre = _compile(pat.replace("{domain}", dom), "wildcard_pattern", name)
            if any(cre.search(text) for text in contents):
                hits.add(dom)
    return hits


def _evaluate(items, literals, wildcard_doms, extra_exact, extra_globs, allow_pairs):
    rows = []
    for item in items:
        dom = _domain(item)
        if item in literals or item in extra_exact:
            status, reason = "covered", None
        elif dom in wildcard_doms or any(
            fnmatch.fnmatch(item, g) for g in extra_globs
        ):
            status, reason = "wildcard", None
        else:
            reason = None
            for pat, why in allow_pairs:
                if fnmatch.fnmatch(item, pat):
                    reason = why
                    break
            status = "allowed" if reason is not None else "gap"
        rows.append(
            {"name": item, "domain": dom, "status": status, "allow_reason": reason}
        )
    return rows


def _rollup(rows):
    summary = {"total": len(rows), "covered": 0, "wildcard": 0, "allowed": 0, "gap": 0}
    by_domain = {}
    for r in rows:
        summary[r["status"]] += 1
        c = by_domain.setdefault(
            r["domain"],
            {"total": 0, "covered": 0, "wildcard": 0, "allowed": 0, "gap": 0},
        )
        c["total"] += 1
        c[r["status"]] += 1
    return summary, by_domain


def _print_report(name, root, cfg_path, summary, by_domain, rows, files):
    print("hurdle universe: %s" % name)
    print("root=%s config=%s" % (root, cfg_path))
    print("scanned files=%d" % files)
    print(
        "total=%(total)d covered=%(covered)d wildcard=%(wildcard)d"
        " allowed=%(allowed)d gap=%(gap)d" % summary
    )
    ranked = sorted(by_domain.items(), key=lambda kv: (-kv[1]["gap"], kv[0]))[:15]
    if ranked:
        print("domain Top %d by gap:" % len(ranked))
        print(
            "  %-24s %5s %4s %4s %6s %5s"
            % ("domain", "total", "cov", "wc", "allow", "gap")
        )
        for dom, c in ranked:
            print(
                "  %-24s %5d %4d %4d %6d %5d"
                % (
                    dom,
                    c["total"],
                    c["covered"],
                    c["wildcard"],
                    c["allowed"],
                    c["gap"],
                )
            )
    allowed = [r for r in rows if r["status"] == "allowed"]
    if allowed:
        print("allowed (allowlisted):")
        for r in allowed[:20]:
            print("  %s — %s" % (r["name"], r.get("allow_reason") or ""))
    gaps = [r for r in rows if r["status"] == "gap"]
    if gaps:
        print("gap items (up to 50 of %d):" % len(gaps))
        for r in gaps[:50]:
            print("  %s" % r["name"])


def run(name, path=".", json_out=None, strict=False):
    root = os.path.abspath(path)
    cfg_path = os.path.join(root, DEFAULT_CONFIG_NAME)
    if not os.path.isfile(cfg_path):
        die(
            "no %s in %s — universe definitions require config"
            % (DEFAULT_CONFIG_NAME, root)
        )
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        die("cannot load config %s: %s" % (cfg_path, exc))
    if not isinstance(raw, dict):
        die("config %s: expected a JSON object" % cfg_path)
    setting = _settings(raw, cfg_path, name)

    items, meta = _load_items(root, setting, name)
    include = _str_list(setting, "include", name, required=True)
    shape = setting.get("literal_shape") or DEFAULT_LITERAL_SHAPE
    if not isinstance(shape, str):
        die("universe '%s': literal_shape must be a string" % name)
    shape_re = _compile(shape, "literal_shape", name)
    patterns = _str_list(setting, "wildcard_patterns", name)
    extra_usage = _str_list(setting, "extra_usage", name)
    allow = setting.get("allowlist") or {}
    if not isinstance(allow, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and k for k, v in allow.items()
    ):
        die(
            "universe '%s': allowlist must map item-name globs to reason strings"
            % name
        )
    allow_pairs = list(allow.items())

    literals, contents, files = _collect_literals(root, include, shape_re)
    domains = {_domain(i) for i in items}
    wildcard_doms = _wildcard_domains(contents, patterns, domains, name)
    extra_exact = {e for e in extra_usage if not any(c in e for c in "*?[")}
    extra_globs = [e for e in extra_usage if any(c in e for c in "*?[")]

    rows = _evaluate(items, literals, wildcard_doms, extra_exact, extra_globs, allow_pairs)
    summary, by_domain = _rollup(rows)
    _print_report(name, root, cfg_path, summary, by_domain, rows, files)

    if json_out:
        payload = {
            "universe": name,
            "meta": meta,
            "summary": summary,
            "by_domain": by_domain,
            "items": rows,
        }
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    return 1 if strict and summary["gap"] >= 1 else 0
