# AI Best-Practice Gate (`hurdle ai-gate`)

> Core question: "Does this LLM-calling code have safety guards?" — existence only, never quality.
> Same philosophy as the test gate: "does a test file exist?" → "does a fallback exist?"

## The Problem

Code that calls LLMs quietly ships to production without error handling, without timeouts, without output validation. Agent loops have no max_steps limit. RAG answers have no source citation. By the time you notice, it's already caused an incident.

## The Approach

`ai-gate` scans source file contents for AI best-practice patterns using **regex matching**. It never executes code, never evaluates output quality. It answers exactly one question: "do the required patterns exist?"

## Usage

### No config needed (built-in gates)

```bash
hurdle ai-gate . --defaults --strict
```

### Custom gates (.hurdle.json)

```jsonc
{
  "ai_gates": {
    "my-llm-rules": {
      "include": ["src/**/*.ts"],
      "detect": "chat\\.completions|anthropic",
      "require": {
        "error_handling": "try[\\s\\S]*catch",
        "timeout": "TIMEOUT|AbortSignal"
      },
      "require_any": {
        "reasoning_fallback": "reasoning_content",
        "retry": "retry|max_retries"
      },
      "allowlist": {
        "src/legacy.ts": "scheduled for rewrite in Q4"
      }
    }
  }
}
```

```bash
hurdle ai-gate . --strict --config .hurdle.json
```

### Merging

`--defaults` + `.hurdle.json` merge together (user-defined keys with the same name override built-ins).

## Built-in Gates (5 Tiers)

These encode the AI Native study guide (02-ai-native.html) — each tier maps to a section of the guide. **What you learned is what the gate enforces.**

### Tier 1: `llm-basic` — LLM Safety Nets

Minimum safety for every LLM API call.

| Pattern | Description | Example match |
|---|---|---|
| `error_handling` | try/catch or except | `try { ... } catch (e)` |
| `timeout` | Timeout configured | `TIMEOUT_MS`, `AbortSignal.timeout()` |
| `output_parse` | Output parsing/validation | `JSON.parse()`, `extractJson()`, `safeParse()` |

**Without it:** LLM dies → app dies. Response truncated → parse error. Waits forever.

### Tier 2: `function-calling` — Tool Use Structure

Files using Function Calling need the full loop.

| Pattern | Description | Example match |
|---|---|---|
| `tool_definition` | Tool definition (JSON Schema) | `"type": "function"`, `tools = [...]` |
| `tool_execution` | Tool execution code | `execute_tool()`, `tc.function.name` |
| `result_return` | Result returned to LLM | `role: "tool", tool_call_id: ...` |

**Without it:** Tools defined but never executed, or results never sent back to the LLM.

### Tier 3: `agent-loop` — Agent Guards

Files running agent loops need two defenses.

| Pattern | Description | Example match |
|---|---|---|
| `max_steps` | Maximum step limit | `MAX_STEPS = 5`, `for i in range(n)` |
| `termination` | Termination condition | `Final Answer`, `break`, `done = True` |

**Without it:** Infinite loop → API bill explosion.

### Tier 4: `rag-integrity` — RAG Trustworthiness

Files doing RAG (retrieval-augmented generation) need provenance and honesty.

| Pattern | Description | Example match |
|---|---|---|
| `source_citation` | Source attribution | `source_documents`, `citation`, `documents[i]` |
| `hallucination_defense` | "I don't know" response | `not found`, `cannot find`, `unknown` |

**Without it:** Unfounded answers (hallucination). Users lose trust instantly.

### Tier 5: `ai-resilience` — Fallback (any one)

At least one recovery mechanism when the LLM call fails.

| Pattern | Description | Example match |
|---|---|---|
| `reasoning_fallback` | Reasoning model fallback | `reasoning_content` |
| `retry` | Retry logic | `retry`, `max_retries` |
| `model_fallback` | Model switching | `lighter`, `FALLBACK_MODEL` |
| `graceful_degradation` | Graceful degradation | `catch { return null }` |

**`require_any` semantics:** any one match passes (OR).

**Without it:** LLM dies → entire service goes down.

## Built-in Paired Check: tool_call_id Correlation

A file referencing `tool_calls` but not `tool_call_id` is reported as a gap. Always on, not configurable.

**Why:** OpenAI/Anthropic APIs require the tool result message to carry the matching `tool_call_id`. Without it:

```
Error: No tool output found for function call
```

The agent loop breaks. This is the most common Function Calling bug.

## Statuses

| Status | Meaning |
|---|---|
| `pass` | All `require` met (+ at least one `require_any`) |
| `gap` | One or more required patterns missing (listed in `missing`) |
| `allowed` | Explicitly allowlisted (reason recorded) |
| `skipped` | Under `include` but not AI-active (detect didn't match) |

## JSON Report

```bash
hurdle ai-gate . --defaults --json report.json
```

```json
{
  "gates": ["llm-basic", "function-calling", "agent-loop", "rag-integrity", "ai-resilience"],
  "summary": {"total": 25, "pass": 20, "gap": 3, "allowed": 1, "skipped": 1},
  "files": [
    {"file": "src/agent.ts", "gate": "function-calling", "status": "gap",
     "missing": ["tool_definition", "tool_call_id_correlation"]}
  ]
}
```

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | No gaps (or not `--strict`) |
| 1 | Gaps present + `--strict` |
| 2 | Configuration error (missing config, invalid regex, etc.) |

## Limitations (Honestly)

This gate provides **minimum verification**. It does not guarantee a good AI Native app.

| What it checks | What it doesn't check |
|---|---|
| Error handling code exists | Whether it's appropriate (empty catch passes) |
| max_steps exists | Whether 5 is reasonable (1000 also passes) |
| Source citation code exists | Whether citations are actually correct |
| JSON parsing exists | Whether output is validated after parsing |
| Fallback code exists | Whether fallback quality is usable |

Think of it as a driving license test — it confirms basic competency, not good driving. But it's better than driving without a license.

## Writing Custom Gates

```jsonc
"ai_gates": {
  "my-gate-name": {
    "include": ["src/**/*.py"],
    "detect": "regex_to_identify_ai_active_files",
    "require": {
      "required_pattern_1": "regex",
      "required_pattern_2": "regex"
    },
    "require_any": {
      "alternative_1": "regex",
      "alternative_2": "regex"
    },
    "allowlist": {
      "src/special.ts": "reason"
    }
  }
}
```

Tips:
- Keep `detect` narrow — too broad and non-AI files get checked
- Name `require` keys clearly — they appear verbatim in reports
- Regexes compile with `re.IGNORECASE`
- For multiline code, use `[\s\S]*` (not `.*`, which can't cross newlines)
