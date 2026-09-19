# 01 — Code Quality

## Why Code Quality Is a Production Concern

Code quality is often framed as an aesthetic preference. In production systems, it is an operational one. Low-quality code is not just unpleasant to read — it is actively expensive:

- **Debugging cost scales with coupling.** A function that does five things requires you to hold five contexts in your head before you can safely change one.
- **Hidden state causes incidents.** Mutable globals, side effects inside constructors, and in-place mutation are common causes of "it worked in dev" failures.
- **Inconsistent style creates merge conflicts and review noise**, displacing attention from logic to formatting.
- **Undocumented assumptions become production bugs.** The comment "this is always sorted" that isn't enforced anywhere becomes a silent correctness failure.

The goal of code quality tooling is to make the *right thing easy* and the *wrong thing loud*, without requiring human review bandwidth to catch issues a machine can catch.

---

## 1. Naming

Good naming is the most impactful single change you can make to code readability. It is also the one thing no linter can fully automate.

### Principles

**Name what it is, not what it does mechanically.**

```python
# Bad: names describe implementation
def do_calc(x, y):
    ...

def proc_usr_data(data):
    ...

# Good: names describe intent
def compute_batch_loss(predictions, targets):
    ...

def normalize_user_profile(raw_profile: dict) -> UserProfile:
    ...
```

**Booleans should read as assertions.**

```python
# Bad
active = True
check = run_health_check()

# Good
is_active = True
is_healthy = run_health_check()
```

**Collections should be plural; single items singular.**

```python
users = [...]           # list of users
user = users[0]         # single user
user_ids = {u.id for u in users}
```

**Avoid abbreviations unless they are universal in the domain.**

```python
# Bad (in ML context)
bs = 32     # batch size? byte size?
lr = 0.001  # fine in ML context, universal abbreviation

# Good
batch_size = 32
learning_rate = 0.001
```

**Functions should be verbs; classes should be nouns.**

```python
# Functions
def load_checkpoint(path: Path) -> ModelState: ...
def validate_schema(data: dict) -> None: ...
def emit_metric(name: str, value: float) -> None: ...

# Classes
class ModelCheckpoint: ...
class FeaturePipeline: ...
class BatchScheduler: ...
```

### Length Heuristics

| Scope | Name Length Guidance |
|-------|---------------------|
| Loop variable (1–2 lines) | `i`, `k`, `x` acceptable |
| Local variable (function scope) | 1–2 words |
| Module-level / class attribute | 2–4 words, precise |
| Public API (used by other teams) | Explicit and self-documenting |

---

## 2. Function Design

### The Single Responsibility Principle (SRP)

A function should do one thing. The test: can you describe what it does without using "and" or "or"?

```python
# Bad: does three things
def process_user(user_id: int) -> None:
    user = db.fetch(user_id)          # I/O
    user.score = compute_score(user)  # computation
    db.save(user)                     # I/O again
    send_email(user)                  # side effect

# Good: each function has one job
def load_user(user_id: int) -> User:
    return db.fetch(user_id)

def update_user_score(user: User) -> User:
    return dataclasses.replace(user, score=compute_score(user))

def persist_user(user: User) -> None:
    db.save(user)

def notify_user(user: User) -> None:
    send_email(user)
```

The orchestration still happens, but in a caller that *reads like a workflow*:

```python
def process_user(user_id: int) -> None:
    user = load_user(user_id)
    updated = update_user_score(user)
    persist_user(updated)
    notify_user(updated)
```

### Function Length

There is no universal rule, but a useful heuristic: **if a function doesn't fit on one screen (roughly 40 lines), question it.** Long functions usually contain implicit sub-functions waiting to be named.

### Pure vs Impure Functions

Prefer pure functions (no side effects, output depends only on input) wherever possible. They are trivially testable and composable.

```python
# Pure — easy to test, no hidden dependencies
def normalize(value: float, min_val: float, max_val: float) -> float:
    return (value - min_val) / (max_val - min_val)

# Impure — harder to test, must control external state
def log_and_normalize(value: float) -> float:
    logger.info("Normalizing %f", value)
    return normalize(value, CONFIG.min, CONFIG.max)
```

Push impure code to the edges of your system (entry points, I/O handlers). Keep the core logic pure.

### Flag Arguments Are a Code Smell

A boolean argument that changes the *behavior* of a function usually means two functions are hiding inside one.

```python
# Bad
def load_model(path: Path, use_gpu: bool) -> Model:
    if use_gpu:
        return load_to_gpu(path)
    return load_to_cpu(path)

# Good
def load_model_cpu(path: Path) -> Model: ...
def load_model_gpu(path: Path) -> Model: ...
```

---

## 3. SOLID Principles in Python

SOLID is not Java-specific. Adapted for Python's duck-typing and dynamic nature:

### S — Single Responsibility

*(Covered above in function design. Applies equally to classes.)*

A class that manages a database connection, formats data, and sends emails is three classes in a trench coat.

### O — Open/Closed

Open for extension, closed for modification. In Python: use `Protocol`, ABC, or hooks/callbacks instead of `if isinstance`.

```python
# Bad: adding a new format requires editing this function
def export_data(data: list, format: str) -> bytes:
    if format == "csv":
        return to_csv(data)
    elif format == "json":
        return to_json(data)
    elif format == "parquet":  # must edit here every time
        return to_parquet(data)

# Good: new formats are added without touching existing code
from typing import Protocol

class DataExporter(Protocol):
    def export(self, data: list) -> bytes: ...

class CsvExporter:
    def export(self, data: list) -> bytes:
        return to_csv(data)

class ParquetExporter:
    def export(self, data: list) -> bytes:
        return to_parquet(data)

def export_data(data: list, exporter: DataExporter) -> bytes:
    return exporter.export(data)
```

### L — Liskov Substitution

Subtypes must be substitutable for their base types without breaking behavior. In Python, this means: if you inherit from something, the subclass must honor the base class's contract — not just its interface.

```python
class DataReader:
    def read(self, path: Path) -> list[dict]: ...

# Bad: violates LSP — raises where base class doesn't
class StrictDataReader(DataReader):
    def read(self, path: Path) -> list[dict]:
        if not path.exists():
            raise FileNotFoundError  # new behavior not in contract
        return super().read(path)

# Good: document and honor the contract
class DataReader:
    def read(self, path: Path) -> list[dict]:
        """
        Raises:
            FileNotFoundError: if path does not exist.
        """
        ...
```

### I — Interface Segregation

Don't force clients to depend on interfaces they don't use. In Python: keep `Protocol`s narrow.

```python
# Bad: one fat protocol
class StorageBackend(Protocol):
    def read(self, key: str) -> bytes: ...
    def write(self, key: str, value: bytes) -> None: ...
    def delete(self, key: str) -> None: ...
    def list_keys(self, prefix: str) -> list[str]: ...
    def get_metadata(self, key: str) -> dict: ...

# Good: narrow protocols, compose as needed
class Readable(Protocol):
    def read(self, key: str) -> bytes: ...

class Writable(Protocol):
    def write(self, key: str, value: bytes) -> None: ...

class ReadWriteStorage(Readable, Writable, Protocol): ...
```

### D — Dependency Inversion

Depend on abstractions, not concretions. In Python: inject dependencies; don't instantiate collaborators inside a class.

```python
# Bad: hard dependency on concrete implementation
class FeaturePipeline:
    def __init__(self):
        self.store = RedisFeatureStore()  # can't swap, can't test

# Good: inject the dependency
class FeaturePipeline:
    def __init__(self, store: FeatureStore) -> None:
        self.store = store
```

---

## 4. DRY, YAGNI, KISS

**DRY (Don't Repeat Yourself):** Every piece of knowledge should have a single authoritative representation.

The enemy of DRY is copy-paste. The sign you've violated DRY: when a business rule changes, you must update it in N places.

> DRY is about *knowledge*, not *code*. Two functions that happen to look similar but represent different domain concepts are *not* DRY violations.

**YAGNI (You Aren't Gonna Need It):** Don't build abstractions for requirements that don't exist yet.

```python
# Bad: over-engineered for a simple script
class AbstractDataLoaderFactory(ABC):
    @abstractmethod
    def create_loader(self, config: LoaderConfig) -> DataLoader: ...

# Good: solve what you have today
def load_csv(path: Path) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))
```

**KISS (Keep It Simple, Stupid):** When two solutions both work, prefer the simpler one. The "clever" solution is a liability.

---

## 5. Module and Package Structure

A well-structured Python package makes imports predictable and avoids circular dependencies.

### The `src` Layout (Recommended)

```
project/
├── src/
│   └── mypackage/
│       ├── __init__.py
│       ├── core/
│       ├── api/
│       └── utils/
├── tests/
├── pyproject.toml
└── README.md
```

The `src` layout prevents accidentally importing the development version of your package instead of the installed one. It also forces proper installation before running, which catches packaging errors early.

### `__init__.py` as a Public API Surface

Use `__init__.py` to define what is public. Everything not re-exported from `__init__.py` is an implementation detail.

```python
# src/mypackage/__init__.py
from mypackage.core.pipeline import FeaturePipeline
from mypackage.core.model import ModelConfig

__all__ = ["FeaturePipeline", "ModelConfig"]
```

### Avoid Wildcard Imports

```python
# Bad
from mypackage.utils import *

# Good
from mypackage.utils import normalize, validate_schema
```

---

## 6. Tooling

### Ruff

Ruff is the current standard for Python linting and formatting. It replaces flake8, isort, pyupgrade, and to a large extent pylint, with an order-of-magnitude speed improvement.

**Install:**
```bash
uv add --dev ruff
```

**Configuration (`pyproject.toml`):**
```toml
[tool.ruff]
target-version = "py310"
line-length = 88

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "B",    # flake8-bugbear (common bugs)
    "C4",   # flake8-comprehensions
    "UP",   # pyupgrade (modernize syntax)
    "N",    # pep8-naming
    "SIM",  # flake8-simplify
    "RUF",  # ruff-specific rules
]
ignore = [
    "E501",  # line too long — handled by formatter
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]  # allow assert in tests

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

**Usage:**
```bash
ruff check .          # lint
ruff check --fix .    # lint + auto-fix
ruff format .         # format
```

**What Ruff catches:**
- Unused imports and variables (`F`)
- Import ordering (`I`)
- Mutable default arguments (`B006`)
- Unnecessary `list()` calls around comprehensions (`C4`)
- Deprecated syntax that can be modernized (`UP`)
- Common naming violations (`N`)

**Limits of Ruff:**
- Does not do type checking (that's mypy/pyright territory)
- Cannot catch logical bugs — only syntactic/style issues
- Some bugbear rules have false positives in ML contexts (e.g., `B023` loop variable capture)

### Pylint

Pylint has deeper analysis than Ruff — it performs some inter-module analysis and catches more design-level issues. It is significantly slower and noisier.

**When to prefer pylint over ruff:** When you need `design` rules like `too-many-arguments`, `too-many-instance-attributes`, or `too-few-public-methods`. These act as automated complexity guards.

```toml
[tool.pylint.design]
max-args = 7
max-attributes = 10
max-bool-expr = 5
max-branches = 12
max-locals = 15
```

**Practical recommendation:** Use Ruff as your primary linter. Add Pylint selectively for design-level enforcement on core library code.

---

## 7. Docstrings

Docstrings are the contract between the author and the caller. They are not optional on public APIs.

Use Google style (cleaner for ML/data codebases than NumPy or Sphinx style):

```python
def compute_precision(
    y_true: list[int],
    y_pred: list[int],
    threshold: float = 0.5,
) -> float:
    """Compute binary precision at a given threshold.

    Args:
        y_true: Ground truth binary labels (0 or 1).
        y_pred: Predicted probabilities in [0, 1].
        threshold: Classification threshold. Defaults to 0.5.

    Returns:
        Precision score in [0, 1].

    Raises:
        ValueError: If y_true and y_pred have different lengths.
        ValueError: If threshold is not in (0, 1).

    Example:
        >>> compute_precision([1, 0, 1], [0.8, 0.3, 0.9])
        1.0
    """
```

**What to document:**
- **Args**: types (even if typed), semantics, valid ranges, units
- **Returns**: what is returned, including edge cases (empty list? None?)
- **Raises**: only exceptions the *caller* should handle; not internal implementation errors
- **Examples**: especially for non-obvious input/output behavior

**What not to document:**
- Re-stating the type annotations that are already in the signature
- Internal implementation steps ("first we sort, then we filter") — that belongs in inline comments if anywhere

---

## Summary

| Principle | Key Test |
|-----------|----------|
| Naming | Can you describe what it does without reading the body? |
| Single Responsibility | Can you describe it without using "and"? |
| Open/Closed | Can you add behavior without editing existing code? |
| Dependency Inversion | Can you swap the implementation without touching the class? |
| DRY | If a rule changes, how many places do you update? |
| YAGNI | Is this abstraction solving a real, current problem? |

> **The most dangerous code is code that *looks* structured but has hidden coupling.** SOLID and good naming make the coupling visible, so it can be managed.
