# 02 — Dependency Management

> Full treatment of `pyproject.toml`, publishing, and lockfile semantics for libraries vs. applications is in Chapter 10. This file covers the day-to-day workflow a developer runs repeatedly.

## Why Dependency Management Is Not Just `pip install`

Ad-hoc `pip install` is fine for a throwaway script. It is a reliability problem in a production service for three reasons:

1. **No lockfile → non-deterministic environments.** `pip install requests` today gives you `requests==2.32.3`. In two months it gives you `requests==2.33.0`. If that version introduced a regression, it fails in CI but not locally (or vice versa), and the failure is attributed to code changes rather than dependency drift.

2. **No dependency groups → blurred boundaries.** Test tools, linting tools, and documentation generators leak into the environment that runs in production if they are all installed together. Tracking what is a runtime dependency vs. a dev tool becomes manual work.

3. **No environment isolation → "works on my machine" bugs.** Without a reproducible environment, debugging is always entangled with the question of whether the dependency set differs between machines.

`uv` solves all three with a single, fast tool.

---

## 1. `uv` — Core Workflow

`uv` is a Python package manager written in Rust. It replaces `pip`, `pip-tools`, `virtualenv`, and `pyenv` for most workflows.

**Install:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Project Initialization

```bash
# New project
uv init feature-pipeline
cd feature-pipeline

# Existing project — just create the lock
uv lock
```

`uv init` creates:
```
feature-pipeline/
├── src/
│   └── feature_pipeline/
│       └── __init__.py
├── pyproject.toml
├── uv.lock
├── .python-version
└── README.md
```

### The Four Commands You Run Daily

```bash
# Add a runtime dependency
uv add httpx

# Add a development-only dependency
uv add --dev pytest ruff mypy

# Sync the environment to the lockfile (what CI runs)
uv sync

# Run a command inside the managed environment
uv run pytest
uv run python -m feature_pipeline
```

`uv sync` is the single idempotent operation that brings any environment to the exact state described by `uv.lock`. Run it after every `git pull`.

### Removing and Updating

```bash
# Remove a dependency
uv remove httpx

# Update a single dependency
uv add httpx@latest

# Update all dependencies within their version constraints
uv lock --upgrade

# Update a single dependency to latest, regardless of constraints
uv lock --upgrade-package httpx
```

---

## 2. `.python-version`

A single-line file at the project root that pins the Python version:

```
3.12.3
```

`uv` reads `.python-version` automatically and will install that exact Python version if it is not present on the system. This eliminates the "which Python are you using?" class of bugs.

```bash
# uv installs Python 3.12.3 if not available, then creates the venv
uv sync
```

**Rules:**
- Commit `.python-version` always
- Use the exact version (e.g., `3.12.3`), not a range — ranges defeat the purpose of pinning
- Match the version in your Docker base image (Chapter 10) and CI matrix (Chapter 07)

```yaml
# .github/workflows/ci.yml — must match .python-version
- uses: astral-sh/setup-uv@v3
  with:
    python-version-file: ".python-version"
```

---

## 3. Dependency Groups

Python's `pyproject.toml` supports two distinct mechanisms for grouping dependencies. They serve different purposes.

### `[project.optional-dependencies]` — Extras

For dependencies that a *consumer* of your package might optionally install:

```toml
[project.optional-dependencies]
redis = ["redis>=5.0"]
kafka = ["confluent-kafka>=2.0"]
```

A consumer installs these with:
```bash
pip install feature-pipeline[redis]
uv add feature-pipeline[redis]
```

Use extras for optional feature bundles that end users of your library might need. Do not use them for dev tools — a library consumer should never install `pytest`.

### `[dependency-groups]` — Dev Groups (PEP 735)

For dependencies that are *never* installed by consumers; only by developers and CI:

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "mypy>=1.11",
]
types = [
    "types-redis",
    "types-requests",
]
docs = [
    "mkdocs-material>=9.0",
    "mkdocstrings[python]>=0.25",
]
```

`uv sync` installs all groups by default in development. In production:

```bash
# Install only runtime dependencies (no dev groups)
uv sync --no-dev
```

In a Docker image:

```dockerfile
RUN uv sync --frozen --no-dev
```

### Choosing Between Extras and Groups

| Situation | Use |
|-----------|-----|
| Optional runtime feature (e.g., Redis support) | `[project.optional-dependencies]` |
| Dev tool (pytest, ruff, mypy) | `[dependency-groups]` |
| CI-only tool (coverage reporter, test runner) | `[dependency-groups]` → `dev` group |
| Docs generator | `[dependency-groups]` → `docs` group |

---

## 4. `uv pip` vs. `uv sync`

These are distinct commands for distinct purposes.

| Command | When to use |
|---------|-------------|
| `uv sync` | The primary workflow command. Syncs the entire environment to `uv.lock`. Use in CI and after `git pull`. |
| `uv pip install <pkg>` | One-off installs into the current environment *without* touching `pyproject.toml` or `uv.lock`. Use for temporary exploration. |
| `uv add <pkg>` | Add a dependency to `pyproject.toml` *and* update `uv.lock`. The correct way to add a permanent dependency. |

The danger of `uv pip install` in a workflow context: the package is installed but not tracked. The next `uv sync` will remove it. Use `uv add` for anything that should persist.

```bash
# Wrong: temporary and will be removed by next uv sync
uv pip install pandas

# Right: permanent, tracked in pyproject.toml and uv.lock
uv add pandas
```

---

## 5. The Lockfile

`uv.lock` is a machine-generated file. Never edit it manually.

### Applications: Always Commit

For deployed services, the lockfile is the reproducibility guarantee. CI and production use `uv sync --frozen`, which fails if `uv.lock` is out of sync with `pyproject.toml`. This is intentional — it catches cases where someone edited `pyproject.toml` without regenerating the lock.

```bash
# CI
uv sync --frozen
```

### Libraries: Commit for Developer Convenience

For a library (a package that other projects depend on), committing `uv.lock` means contributors get a reproducible environment. However, the lockfile is *not* used by consumers of the library — they get the lockfile from their own project. Committing it is a developer quality-of-life decision, not a reproducibility requirement.

See Chapter 10 for the full discussion on library vs. application lockfile policy.

---

## 6. Dependency Update Strategy

Dependencies go stale. Security vulnerabilities are patched; APIs are deprecated. An update strategy prevents the choice between "update everything at once (risky)" and "never update (more risky)."

### Automated: Dependabot or Renovate Bot

Configure GitHub's Dependabot or Renovate to open PRs for dependency updates on a schedule:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      dev-dependencies:
        dependency-type: "development"
```

Each PR is small, scoped to one (or a handful of) packages, and runs the full CI suite. The update is merged or rejected in isolation. This is strongly preferred over batched manual updates.

### Manual: Scheduled Upgrade Runs

For teams not using automated bots, schedule a monthly dependency update:

```bash
# Update all packages within their declared constraints
uv lock --upgrade

# Run tests
uv run pytest

# Review the diff — uv.lock will show exactly what changed
git diff uv.lock
```

The `uv.lock` diff is the audit trail. Commit it with a message like:

```
chore: bump dependencies (monthly update)

Updated:
- httpx 0.27.0 → 0.27.2
- pydantic 2.8.0 → 2.9.1
```

### Pinning Specific Packages

Some dependencies need to be pinned — usually because a newer version has a breaking change or known incompatibility:

```toml
[project]
dependencies = [
    "some-package>=1.2,<2.0",  # <2.0 has breaking API changes
]
```

Document *why* a pin exists in a comment or in the project's `CHANGELOG.md`. Unexplained pins become permanent fixtures that nobody removes.

---

## Summary

| Decision | Recommendation |
|----------|---------------|
| Package manager | `uv` — replaces pip, pip-tools, virtualenv |
| Python version | Pin exact version in `.python-version`; commit it |
| Dev tools | `[dependency-groups]`, not `[project.optional-dependencies]` |
| Optional features | `[project.optional-dependencies]` extras |
| Adding a dependency | `uv add <pkg>` — updates both `pyproject.toml` and `uv.lock` |
| Ad-hoc installs | `uv pip install` — temporary, not tracked |
| CI sync | `uv sync --frozen` — fails fast if lockfile is stale |
| Production Docker | `uv sync --frozen --no-dev` |
| Update strategy | Automated (Dependabot/Renovate) preferred; monthly manual run as fallback |

> **The test of a good dependency setup:** a new engineer can clone the repo, run `uv sync`, and have the exact same environment as CI — down to the patch version of every transitive dependency.
