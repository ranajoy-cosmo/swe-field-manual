# 04 — Pre-commit Hooks

## What Pre-commit Is and What It Is Not

`pre-commit` is a framework that runs a configurable set of checks before a Git operation completes. It runs in the developer's local environment, before code reaches remote. This matters because:

**The local loop is faster than CI.** A pre-commit hook that runs in 2 seconds catches a linting error before it becomes a PR comment, a CI failure, and a context-switch. The earlier a problem is caught, the cheaper it is to fix.

**Pre-commit is not a replacement for CI.** It runs on what the developer chooses to stage — it can be skipped with `--no-verify`, it doesn't run on code pushed directly to a branch without commits, and it is not executed by everyone (e.g., automated scripts, GitHub web editor). CI is the authoritative enforcement point. Pre-commit is the fast feedback mechanism.

The relationship:
- **Pre-commit**: catch issues locally, fast, developer opt-in (enforced by policy)
- **CI**: authoritative gate, runs always, cannot be skipped, blocks merges

---

## 1. Installation

```bash
uv add --dev pre-commit
uv run pre-commit install
```

`pre-commit install` writes Git hooks into `.git/hooks/`. After this, every `git commit` triggers the configured hooks.

Also install the commit-msg hook (for conventional commit enforcement):
```bash
uv run pre-commit install --hook-type commit-msg
```

---

## 2. `.pre-commit-config.yaml` — Structure

```yaml
# .pre-commit-config.yaml
default_install_hook_types: [pre-commit, commit-msg]
default_stages: [pre-commit]

repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
        args: [--unsafe]          # allows YAML with custom tags (e.g., !reference in GitLab CI)
      - id: check-toml
      - id: check-json
      - id: check-merge-conflict
      - id: check-added-large-files
        args: [--maxkb=1000]
      - id: detect-private-key
      - id: no-commit-to-branch
        args: [--branch, main, --branch, master]

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.2
    hooks:
      - id: mypy
        additional_dependencies:
          - pydantic>=2.0
          - types-redis
          - types-requests
        args: [--config-file=pyproject.toml]
        stages: [pre-push]        # slow; run on push, not commit

  - repo: https://github.com/commitizen-tools/commitizen
    rev: v3.29.0
    hooks:
      - id: commitizen
        stages: [commit-msg]
```

### Key Structural Elements

**`rev:`** — The exact version of the hook repository to use. Pre-commit pins these for reproducibility. Update with `pre-commit autoupdate`.

**`stages:`** — Controls when the hook runs. Valid stages:

| Stage | Git event |
|-------|-----------|
| `pre-commit` | Before `git commit` completes |
| `pre-push` | Before `git push` completes |
| `commit-msg` | After the commit message is written, before commit completes |
| `manual` | Only when explicitly invoked via `pre-commit run --hook-stage manual` |

**`additional_dependencies:`** — Packages to install into the hook's isolated environment. Required for mypy type stubs.

**`args:`** — Arguments passed to the hook. These extend (not replace) the hook's default arguments.

---

## 3. Essential Hooks Explained

### `pre-commit-hooks` — The Basics

These are low-cost, high-signal checks that run in milliseconds:

| Hook | What it catches |
|------|----------------|
| `trailing-whitespace` | Trailing spaces — merge conflict noise, diff noise |
| `end-of-file-fixer` | Missing newline at end of file — POSIX compliance, diff noise |
| `check-yaml` | YAML syntax errors before they reach CI |
| `check-toml` | TOML syntax errors — catches malformed `pyproject.toml` |
| `check-merge-conflict` | Committed `<<<<<<< HEAD` markers |
| `check-added-large-files` | Prevents accidentally committing data files, model weights, etc. |
| `detect-private-key` | Pattern-matches common private key headers — not foolproof, but catches accidents |
| `no-commit-to-branch` | Prevents direct commits to `main`/`master` — enforces PR workflow |

### `ruff` and `ruff-format`

Both run on every commit. `--fix` enables auto-fixing of safe issues — the commit proceeds with fixed files staged. This is the right default; it is annoying when a hook fails and makes no change, leaving the developer to re-run manually.

```yaml
- id: ruff
  args: [--fix, --exit-non-zero-on-fix]  # exit non-zero if fixes were applied
```

`--exit-non-zero-on-fix` is optional but recommended: it means the commit is aborted even when Ruff fixed the files, so the developer reviews the changes before recommitting. Without it, Ruff silently modifies and stages files, which can be surprising.

### `mypy` — On Push, Not Commit

mypy is slow. A full mypy run on a medium-sized codebase takes 10–60 seconds. On every commit, this becomes unbearable. The correct placement is `stages: [pre-push]` — it runs once before code hits remote, not on every intermediate commit.

```yaml
- id: mypy
  stages: [pre-push]
```

This means local commits are cheap; the mypy gate fires only when the developer pushes. CI then re-runs mypy as the authoritative check.

### `commitizen` — Conventional Commit Enforcement

Commitizen enforces the [Conventional Commits](https://www.conventionalcommits.org/) format at the `commit-msg` stage:

```
<type>(<scope>): <subject>

type: feat | fix | docs | style | refactor | test | chore | ci | perf
scope: optional, the affected module or area
subject: imperative, present tense, no period
```

Valid examples:
```
feat(pipeline): add incremental feature computation mode
fix(redis-store): handle connection timeout on cold start
chore(deps): bump ruff to 0.6.9
docs(readme): add environment setup instructions
```

Invalid examples (commitizen will reject):
```
Fixed the thing
WIP
Merged PR #42
```

Conventional Commits enable automated changelog generation and semantic version bumping (Chapter 10).

Configure commitizen in `pyproject.toml`:

```toml
[tool.commitizen]
name = "cz_conventional_commits"
tag_format = "v$version"
version_scheme = "semver"
version_provider = "pep621"
update_changelog_on_bump = true
major_version_zero = true  # 0.x.y versions: breaking changes don't bump major
```

---

## 4. Running Hooks in CI

Pre-commit should run in CI on the full file tree:

```yaml
# .github/workflows/ci.yml
jobs:
  pre-commit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version-file: ".python-version"
          enable-cache: true
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pre-commit
          key: pre-commit-${{ hashFiles('.pre-commit-config.yaml') }}
      - run: uv run pre-commit run --all-files
```

`--all-files` runs hooks against every file in the repository, regardless of what changed. This is necessary in CI because the CI run doesn't have a staged set of files — it checks the entire codebase.

**Why run pre-commit in CI at all, if mypy and ruff also run separately?**

Pre-commit in CI catches the class of issues that can only be verified with the hooks as configured — including `no-commit-to-branch` violations when developers push directly, large file additions, and YAML/TOML syntax errors that don't have separate CI jobs. It's also the easiest way to ensure the pre-commit configuration itself is correct.

---

## 5. Skipping Hooks

Sometimes a commit must happen despite a hook failure — typically during incident response or when intentionally committing something that a hook flags incorrectly.

```bash
# Skip a specific hook
SKIP=mypy git commit -m "fix: hotfix for incident-42"

# Skip all hooks (use sparingly; defeats the purpose)
git commit --no-verify -m "wip: do not merge"

# Skip multiple hooks
SKIP=mypy,ruff git commit -m "chore: temporary debug commit"
```

**Policy on skipping:**
- `SKIP=mypy` is acceptable during active development when committing work-in-progress that will be type-fixed before the PR is opened
- `--no-verify` is acceptable for emergency hotfixes when CI will still run as the authoritative gate
- Neither is acceptable as a regular workflow; it means the hook is misconfigured or has false positives that should be fixed

Document your team's skip policy in the contributing guide. If developers routinely skip a hook, the hook is either wrong or too aggressive.

---

## 6. Keeping Hooks Updated

Hook revisions go stale. `pre-commit autoupdate` updates all `rev:` values to the latest release:

```bash
uv run pre-commit autoupdate
```

Review the diff. Hook updates are low-risk (they add lint rules or fix bugs) but occasionally introduce new failures when existing code violates a newly-enabled rule. Treat hook updates like dependency updates — run CI after the update PR.

Automate this with Dependabot:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

Or schedule a `pre-commit autoupdate` cron job in GitHub Actions.

---

## 7. Writing a Custom Hook

When a project-specific check is needed that no existing hook covers:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: check-feature-schema
        name: Validate feature schema definitions
        language: python
        entry: python scripts/validate_feature_schema.py
        files: ^src/feature_pipeline/schemas/.*\.py$
        pass_filenames: true
```

The hook script receives matching filenames as arguments:

```python
#!/usr/bin/env python
# scripts/validate_feature_schema.py

import sys
from pathlib import Path

def validate(path: Path) -> bool:
    """Return True if the schema file is valid."""
    # Project-specific validation logic here
    content = path.read_text()
    if "UNREGISTERED_FEATURE" in content:
        print(f"ERROR: {path} contains an unregistered feature marker")
        return False
    return True

def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    failures = [p for p in paths if not validate(p)]
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
```

Custom hooks with `language: python` share the same isolated environment as the hook runner. Use `additional_dependencies` if the script needs packages:

```yaml
- id: check-feature-schema
  language: python
  entry: python scripts/validate_feature_schema.py
  additional_dependencies: [pydantic>=2.0]
```

---

## Summary

| Hook category | Stage | Frequency |
|---------------|-------|-----------|
| Whitespace, YAML, TOML fixers | `pre-commit` | Every commit |
| Ruff lint + format | `pre-commit` | Every commit |
| mypy | `pre-push` | Every push |
| Conventional commit message | `commit-msg` | Every commit |
| Pre-commit full suite | CI (`--all-files`) | Every PR |

| Decision | Recommendation |
|----------|---------------|
| Install hook types | `pre-commit` and `commit-msg` (run `pre-commit install --hook-type commit-msg`) |
| Ruff in hooks | Use `ruff-pre-commit` mirror; add `--fix` to auto-repair |
| mypy in hooks | Stage `pre-push`; too slow for every commit |
| Conventional commits | Enforce at `commit-msg` stage via commitizen |
| CI integration | `pre-commit run --all-files` in its own CI job |
| Skip policy | `SKIP=<hook>` acceptable for WIP; `--no-verify` only for emergencies |
| Hook updates | `pre-commit autoupdate`; automate with Dependabot or a scheduled CI job |

> **The measure of a good pre-commit setup:** a developer on their first day can clone the repo, run `uv sync && pre-commit install`, and have linting, formatting, and type feedback running in their local Git workflow within five minutes — with no manual tool installation beyond `uv`.
