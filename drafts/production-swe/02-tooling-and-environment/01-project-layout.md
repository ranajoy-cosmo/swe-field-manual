# 01 — Project Layout

## Why Layout Is a Production Concern

The directory structure of a Python project is not a cosmetic decision. It determines:

- **Whether `import` works correctly** when the package is installed vs. run directly from source
- **Whether tests exercise the installed code** or accidentally import from the working tree
- **Where CI looks** for source, tests, and configuration
- **How fast new engineers can orient themselves** — a consistent layout is a shared mental model

A poorly structured project creates subtle bugs (wrong package imported), CI failures that only appear in specific execution orders, and onboarding friction that compounds across every new engineer.

---

## 1. The `src/` Layout

The recommended default for any Python package that will be installed or distributed.

```
feature-pipeline/
├── src/
│   └── feature_pipeline/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── pipeline.py
│       │   └── transforms.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── routes.py
│       └── infrastructure/
│           ├── __init__.py
│           └── redis_store.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── scripts/
│   └── backfill_features.py
├── pyproject.toml
├── uv.lock
├── .python-version
├── .pre-commit-config.yaml
├── .editorconfig
├── Makefile
└── README.md
```

### Why `src/` and Not a Flat Layout

The flat layout (package directory at the project root) has one critical failure mode: Python adds the current directory to `sys.path` on startup. This means `import feature_pipeline` will resolve to `./feature_pipeline/` — the source tree — rather than the *installed* package. Consequences:

1. **Tests may pass locally but fail in CI** if the package isn't installed and CI runs with a different working directory
2. **Packaging bugs go undetected** — a missing `__init__.py` or misconfigured `[tool.hatch.build]` is invisible until a user reports a broken install
3. **Editable installs behave differently from regular installs**, making it impossible to test the package as a consumer would see it

The `src/` layout solves this by ensuring the package is *not* on `sys.path` unless explicitly installed. Running `uv sync` installs the package in editable mode; from that point forward, `import feature_pipeline` resolves to the installed package regardless of working directory.

```bash
# After uv sync, this is safe from anywhere:
python -c "import feature_pipeline; print(feature_pipeline.__file__)"
# → /path/to/project/src/feature_pipeline/__init__.py  (editable install)
```

### Enabling `src/` in `pyproject.toml`

With `hatchling` (the recommended build backend):

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/feature_pipeline"]
```

With `setuptools`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Both tell the build backend where to find the Python package. `uv` respects this when installing.

---

## 2. `__init__.py` as a Public API Surface

`__init__.py` is not just a marker file. It is the *public contract* of a package. What is re-exported from `__init__.py` is public; everything else is an implementation detail free to change without a semver bump.

```python
# src/feature_pipeline/__init__.py

from feature_pipeline.core.pipeline import FeaturePipeline
from feature_pipeline.core.transforms import StandardScalerTransform
from feature_pipeline.infrastructure.redis_store import RedisFeatureStore

__all__ = [
    "FeaturePipeline",
    "StandardScalerTransform",
    "RedisFeatureStore",
]
```

Callers do:

```python
from feature_pipeline import FeaturePipeline  # stable, public
```

Not:

```python
from feature_pipeline.core.pipeline import FeaturePipeline  # internal path, may change
```

Enforce this discipline in the linting config:

```toml
[tool.ruff.lint]
# Prevent importing from internal submodules directly
# (Manual convention; consider using `import-linter` for hard enforcement)
```

For hard enforcement of import boundaries, see `import-linter` (Chapter 06).

### Subpackage `__init__.py` Discipline

Internal subpackage `__init__.py` files (e.g., `core/__init__.py`) should typically be *empty* or contain only `__all__ = []`. Do not re-export across layers from internal `__init__.py` files — it creates circular import traps.

```python
# src/feature_pipeline/core/__init__.py
# Intentionally empty — imports happen from the top-level __init__.py
```

---

## 3. The Standard File Inventory

Every production Python project should have these files at the root:

| File | Purpose |
|------|---------|
| `pyproject.toml` | Single source of truth for metadata, deps, tool config. See Chapter 10. |
| `uv.lock` | Deterministic lockfile. **Always commit for applications; review for libraries.** |
| `.python-version` | Pins the Python version for `uv` and `pyenv`. One line: `3.12.3` |
| `.pre-commit-config.yaml` | Hook configuration. See `04-pre-commit-hooks.md`. |
| `.editorconfig` | Cross-editor formatting baseline. See `05-editor-and-dev-environment.md`. |
| `Makefile` | Task runner — `make test`, `make lint`, `make dev`. |
| `README.md` | Entry point for humans. Includes setup instructions. |
| `.gitignore` | Standard Python gitignore + project-specific patterns. |
| `.github/` | GitHub Actions workflows, PR templates, CODEOWNERS. |

Files that **must not** be committed:

| File | Reason |
|------|--------|
| `.env` | Contains secrets. Use `.env.example` as a template. |
| `__pycache__/`, `*.pyc` | Regenerated on every run; binary and ephemeral. |
| `.venv/` | Reproducible from `uv.lock`; large and machine-specific. |
| `*.egg-info/` | Build artifact; regenerated by install. |

Canonical `.gitignore` starters: [`github.com/github/gitignore/blob/main/Python.gitignore`](https://github.com/github/gitignore/blob/main/Python.gitignore).

---

## 4. `tests/` Directory Structure

Tests live outside `src/`. The structure mirrors the source tree:

```
tests/
├── conftest.py              # root fixtures: db session, client, settings
├── unit/
│   ├── test_pipeline.py     # mirrors src/feature_pipeline/core/pipeline.py
│   └── test_transforms.py
├── integration/
│   ├── conftest.py          # integration-specific fixtures (containers)
│   └── test_redis_store.py
└── contract/
    └── test_schema_pacts.py
```

The `conftest.py` hierarchy is discussed in detail in Chapter 03. One rule here: **the test root `conftest.py` must not import from `tests/` subdirectories**. Only downward imports are safe.

---

## 5. Mono-repo vs. Multi-repo

The choice between a mono-repo (all services in one repository) and a multi-repo (one repository per service) is a team-structure and release-cadence decision, not a technical one.

### Mono-repo

All services under one root, often with a `services/` or `packages/` top-level directory:

```
platform/
├── services/
│   ├── feature-pipeline/
│   │   ├── src/
│   │   └── pyproject.toml
│   └── model-serving/
│       ├── src/
│       └── pyproject.toml
├── libs/
│   └── shared-types/
│       ├── src/
│       └── pyproject.toml
└── pyproject.toml          # workspace root (uv workspace)
```

**Advantages:**
- Atomic cross-service changes (update shared library + all consumers in one PR)
- Single CI pipeline; one place to look for build status
- Easier discoverability of shared code; prevents duplication

**Disadvantages:**
- CI time grows with the number of services unless paths-based filtering is implemented
- Build tooling complexity (workspace configuration, selective CI)
- A broken commit blocks *all* services if CI is not service-isolated

**`uv` workspaces** (analogous to npm/Cargo workspaces) provide native mono-repo support:

```toml
# Root pyproject.toml
[tool.uv.workspace]
members = ["services/*", "libs/*"]
```

Each member has its own `pyproject.toml`. `uv sync` installs all workspace members in development mode. A single `uv.lock` covers the entire workspace.

### Multi-repo

One repository per service, with shared libraries published to a private registry (GCP Artifact Registry, Artifactory, etc.).

**Advantages:**
- Independent CI: a failure in one service does not block others
- Cleaner ownership model — one team, one repo
- No workspace tooling complexity

**Disadvantages:**
- Cross-service changes require coordinated PRs across repositories
- Shared library updates require a publish-and-upgrade cycle in every consumer
- Discoverability is harder; teams duplicate code instead of sharing

### Decision Rule: The Two-Team Test

> If two independent teams need to deploy the code on different release cadences, it belongs in different repositories.

For ML infrastructure teams, the common split is:

| Repository | Rationale |
|------------|-----------|
| `feature-pipeline` service | Deployed independently, owned by data engineering |
| `model-serving` service | Different scaling profile, owned by ML serving team |
| `ml-platform-libs` mono-repo | Shared types, feature definitions — single release train |

---

## 6. `scripts/` and `notebooks/` Directories

Scripts are operational one-offs (backfills, migrations, data fixes) and should live in `scripts/`. They are not part of the installed package and do not belong in `src/`.

```
scripts/
├── backfill_features.py   # run with: uv run scripts/backfill_features.py
├── validate_schema.py
└── README.md              # documents what each script does and when to run it
```

Notebooks live in `notebooks/` and follow the naming convention `{number}-{author-initials}-{description}.ipynb` (e.g., `01-rj-feature-exploration.ipynb`). Notebooks are exploration tools, not production code. A notebook that is "good enough" to deploy is a notebook that should be refactored into `src/`.

---

## Summary

| Decision | Recommendation |
|----------|---------------|
| Layout | `src/` layout. Always. |
| `__init__.py` top-level | Explicit re-exports only; defines public API surface |
| `__init__.py` subpackages | Empty or minimal; avoid re-exporting across layers |
| Lockfile | Commit for applications; conditional for libraries (see Chapter 10) |
| `.python-version` | Commit always; one-line version pin |
| Mono vs. multi-repo | Use the two-team test; default to mono-repo for ML platform teams |
| Scripts | `scripts/` directory; never in `src/` |
| Notebooks | `notebooks/`; exploration only, not production code |

> **The canonical sign of a well-structured project:** a new engineer can clone the repo, run `uv sync && make dev`, and have a working local environment within five minutes.
