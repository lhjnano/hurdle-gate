# Contributing

## Development environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Uses only the Python 3.9+ standard library (zero runtime dependencies). The
only dev dependency is pytest.

## Verification

```bash
make test    # pytest (tests/test_cli.py)
make smoke   # bash tests/run_smoke.sh — verdict-regression smoke test
make check   # dogfood — hurdle scan . --strict (gates itself)
```

## Adding a language convention

Steps to add a "test existence" rule for a new language:

1. Add an extension → `(lang, kind)` branch to `classify()` and the mapping
   candidate paths to `test_candidates()` in `src/hurdle/cli.py`.
2. Add minimal fixtures under `tests/fixtures/` (at least one covered and one
   gap case).
3. Add verdict assertions to the expectation table (`CONFIGLESS_EXPECT`) in
   `tests/test_cli.py`.

For trees like C/shell where file-to-file mapping is impossible, verdicts use
the `module_map` keyword-based module-aggregated heuristic and keep confidence
at `heuristic`.

## Changing the config schema

When you change the `.hurdle.json` schema (`exclude` / `allowlist` /
`module_map`), update `.hurdle.example.json` and the configuration table in
the README in the same change.

## PR checklist

- [ ] `pytest` passes
- [ ] `bash tests/run_smoke.sh` passes
- [ ] `hurdle scan . --strict` passes
- [ ] User-visible changes get a `CHANGELOG.md` entry
