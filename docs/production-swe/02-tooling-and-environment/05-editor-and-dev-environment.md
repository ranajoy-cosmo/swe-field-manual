# 05 — Editor and Dev Environment

## Why Shared Editor Configuration Is Worth the Controversy

The argument against checking in editor configuration is that it forces tool choices on contributors. The argument for it is that without shared configuration, every contributor's editor makes different decisions about tabs vs. spaces, line endings, and auto-formatting — and those differences appear in diffs, create merge conflicts, and generate review noise.

The resolution: **configure the baseline at the lowest level (`.editorconfig`)**, which is editor-agnostic, and **provide a recommended VS Code configuration** that is explicit about being a suggestion, not a mandate.

A dev environment that a new engineer can set up in under ten minutes is worth the marginal discomfort of having editor preferences documented.

---

## 1. `.editorconfig` — The Lowest-Friction Consistency Tool

`.editorconfig` is supported by almost every editor and IDE (VS Code, JetBrains, Vim, Emacs, Helix, Neovim, Sublime Text) without a plugin in many cases. It is the universal substrate for formatting consistency.

**Install:** Nothing. Most editors read `.editorconfig` natively. VS Code bundles the extension by default.

```ini
# .editorconfig
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4

[*.{yaml,yml,toml,json}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false  # trailing spaces are intentional in Markdown (line break)
max_line_length = off

[Makefile]
indent_style = tab   # Makefiles require tabs
indent_size = 4

[*.{sh,bash}]
indent_size = 2
```

**What `.editorconfig` enforces:**
- `end_of_line = lf`: LF (Unix) line endings everywhere. Prevents CRLF Windows line endings from appearing in diffs.
- `insert_final_newline = true`: POSIX requirement; prevents diff noise on the last line.
- `trim_trailing_whitespace = true`: Pairs with the pre-commit `trailing-whitespace` hook.
- `indent_style = space`: Python requires spaces. `.editorconfig` prevents a tab accidentally slipping in.
- `indent_size = 4`: Python community standard (PEP 8).

**What `.editorconfig` cannot enforce:** It configures the editor to *generate* correct output, but it does not check existing files. The `trailing-whitespace` and `end-of-file-fixer` pre-commit hooks are the enforcement layer.

---

## 2. VS Code Configuration

VS Code configuration is split into two files: `settings.json` (editor behavior) and `extensions.json` (recommended extensions). Both live in `.vscode/` and are checked into source control.

**The controversy:** checking in VS Code config forces VS Code preferences on contributors who use other editors. The position taken here is that `.vscode/extensions.json` is a *recommendation*, not a mandate, and `.vscode/settings.json` should only configure things the project already enforces via other means (ruff, mypy). A JetBrains or Helix user is not harmed by the presence of a `.vscode/` directory.

### `.vscode/settings.json`

```json
{
  // Python interpreter — use the uv-managed venv
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",

  // Disable the built-in Python linting (we use Ruff)
  "python.linting.enabled": false,
  "python.linting.pylintEnabled": false,
  "python.linting.flake8Enabled": false,

  // Ruff as the linter and formatter
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  },

  // Type checking via Pylance (pyright)
  "python.analysis.typeCheckingMode": "standard",
  "python.analysis.autoImportCompletions": true,

  // Test discovery
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests"],
  "python.testing.unittestEnabled": false,

  // Editor baseline — should match .editorconfig
  "editor.rulers": [88],
  "editor.insertSpaces": true,
  "editor.tabSize": 4,
  "files.trimTrailingWhitespace": true,
  "files.insertFinalNewline": true,
  "files.eol": "\n",

  // File exclusions — keep the explorer clean
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.pyc": true,
    "**/.mypy_cache": true,
    "**/.ruff_cache": true,
    "**/*.egg-info": true
  },

  // YAML schema validation
  "yaml.schemas": {
    "https://json.schemastore.org/github-workflow.json": ".github/workflows/*.yml",
    "https://json.schemastore.org/pre-commit-config.json": ".pre-commit-config.yaml"
  }
}
```

### `.vscode/extensions.json`

```json
{
  "recommendations": [
    "charliermarsh.ruff",          // Ruff linter and formatter
    "ms-python.python",            // Python language support
    "ms-python.pylance",           // Pyright-based type checking
    "ms-python.debugpy",           // Python debugger
    "tamasfe.even-better-toml",   // TOML syntax highlighting and validation
    "redhat.vscode-yaml",          // YAML language support + schema validation
    "eamodio.gitlens",             // Git blame, history, diff
    "editorconfig.editorconfig",   // .editorconfig support
    "github.vscode-pull-request-github", // GitHub PR review inline
    "streetsidesoftware.code-spell-checker" // Catch typos in comments and strings
  ]
}
```

When a contributor opens the project, VS Code prompts: "This workspace has extension recommendations. Do you want to install them?" They can accept or decline.

---

## 3. Dev Containers

A dev container is a Docker-based development environment defined in `.devcontainer/devcontainer.json`. Any developer with VS Code + Docker (or GitHub Codespaces) can get an identical environment with a single click.

**When dev containers are worth it:**
- The service depends on system-level tools (e.g., a specific version of `libgomp`, CUDA runtime, `protoc`)
- The team has diverse operating systems (Windows + Mac + Linux)
- Onboarding time is a significant cost

**When dev containers are overkill:**
- Pure Python projects with only Python-level dependencies
- Small teams with a single OS preference
- Projects where the Docker build time exceeds the onboarding cost

### `.devcontainer/devcontainer.json`

```json
{
  "name": "feature-pipeline",
  "image": "mcr.microsoft.com/devcontainers/python:3.12-bullseye",

  "features": {
    "ghcr.io/devcontainers/features/docker-in-docker:2": {}
  },

  "postCreateCommand": "curl -LsSf https://astral.sh/uv/install.sh | sh && uv sync && pre-commit install",

  "customizations": {
    "vscode": {
      "settings": {
        "python.defaultInterpreterPath": "/workspace/.venv/bin/python"
      },
      "extensions": [
        "charliermarsh.ruff",
        "ms-python.python",
        "ms-python.pylance"
      ]
    }
  },

  "mounts": [
    "source=${localWorkspaceFolder},target=/workspace,type=bind"
  ],

  "remoteUser": "vscode",
  "workspaceFolder": "/workspace"
}
```

The `postCreateCommand` runs once after the container is created:
1. Installs `uv`
2. Runs `uv sync` — installs all dependencies from `uv.lock`
3. Installs pre-commit hooks

After this, the container is fully operational. No additional manual steps.

---

## 4. `Makefile` as a Task Runner

`make` is a near-universal task runner that works on any Unix-like system without additional tooling. A `Makefile` at the project root provides a standard interface for common operations regardless of the underlying tool implementation.

The value is *discoverability* and *consistency*: a new engineer doesn't need to know that linting runs via `uv run ruff check .` — they know it's `make lint`.

```makefile
# Makefile
.PHONY: install dev test lint format typecheck clean

# Default target — show available commands
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime and dev dependencies
	uv sync

dev: ## Start the development server with hot reload
	uv run uvicorn feature_pipeline.api.main:app --reload --port 8000

test: ## Run the full test suite
	uv run pytest tests/ -v --tb=short

test-unit: ## Run unit tests only
	uv run pytest tests/unit/ -v

test-integration: ## Run integration tests (requires Docker)
	uv run pytest tests/integration/ -v --tb=short

lint: ## Run Ruff linter
	uv run ruff check .

format: ## Run Ruff formatter
	uv run ruff format .

format-check: ## Check formatting without writing (for CI)
	uv run ruff format --check .

typecheck: ## Run mypy type checker
	uv run mypy src/

typecheck-strict: ## Run both mypy and pyright
	uv run mypy src/
	uv run pyright src/

pre-commit: ## Run all pre-commit hooks against all files
	uv run pre-commit run --all-files

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .mypy_cache .ruff_cache dist build *.egg-info

build: ## Build the distribution package
	uv build

ci: lint format-check typecheck test ## Run the full CI pipeline locally
```

### Makefile Conventions

**`.PHONY`** — Declare all targets that are not file outputs. Without this, `make test` would not run if a file named `test` exists in the directory.

**`## ` comments** — The `help` target grep pattern extracts these comments to display usage. `make` with no arguments shows the available commands. This is a low-cost discoverability mechanism.

**`uv run` prefix** — All commands use `uv run`, which ensures they execute inside the managed virtual environment regardless of the developer's shell state. This eliminates "wrong Python" errors.

**`ci` target** — A local equivalent of the CI pipeline. Developers can run `make ci` before pushing to catch failures without waiting for CI.

---

## 5. Environment Variable Management

Environment variables are the correct way to configure a service across environments (development, staging, production) without code changes. This is Twelve-Factor App principle III.

### `.env` Files for Local Development

```bash
# .env.example  — committed to source control; safe values only
DATABASE_URL=postgresql://localhost:5432/feature_pipeline_dev
REDIS_URL=redis://localhost:6379/0
LOG_LEVEL=DEBUG
FEATURE_STORE_API_KEY=your_api_key_here  # replace with real value
```

```bash
# .env  — NOT committed; contains actual secrets
DATABASE_URL=postgresql://localhost:5432/feature_pipeline_dev
REDIS_URL=redis://localhost:6379/0
LOG_LEVEL=DEBUG
FEATURE_STORE_API_KEY=sk-abc123real
```

`uv run` automatically loads `.env` if `python-dotenv` is installed and the entry point loads it. Alternatively, load explicitly:

```python
# src/feature_pipeline/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str
    redis_url: str
    log_level: str = "INFO"
    feature_store_api_key: str

settings = Settings()
```

`pydantic-settings` reads from `.env` in development and from environment variables in production. The settings object is a typed, validated representation of the runtime configuration.

```bash
uv add pydantic-settings
```

### Rules for `.env` Files

| Rule | Reason |
|------|--------|
| Never commit `.env` | It contains secrets. Add to `.gitignore`. |
| Always commit `.env.example` | Documents required variables for new contributors |
| Keep `.env.example` in sync | Add new variables here as they are introduced in code |
| Use `detect-private-key` pre-commit hook | Catches accidental commits of key material |
| Use `pydantic-settings` for validation | Missing required variables fail at startup, not at runtime |

The `detect-private-key` hook matches patterns like `-----BEGIN RSA PRIVATE KEY-----`. It is not a substitute for a full secrets scanner (Chapter 07 covers `detect-secrets` and GitHub secret scanning) but it catches the most common accidents.

### Secrets in Production

`.env` files are for local development only. In production:

- **GCP Secret Manager / AWS Secrets Manager / HashiCorp Vault**: IAM-controlled, versioned, audit-logged (Chapter 07)
- **Kubernetes Secrets**: injected as environment variables into the pod
- **GitHub Actions secrets**: `${{ secrets.FEATURE_STORE_API_KEY }}` — available to CI jobs

The application code is the same in all environments. The difference is where the environment variables come from. `pydantic-settings` doesn't care — it reads from the environment regardless of the source.

---

## Summary

| Tool | Purpose | Commit? |
|------|---------|---------|
| `.editorconfig` | Universal formatting baseline | Yes |
| `.vscode/settings.json` | VS Code-specific tool configuration | Yes |
| `.vscode/extensions.json` | Extension recommendations | Yes |
| `.devcontainer/devcontainer.json` | Reproducible Docker-based dev environment | Yes |
| `Makefile` | Task runner with standard targets | Yes |
| `.env.example` | Template for required environment variables | Yes |
| `.env` | Actual secrets and local overrides | **Never** |

| Decision | Recommendation |
|----------|---------------|
| `.editorconfig` | Always; LF line endings, 4-space Python indent, 2-space YAML/TOML |
| VS Code settings | Check in; scope to project-enforced behavior only |
| Dev containers | Use when system-level dependencies differ across developer machines |
| Makefile | Always; `make ci` as the local equivalent of the CI pipeline |
| Settings management | `pydantic-settings` with a `Settings` class; fail fast on missing variables |
| Secrets | `.env` for local development only; Secret Manager/Vault for production |

> **The benchmark for a good dev environment:** a new engineer with `uv` installed can run `git clone && cd <project> && uv sync && make dev` and have a working local service. No undocumented manual steps. No "ask the team" required.
