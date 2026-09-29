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


class AiGateBasic(unittest.TestCase):
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
                "detect": "chat\\.completions",
                "require": {
                    "error_handling": "try[\\s\\S]*catch",
                    "timeout": "TIMEOUT",
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
                "detect": "chat\\.completions",
                "require": {
                    "error_handling": "try[\\s\\S]*catch",
                    "timeout": "TIMEOUT",
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
                "detect": "chat\\.completions",
                "require": {"timeout": "TIMEOUT"},
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
                "detect": "chat\\.completions",
                "require_any": {
                    "fallback": "reasoning_content",
                    "retry": "retry",
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
                "detect": "chat\\.completions",
                "require_any": {
                    "fallback": "reasoning_content",
                    "retry": "retry",
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
                "detect": "chat\\.completions",
                "require": {"timeout": "TIMEOUT"},
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
                "detect": "chat\\.completions",
                "require": {"timeout": "TIMEOUT"},
            }
        })
        self._write("src/llm.ts", "await client.chat.completions.create({});")
        jf = os.path.join(self.tmp, "report.json")
        rc, out = run_hurdle("ai-gate", self.tmp, "--json", jf, "--strict")
        self.assertEqual(rc, 1)
        with open(jf) as fh:
            data = json.load(fh)
        self.assertEqual(data["summary"]["gap"], 1)
        self.assertEqual(data["files"][0]["missing"], ["timeout"])

    def test_no_config_exits_2(self):
        empty = tempfile.mkdtemp()
        rc, out = run_hurdle("ai-gate", empty)
        self.assertEqual(rc, 2)

    def test_empty_gates_exits_2(self):
        self._config({})
        rc, out = run_hurdle("ai-gate", self.tmp)
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
