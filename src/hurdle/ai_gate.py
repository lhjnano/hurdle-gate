"""hurdle ai-gate — AI best-practice pattern gate (stdlib only).

hurdle ai-gate [PATH] [--json FILE] [--strict] [--config FILE]

For every source file that matches an AI "detect" pattern (e.g. contains an
LLM API call), verify that the required best-practice patterns are also
present in the same file. A file that calls an LLM without error handling,
timeout, or output validation is reported as a gap — the same ratchet
philosophy as the test-existence gate: existence only, never quality.

Gate definitions live under "ai_gates" in .hurdle.json:

  "ai_gates": {
    "llm-basic": {
      "include": ["src/**/*.ts", "src/**/*.py"],
      "detect": "chat\\.completions|/v1/messages|anthropic",
      "require": {
        "error_handling": "try[\\s\\S]*catch",
        "timeout": "TIMEOUT|timeout|AbortSignal",
        "output_parse": "JSON\\.parse|extractJson|safeParse"
      }
    },
    "agent-safety": {
      "include": ["src/**/*.ts"],
      "detect": "tool_calls|while.*agent",
      "require": {
        "max_steps": "max_steps|MAX_STEPS",
        "hallucination_defense": "not.*found|cannot.*find|모른다"
      },
      "require_any": {
        "human_review": "confirm|review|approve",
        "fallback": "fallback|reasoning_content|retry"
      }
    }
  }

Semantics:
  detect   — a single regex; files under `include` whose content matches
             this pattern are "AI-active" and subject to the gate.
  require  — all listed keys must match somewhere in the same file.
  require_any — at least one listed key must match (OR semantics).
  allowlist — per-file escape hatch (same as other gates): glob → reason.

Statuses per file: pass (all requirements met) / gap (missing one or more
required patterns) / allowed (explicitly allowlisted) / skipped (under
include but not AI-active — detect did not match).

--strict exits 1 when any gap remains. Config or regex errors exit 2.
"""

import fnmatch
import json
import os
import re

from .cli import DEFAULT_CONFIG_NAME, MAX_CONTENT_BYTES, die, walk


def _glob_match(rel, pattern):
    if fnmatch.fnmatch(rel, pattern):
        return True
    return "**/" in pattern and fnmatch.fnmatch(rel, pattern.replace("**/", ""))


def _compile(pattern, gate, key):
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        die("ai-gate '%s': invalid %s regex %r: %s" % (gate, key, pattern, exc))


def _read_file(path):
    try:
        if os.path.getsize(path) > MAX_CONTENT_BYTES:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _check_gate(name, setting, root, global_allow):
    include = setting.get("include") or ["**/*"]
    detect_re = _compile(setting.get("detect", ""), name, "detect")
    require = setting.get("require") or {}
    require_any = setting.get("require_any") or {}
    allow = setting.get("allowlist") or {}

    for key, val in list(require.items()) + list(require_any.items()):
        if not isinstance(val, str) or not val:
            die("ai-gate '%s': %s must be a non-empty regex string" % (name, key))

    req_res = {k: _compile(v, name, k) for k, v in require.items()}
    any_res = {k: _compile(v, name, k) for k, v in require_any.items()}

    rows = []
    for f in walk(root):
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        if not any(_glob_match(rel, p) for p in include):
            continue
        text = _read_file(f)
        if text is None:
            continue
        if not detect_re.search(text):
            rows.append({"file": rel, "gate": name, "status": "skipped",
                         "missing": [], "reason": None})
            continue

        reason = allow.get(rel) or global_allow.get(rel)
        if reason:
            rows.append({"file": rel, "gate": name, "status": "allowed",
                         "missing": [], "reason": reason})
            continue

        missing = [k for k, cre in req_res.items() if not cre.search(text)]
        if require_any and not any(cre.search(text) for cre in any_res.values()):
            missing.append("|".join(require_any.keys()))

        status = "gap" if missing else "pass"
        rows.append({"file": rel, "gate": name, "status": status,
                     "missing": missing, "reason": None})
    return rows


def run(path=".", json_out=None, strict=False, config=None):
    root = os.path.abspath(path)
    cfg_path = config or os.path.join(root, DEFAULT_CONFIG_NAME)
    if not os.path.isfile(cfg_path):
        die("no %s in %s — ai-gate definitions require config" % (DEFAULT_CONFIG_NAME, root))
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        die("cannot load config %s: %s" % (cfg_path, exc))

    gates = raw.get("ai_gates") or {}
    if not isinstance(gates, dict) or not gates:
        die("config %s: 'ai_gates' must be a non-empty object" % cfg_path)
    global_allow = raw.get("allowlist") or {}

    all_rows = []
    for name, setting in gates.items():
        if not isinstance(setting, dict):
            die("ai-gate '%s': definition must be an object" % name)
        all_rows.extend(_check_gate(name, setting, root, global_allow))

    summary = {"total": len(all_rows), "pass": 0, "gap": 0, "allowed": 0, "skipped": 0}
    for r in all_rows:
        summary[r["status"]] += 1

    print("hurdle ai-gate")
    print("root=%s config=%s" % (root, cfg_path))
    print("files=%d pass=%d gap=%d allowed=%d skipped=%d"
          % (summary["total"], summary["pass"], summary["gap"],
             summary["allowed"], summary["skipped"]))
    gaps = [r for r in all_rows if r["status"] == "gap"]
    if gaps:
        print("\ngaps (up to 50 of %d):" % len(gaps))
        for r in gaps[:50]:
            missing = ", ".join(r["missing"])
            print("  %s [%s] missing: %s" % (r["file"], r["gate"], missing))

    if json_out:
        payload = {
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
            "summary": summary,
            "files": all_rows,
        }
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    return 1 if strict and summary["gap"] >= 1 else 0
