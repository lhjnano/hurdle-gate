"""Tests for hurdle ai-gate — AI best-practice pattern verification."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


def run_hurdle(*args, cwd=None):
    env = dict(os.environ)
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    env["PYTHONPATH"] = src
    r = subprocess.run(
        [sys.executable, "-m", "hurdle", *args],
        capture_output=True, text=True, cwd=cwd, env=env,
    )
    return r.returncode, r.stdout + r.stderr


class AiGateCustom(unittest.TestCase):
    """User-defined gates via .hurdle.json ai_gates."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, ".hurdle.json")

    def _write(self, rel, content):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(textwrap.dedent(content))

    def _config(self, gates):
        with open(self.cfg, "w") as fh:
            json.dump({"ai_gates": gates}, fh)

    def test_pass_with_all_requirements(self):
        self._config({
            "llm-basic": {
                "include": ["src/**/*.ts"],
                "detect": r"chat\.completions",
                "require": {
                    "error_handling": r"try[\s\S]*catch",
                    "timeout": r"TIMEOUT",
                },
            }
        })
        self._write("src/llm.ts", """
            const TIMEOUT_MS = 30000;
            async function call() {
                try {
                    return await client.chat.completions.create({});
                } catch (e) { throw e; }
            }
        """)
        rc, out = run_hurdle("ai-gate", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("pass=1", out)

    def test_gap_missing_timeout(self):
        self._config({
            "llm-basic": {
                "include": ["src/**/*.ts"],
                "detect": r"chat\.completions",
                "require": {
                    "error_handling": r"try[\s\S]*catch",
                    "timeout": r"TIMEOUT",
                },
            }
        })
        self._write("src/llm.ts", """
            async function call() {
                try {
                    return await client.chat.completions.create({});
                } catch (e) { throw e; }
            }
        """)
        rc, out = run_hurdle("ai-gate", self.tmp, "--strict")
        self.assertEqual(rc, 1)
        self.assertIn("timeout", out)

    def test_skipped_when_no_llm_call(self):
        self._config({
            "llm-basic": {
                "include": ["src/**/*.ts"],
                "detect": r"chat\.completions",
                "require": {"timeout": r"TIMEOUT"},
            }
        })
        self._write("src/utils.ts", """
            export function add(a, b) { return a + b; }
        """)
        rc, out = run_hurdle("ai-gate", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("skipped=1", out)

    def test_require_any_pass(self):
        self._config({
            "resilience": {
                "include": ["src/**/*.ts"],
                "detect": r"chat\.completions",
                "require_any": {
                    "fallback": r"reasoning_content",
                    "retry": r"retry",
                },
            }
        })
        self._write("src/llm.ts", """
            const content = msg.content || msg.reasoning_content || '';
            await client.chat.completions.create({});
        """)
        rc, out = run_hurdle("ai-gate", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("pass=1", out)

    def test_require_any_gap(self):
        self._config({
            "resilience": {
                "include": ["src/**/*.ts"],
                "detect": r"chat\.completions",
                "require_any": {
                    "fallback": r"reasoning_content",
                    "retry": r"retry",
                },
            }
        })
        self._write("src/llm.ts", """
            const data = await client.chat.completions.create({});
        """)
        rc, out = run_hurdle("ai-gate", self.tmp, "--strict")
        self.assertEqual(rc, 1)
        self.assertIn("fallback|retry", out)

    def test_allowlist_per_file(self):
        self._config({
            "llm-basic": {
                "include": ["src/**/*.ts"],
                "detect": r"chat\.completions",
                "require": {"timeout": r"TIMEOUT"},
                "allowlist": {
                    "src/legacy.ts": "pre-existing — scheduled for rewrite"
                },
            }
        })
        self._write("src/legacy.ts", """
            await client.chat.completions.create({});
        """)
        rc, out = run_hurdle("ai-gate", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("allowed=1", out)

    def test_json_output(self):
        self._config({
            "llm-basic": {
                "include": ["src/**/*.ts"],
                "detect": r"chat\.completions",
                "require": {"timeout": r"TIMEOUT"},
            }
        })
        self._write("src/llm.ts", "await client.chat.completions.create({});")
        jf = os.path.join(self.tmp, "report.json")
        rc, out = run_hurdle("ai-gate", self.tmp, "--json", jf, "--strict")
        self.assertEqual(rc, 1)
        with open(jf) as fh:
            data = json.load(fh)
        self.assertEqual(data["summary"]["gap"], 1)

    def test_no_config_no_defaults_exits_2(self):
        empty = tempfile.mkdtemp()
        rc, out = run_hurdle("ai-gate", empty)
        self.assertEqual(rc, 2)


class AiGateDefaults(unittest.TestCase):
    """Built-in --defaults gates (AI Native study guide tiers)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, rel, content):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(textwrap.dedent(content))

    def test_defaults_runs_without_config(self):
        self._write("src/utils.ts", "export const x = 1;")
        rc, out = run_hurdle("ai-gate", self.tmp, "--defaults")
        self.assertEqual(rc, 0)
        self.assertIn("gates=5", out)

    def test_llm_basic_detects_missing_timeout(self):
        self._write("src/llm.ts", """
            async function call() {
                try {
                    const res = await client.chat.completions.create({});
                    const data = JSON.parse(JSON.stringify(res));
                    return data;
                } catch (e) { return null; }
            }
        """)
        rc, out = run_hurdle("ai-gate", self.tmp, "--defaults", "--strict")
        self.assertEqual(rc, 1)
        self.assertIn("timeout", out.lower())

    def test_tool_call_id_correlation(self):
        """tool_calls present but tool_call_id absent → gap."""
        self._write("src/agent.ts", """
            const TIMEOUT_MS = 30000;
            try {
                const msg = await client.chat.completions.create({});
                if (msg.tool_calls) {
                    // iterates calls but never echoes the correlation id
                    for (const tc of msg.tool_calls) {
                        console.log(tc.function.name);
                    }
                }
                const parsed = JSON.parse(JSON.stringify(msg));
            } catch (e) { return null; }
        """)
        rc, out = run_hurdle("ai-gate", self.tmp, "--defaults", "--strict")
        self.assertEqual(rc, 1)
        self.assertIn("tool_call_id_correlation", out)

    def test_agent_loop_needs_max_steps(self):
        self._write("src/agent.ts", """
            const TIMEOUT_MS = 30000;
            while (true) {
                if (msg.tool_calls) {
                    for (const tc of msg.tool_calls) {
                        messages.push({
                            role: "tool",
                            tool_call_id: tc.id,
                            content: "result"
                        });
                    }
                } else {
                    break;
                }
            }
        """)
        rc, out = run_hurdle("ai-gate", self.tmp, "--defaults", "--strict")
        self.assertEqual(rc, 1)
        self.assertIn("max_steps", out)

    def test_rag_needs_source_citation(self):
        self._write("src/rag.py", """
            import json
            try:
                embeddings = model.encode(chunks)
                vectordb = Chroma.from_texts(chunks, embeddings)
                results = vectordb.similarity_search(query, k=3)
                # Missing: no source citation, no hallucination defense
                answer = llm.invoke(query)
            except Exception:
                results = []
        """)
        rc, out = run_hurdle("ai-gate", self.tmp, "--defaults", "--strict")
        self.assertEqual(rc, 1)
        # Should flag missing source_citation or hallucination_defense
        self.assertTrue(
            "source_citation" in out or "hallucination" in out,
            "Expected source_citation or hallucination_defense in output"
        )

    def test_full_ai_native_code_passes(self):
        """A well-written AI Native file should pass all gates."""
        self._write("src/copilot.ts", """
            const TIMEOUT_MS = 180000;
            const MAX_STEPS = 5;

            async function agent(question: string) {
                const messages = [{ role: "user", content: question }];
                try {
                    for (let step = 0; step < MAX_STEPS; step++) {
                        const msg = await client.chat.completions.create({
                            model: "gpt-4o",
                            messages,
                            tools,
                        });
                        if (msg.tool_calls) {
                            messages.push(msg);
                            for (const tc of msg.tool_calls) {
                                const result = executeTool(tc.function.name, tc.function.arguments);
                                messages.push({
                                    role: "tool",
                                    tool_call_id: tc.id,
                                    content: JSON.stringify(result),
                                });
                            }
                        } else {
                            break;
                        }
                    }
                    const parsed = JSON.parse(JSON.stringify(messages));
                    return parsed;
                } catch (e) {
                    return null;
                }
            }
        """)
        rc, out = run_hurdle("ai-gate", self.tmp, "--defaults", "--strict")
        self.assertEqual(rc, 0, "Expected well-written AI code to pass:\n%s" % out)


if __name__ == "__main__":
    unittest.main()
