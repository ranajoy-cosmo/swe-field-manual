# Pre-commit Hooks

*(See Chapter 02 for full configuration and setup of pre-commit).*

Pre-commit hooks shift-left the discovery of formatting and linting errors. Instead of waiting 5 minutes for CI to fail because of a trailing whitespace, the developer gets instant feedback at commit time.

## CI vs. Local Hook Distinction

A common misconception is that pre-commit hooks replace CI. They do not.

- **Local Hooks**: Fail fast, save developer time, and format code automatically. However, they can be bypassed (`git commit --no-verify`).
- **CI Hooks**: The authoritative gate. CI must run the exact same checks to guarantee code quality, regardless of how the developer committed the code.

To ensure parity, run pre-commit as the first step in your CI pipeline:

```yaml
# .github/workflows/ci.yml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - run: pip install pre-commit
      - run: pre-commit run --all-files
```

## Hook Performance: `commit` vs `push`

By default, hooks run during the `pre-commit` stage. If a hook takes longer than 2 seconds, developers will bypass it out of frustration.

- **`commit` stage**: Fast checks (Ruff formatting, whitespace fixing, secrets detection).
- **`push` stage**: Slow checks (mypy type checking, running the test suite).

To move a slow hook to the push stage, specify `stages: [pre-push]` in `.pre-commit-config.yaml`:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: uv run mypy src
        language: system
        types: [python]
        stages: [pre-push]  # Only runs when typing `git push`
```

## Writing Custom Hooks

You aren't limited to the public ecosystem. You can write local hooks for project-specific constraints (e.g., ensuring no one imports from a deprecated module).

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: check-deprecated-imports
        name: Check for deprecated imports
        entry: ./scripts/check_imports.sh
        language: script
        files: \.py$
```

```bash
#!/bin/bash
# scripts/check_imports.sh
if grep -rn "from feature_pipeline.legacy" "$@"; then
    echo "ERROR: Do not import from the legacy module."
    exit 1
fi
```

## Managing Hook Dependencies

Hooks are dependencies and will rot if not updated. `pre-commit` provides a built-in command to update all hooks to their latest tags:

```bash
pre-commit autoupdate
```

Run this command monthly. If a hook update introduces new linting errors (e.g., a new Ruff rule is enabled), fix the code immediately rather than pinning the hook to an old version.

## Summary

| Decision | Recommendation | Reason |
|----------|----------------|--------|
| CI Integration | Run `pre-commit run --all-files` | CI is the ultimate source of truth; local hooks are just for speed. |
| Hook Stages | Move slow hooks to `pre-push` | Keeps `git commit` fast so developers don't use `--no-verify`. |
| Updates | Run `pre-commit autoupdate` monthly | Prevents tooling from falling years behind current standards. |
