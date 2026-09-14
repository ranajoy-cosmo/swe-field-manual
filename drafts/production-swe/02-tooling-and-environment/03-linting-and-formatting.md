# 03 — Linting and Formatting

## Why Automated Style Enforcement Matters

Code review is expensive. Engineer time spent commenting on import ordering, missing type annotations, or unused variables is time not spent on logic, architecture, or correctness. Automated style enforcement eliminates entire categories of review comments before a PR is opened.

More importantly, automated enforcement is *consistent*. Human reviewers have preferences that vary by reviewer and mood. A linting rule is binary and unconditional. This removes the friction of "but the other reviewer said it was fine last week."

The model for a production Python project:

- **Ruff** — fast, unified linter and formatter. Runs in pre-commit and CI.
- **mypy** — type checker. Runs in CI as the authoritative type gate.
- **pyright** — type checker. Runs in the editor for real-time feedback.

These three tools have distinct roles. They are not alternatives to each other.

---

## 1. Ruff — Linting and Formatting

Ruff is the current standard for Python linting. Written in Rust, it is 10–100× faster than the tools it replaces (flake8, isort, pyupgrade, pydocstyle). Configuration lives entirely in `pyproject.toml`.

**Install:**
```bash
uv add --dev ruff
```

### Rule Groups

Ruff organizes rules into groups, each corresponding to a lint category. The recommended configuration for a production Python service:

```toml
[tool.ruff]
target-version = "py310"
line-length = 88
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E",    # pycodestyle: style errors (indentation, whitespace, blank lines)
    "W",    # pycodestyle: style warnings (trailing whitespace, blank line warnings)
    "F",    # pyflakes: undefined names, unused imports, unused variables
    "I",    # isort: import ordering
    "B",    # flake8-bugbear: common bugs and design issues
    "C4",   # flake8-comprehensions: unnecessary comprehension patterns
    "UP",   # pyupgrade: deprecated syntax modernization
    "N",    # pep8-naming: naming convention enforcement
    "SIM",  # flake8-simplify: unnecessary control flow complexity
    "RUF",  # ruff-specific: rules without an upstream equivalent
]
ignore = [
    "E501",   # line too long — the formatter handles this
    "B008",   # function call in default args — common pattern in FastAPI Depends()
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = [
    "S101",   # allow assert in tests (flake8-bandit)
    "ARG",    # allow unused arguments in test fixtures
]
"scripts/**" = [
    "T201",   # allow print() in scripts
    "INP001", # scripts are not part of a package
]
```

### What Each Group Catches

**`E` / `W` — pycodestyle**

Indentation, whitespace, blank lines, line length. These are the bikeshed rules — individually minor, collectively the background noise that slows reading. Let the formatter handle `E501`; enforce the rest.

**`F` — pyflakes**

The highest-signal group:
- `F401`: unused imports. Cleanliness and a sign of dead code.
- `F811`: redefinition of an unused name. Common when refactoring.
- `F821`: undefined names. Catches `NameError` before runtime.

**`I` — isort**

Import ordering. The rule: standard library → third-party → first-party, each group separated by a blank line. Ruff's isort is configuration-compatible with standalone isort:

```toml
[tool.ruff.lint.isort]
known-first-party = ["feature_pipeline"]
split-on-trailing-comma = true
```

**`B` — flake8-bugbear**

Common Python bugs that are syntactically valid but semantically wrong:

- `B006`: mutable default arguments — `def foo(items: list = [])` is a classic Python trap
- `B007`: loop variable not used in loop body
- `B017`: `assertRaises(Exception)` catches too broadly
- `B023`: function defined in a loop captures loop variable by reference

```python
# B006 — caught by Ruff
def append_item(item: str, items: list[str] = []) -> list[str]:  # BAD
    items.append(item)
    return items

# Fixed
def append_item(item: str, items: list[str] | None = None) -> list[str]:
    if items is None:
        items = []
    items.append(item)
    return items
```

**`C4` — flake8-comprehensions**

Unnecessary patterns around list/set/dict comprehensions:
- `C400`: `list(x for x in ...)` → `[x for x in ...]`
- `C401`: `set(x for x in ...)` → `{x for x in ...}`
- `C417`: `map(lambda x: x * 2, items)` → `[x * 2 for x in items]`

**`UP` — pyupgrade**

Modernizes Python syntax to the `target-version`:
- `UP007`: `Optional[X]` → `X | None`
- `UP006`: `List[X]` → `list[X]` (Python 3.9+)
- `UP035`: deprecated `typing` imports → `collections.abc`
- `UP032`: `"{}".format(x)` → f-string

**`N` — pep8-naming**

- `N801`: class names should be `CapWords`
- `N802`: function names should be `lowercase_with_underscores`
- `N806`: variable in function should be `lowercase`

**`SIM` — flake8-simplify**

- `SIM102`: collapsible `if` statements
- `SIM108`: ternary operator instead of `if`/`else` block
- `SIM117`: merge nested `with` statements

**`RUF` — Ruff-specific**

- `RUF010`: use explicit conversion flag in f-string (`f"{x!r}"` vs `f"{repr(x)}"`)
- `RUF012`: mutable class attributes should be annotated with `ClassVar`
- `RUF100`: unused `# noqa` directives (prevents `noqa` sprawl)

### Additional Groups Worth Enabling

For security-sensitive code (APIs handling external input):

```toml
select = [
    # ... base groups above ...
    "S",    # flake8-bandit: security issues (hardcoded passwords, shell injection, etc.)
    "ANN",  # flake8-annotations: enforces type annotations on all public functions
]
```

`S` (bandit) is high-noise but catches real issues: `S105` (hardcoded passwords), `S108` (insecure temp file), `S324` (MD5/SHA1 for hashing). Tune `per-file-ignores` to suppress expected positives.

### Ruff Usage

```bash
# Lint only
ruff check .

# Lint and auto-fix safe issues
ruff check --fix .

# Format
ruff format .

# Check formatting without writing (for CI)
ruff format --check .

# Show specific rule explanation
ruff rule B006
```

### Ruff Formatter vs. Black

Ruff's formatter is intentionally Black-compatible. The output is virtually identical for the vast majority of code. The practical difference:

| Aspect | Ruff | Black |
|--------|------|-------|
| Speed | ~100× faster | Baseline |
| Magic trailing comma | Supported | Supported |
| Configuration surface | Minimal (intentional) | Minimal |
| `pyproject.toml` | Native | Native |

**Recommendation:** Use Ruff's formatter. If a project already uses Black, the migration is a one-line `pyproject.toml` change plus a `ruff format .` run. The diff is cosmetic and can be committed as a single formatting commit.

---

## 2. mypy — Type Checking in CI

mypy is Python's reference type checker. It is the authoritative gate in CI. If mypy passes, the codebase's type annotations are internally consistent.

**Install:**
```bash
uv add --dev mypy
```

### Configuration for a Library vs. Application

Type checking strictness is calibrated differently depending on whether you are building a library (consumed by others) or an application (deployed as a service).

**Application — strict:**
```toml
[tool.mypy]
python_version = "3.12"
strict = true
# strict enables: disallow_any_generics, disallow_untyped_defs,
#   warn_return_any, warn_unused_ignores, and more

# Overrides for third-party stubs
[[tool.mypy.overrides]]
module = [
    "confluent_kafka.*",
    "pandera.*",
]
ignore_missing_imports = true
```

**Library — strict, but with a narrow public surface:**
```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_unused_configs = true

# Internal implementation modules can be less strict
[[tool.mypy.overrides]]
module = ["feature_pipeline.internal.*"]
disallow_untyped_defs = false
```

### Key mypy Flags

| Flag | Effect |
|------|--------|
| `strict` | Enables the full strict suite (recommended starting point) |
| `disallow_untyped_defs` | All function signatures must have type annotations |
| `warn_return_any` | Warn when a function returns `Any` (often unintentional) |
| `warn_unused_ignores` | Flag `# type: ignore` comments that are no longer needed |
| `no_implicit_optional` | `def f(x: str = None)` must be `str \| None` |
| `check_untyped_defs` | Type-check the body of unannotated functions too |

### Handling Missing Stubs

Many third-party libraries lack type stubs. Options:

1. **Install stubs from `types-*` packages:**
```bash
uv add --dev types-redis types-requests
```

2. **Use `ignore_missing_imports` per module** (in `[[tool.mypy.overrides]]`):
```toml
[[tool.mypy.overrides]]
module = ["some_untyped_library.*"]
ignore_missing_imports = true
```

3. **Create a local stub file** (`src/stubs/some_library.pyi`) for libraries your team controls that lack stubs.

4. **Use `py.typed` marker** (Chapter 10) so that *your* library ships its types and downstream mypy runs don't need stubs.

### Suppressing Specific Errors

Use `# type: ignore[error-code]` — never bare `# type: ignore`:

```python
# Bad: suppresses all type errors on this line
result = fetch_data()  # type: ignore

# Good: specific suppression with a comment explaining why
result = fetch_data()  # type: ignore[return-value]  # third-party returns Any
```

`warn_unused_ignores = true` ensures that suppressed errors that are no longer triggered are flagged — preventing `# type: ignore` rot.

---

## 3. pyright — Type Checking in the Editor

pyright is Microsoft's type checker, bundled in VS Code as Pylance. It is faster than mypy for interactive use (incremental checks on file save) and has better inference in some cases.

**The key question:** if both mypy and pyright exist, which one runs in CI?

**Answer: mypy in CI, pyright in the editor.** This is a deliberate split.

### Why Both?

| Tool | Strength | Use in |
|------|----------|--------|
| mypy | Mature, stable, widely adopted, many plugins (e.g., `sqlalchemy-stubs`, `django-stubs`) | CI — authoritative gate |
| pyright | Fast incremental, better generics inference, strict mode is stricter | Editor — real-time feedback |

Running both catches more errors than either alone. mypy and pyright do not agree on every edge case. The discrepancies are usually in complex generic types or `Protocol` matching. Teams that require both to pass have the most rigorous type coverage.

**Running pyright in CI additionally (optional but recommended for strict codebases):**

```bash
uv add --dev pyright
uv run pyright src/
```

### pyrightconfig.json

pyright can be configured in `pyrightconfig.json` or `pyproject.toml`:

```json
{
  "include": ["src"],
  "exclude": ["**/__pycache__"],
  "pythonVersion": "3.12",
  "typeCheckingMode": "strict",
  "reportMissingImports": true,
  "reportMissingTypeStubs": false,
  "venvPath": ".",
  "venv": ".venv"
}
```

Or in `pyproject.toml`:

```toml
[tool.pyright]
include = ["src"]
pythonVersion = "3.12"
typeCheckingMode = "strict"
venvPath = "."
venv = ".venv"
```

---

## 4. Integration: All Three in `pyproject.toml`

A complete, production-ready configuration:

```toml
[tool.ruff]
target-version = "py312"
line-length = 88
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP", "N", "SIM", "RUF"]
ignore = ["E501", "B008"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "ARG001", "ARG002"]
"scripts/**" = ["T201", "INP001"]

[tool.ruff.lint.isort]
known-first-party = ["feature_pipeline"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.mypy]
python_version = "3.12"
strict = true
warn_unused_ignores = true

[[tool.mypy.overrides]]
module = ["confluent_kafka.*", "pandera.*"]
ignore_missing_imports = true

[tool.pyright]
include = ["src"]
pythonVersion = "3.12"
typeCheckingMode = "standard"  # strict in editor; standard to avoid duplicate CI noise
venvPath = "."
venv = ".venv"
```

---

## 5. What Each Tool Cannot Do

| Limitation | Tool | Implication |
|------------|------|-------------|
| Cannot catch logic bugs | Ruff, mypy, pyright | Tests are the only defense |
| Cannot catch runtime type errors from external data | mypy, pyright | Use Pydantic for runtime validation (Chapter 01) |
| Cannot enforce semantic naming | Any linter | Code review is the only defense |
| Cannot check SQL query correctness | Any linter | Use typed query builders or integration tests |
| False positives in ML-heavy code | Ruff `B023` | Use `# noqa: B023` with a comment |

---

## Summary

| Tool | Role | Where it runs |
|------|------|--------------|
| Ruff | Linter + formatter | Pre-commit + CI |
| mypy | Authoritative type checker | CI |
| pyright | Real-time type feedback | Editor (VS Code/Neovim) |

| Decision | Recommendation |
|----------|---------------|
| Ruff rule selection | `E`, `W`, `F`, `I`, `B`, `C4`, `UP`, `N`, `SIM`, `RUF` as a baseline |
| Line length | 88 (Black default; well-established) |
| mypy strictness | `strict = true` for both libraries and applications |
| pyright strictness | `standard` in CI; `strict` in editor |
| `# type: ignore` | Always specify the error code; never bare |
| Per-file ignores | `tests/` exempt from `S101` (assert); `scripts/` exempt from `T201` (print) |

> **The most important linting rule is consistency.** A team that enforces `E` + `F` + `I` consistently has a better codebase than a team with a 50-rule config that has 200 inline `# noqa` suppressions.
