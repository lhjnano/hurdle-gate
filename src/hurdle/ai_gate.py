"""hurdle ai-gate — AI best-practice pattern gate (stdlib only).

hurdle ai-gate [PATH] [--json FILE] [--strict] [--config FILE] [--defaults]

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
    }
  }

Semantics:
  detect      — regex; matching files are "AI-active" and subject to the gate.
  require     — all listed patterns must match (AND).
  require_any — at least one must match (OR).
  allowlist   — per-gate escape hatch: relpath → reason.

Built-in checks (always on, not configurable):
  tool_call_id correlation — a file referencing 'tool_calls' must also
  reference 'tool_call_id'; without it the agent loop breaks ("No tool
  output found for function call").

--defaults loads a built-in set of gates covering the five AI Native
tiers (below) without requiring any user config. User-defined gates in
.hurdle.json are merged on top (same-name keys override).

Built-in default gates (--defaults):
  Tier 1  llm-basic        — error handling, timeout, output parsing
  Tier 2  function-calling — tool definition + execution + result return
  Tier 3  agent-loop       — max_steps + termination condition
  Tier 4  rag-integrity    — source citation + hallucination defense
  Tier 5  ai-resilience    — reasoning fallback OR retry OR model fallback

These encode the AI Native study guide (02-ai-native.html) — each tier
maps to a section of the guide, so what you learned is what the gate
enforces.
"""

import fnmatch
import json
import os
import re

from .cli import DEFAULT_CONFIG_NAME, MAX_CONTENT_BYTES, die, walk


# ─── Built-in default gates (from AI Native study guide) ───────────

DEFAULT_GATES = {
    # Tier 1: Every LLM call needs safety nets (§1 AI Native traits)
    "llm-basic": {
        "include": ["src/**/*.ts", "src/**/*.tsx", "src/**/*.py",
                     "src/**/*.js", "web/src/**/*.ts", "web/src/**/*.tsx"],
        "detect": r"chat\.completions|/v1/messages|anthropic|generateText|llm\.chat",
        "require": {
            "error_handling": r"try[\s\S]*catch|except\s",
            "timeout": r"TIMEOUT|timeout|AbortSignal|abort\(",
            "output_parse": r"JSON\.parse|extractJson|safeParse|json\.loads|json\.parse",
        },
    },
    # Tier 2: Function Calling needs the full loop (§2)
    "function-calling": {
        "include": ["src/**/*.ts", "src/**/*.tsx", "src/**/*.py",
                     "web/src/**/*.ts", "web/src/**/*.tsx"],
        "detect": r"tool_calls|function_call",
        "require": {
            "tool_definition": r'"type"[\s\S]*"function"|"function"[\s\S]*"parameters"|tools\s*[=:]|tool_choice|tools,',
            "tool_execution": r"execute_tool|TOOL_MAP|dispatch|function\.name|tool_call\.function",
            "result_return": r'"role"[\s\S]*"tool"|role[\s\S]*tool[\s\S]*content',
        },
    },
    # Tier 3: Agent loops need guards (§3 ReAct)
    "agent-loop": {
        "include": ["src/**/*.ts", "src/**/*.py", "web/src/**/*.ts"],
        "detect": r"while[\s\S]*(?:tool_call|Action|agent)|ReAct|react_agent",
        "require": {
            "max_steps": r"max_steps|MAX_STEPS|for\s+\w+\s+in\s+range",
            "termination": r"Final Answer|final_answer|break|done\s*=\s*True",
        },
    },
    # Tier 4: RAG needs provenance + honesty (§4)
    "rag-integrity": {
        "include": ["src/**/*.ts", "src/**/*.py", "web/src/**/*.ts"],
        "detect": r"retriev|embedding|vector|chroma|faiss|vectordb",
        "require": {
            "source_citation": r"source_documents|citation|출처|근거|source\s*\[|documents\[",
            "hallucination_defense": r"not[\s_]*found|cannot[\s_]*find|모른다|찾을 수 없|don.t know|unknown",
        },
    },
    # Tier 5: Resilience — at least one fallback mechanism (§1.3④)
    "ai-resilience": {
        "include": ["src/**/*.ts", "src/**/*.py", "web/src/**/*.ts"],
        "detect": r"chat\.completions|anthropic|llm\.chat|reasoning",
        "require_any": {
            "reasoning_fallback": r"reasoning_content",
            "retry": r"retry|attempt|max_retries",
            "model_fallback": r"fallback.*model|lighter|FALLBACK",
            "graceful_degradation": r"catch[\s\S]*return\s+(?:null|''|\"\"|\[\]|\{\})",
        },
    },
}

# Built-in paired check: tool_calls without tool_call_id breaks the loop
PAIRED_CHECKS = [
    {
        "name": "tool_call_id_correlation",
        "detect": r"tool_calls",
        "require": r"tool_call_id",
        "description": "tool_calls without tool_call_id — agent loop will break",
    },
]


# ─── Engine ─────────────────────────────────────────────────────────

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
            missing.append("|".join(sorted(require_any.keys())))

        # Built-in paired checks
        for pc in PAIRED_CHECKS:
            det = _compile(pc["detect"], name, pc["name"])
            req = _compile(pc["require"], name, pc["name"])
            if det.search(text) and not req.search(text):
                missing.append(pc["name"])

        status = "gap" if missing else "pass"
        rows.append({"file": rel, "gate": name, "status": status,
                     "missing": missing, "reason": None})
    return rows


def run(path=".", json_out=None, strict=False, config=None, defaults=False):
    root = os.path.abspath(path)

    gates = {}
    if defaults:
        gates.update(DEFAULT_GATES)

    cfg_path = config or os.path.join(root, DEFAULT_CONFIG_NAME)
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as exc:
            die("cannot load config %s: %s" % (cfg_path, exc))
        user_gates = raw.get("ai_gates") or {}
        if not isinstance(user_gates, dict):
            die("config %s: 'ai_gates' must be an object" % cfg_path)
        gates.update(user_gates)
        global_allow = raw.get("allowlist") or {}
    else:
        if not defaults:
            die("no %s in %s and no --defaults — nothing to check"
                % (DEFAULT_CONFIG_NAME, root))
        global_allow = {}

    if not gates:
        die("no gates defined (config empty and --defaults not set)")

    all_rows = []
    for name, setting in gates.items():
        if not isinstance(setting, dict):
            die("ai-gate '%s': definition must be an object" % name)
        all_rows.extend(_check_gate(name, setting, root, global_allow))

    summary = {"total": len(all_rows), "pass": 0, "gap": 0, "allowed": 0, "skipped": 0}
    for r in all_rows:
        summary[r["status"]] += 1

    print("hurdle ai-gate")
    print("root=%s config=%s%s" % (root, cfg_path if os.path.isfile(cfg_path) else "(none)",
                                    " +defaults" if defaults else ""))
    print("gates=%d" % len(gates))
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
        import datetime
        payload = {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "gates": sorted(gates.keys()),
            "summary": summary,
            "files": all_rows,
        }
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    return 1 if strict and summary["gap"] >= 1 else 0
