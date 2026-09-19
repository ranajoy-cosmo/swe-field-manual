# 02 — Typing and Contracts

## Why Types Matter in Production Python

Python is dynamically typed. This is a feature, not a bug — it enables rapid iteration, flexible data structures, and duck typing patterns that are genuinely powerful. But in a production system maintained by multiple people over years, the absence of type information creates specific, recurring failure modes:

- **A function receives `None` where it expects a string.** It works silently for most inputs and crashes on the edge case that only appears in production.
- **A dict grows organically.** Three months later, nobody knows which keys are required, which are optional, or what the types of the values are.
- **You rename a field in a data class.** The codebase has 40 call sites. You update 38. The other two fail silently because of dynamic attribute access.
- **An API endpoint accepts a JSON body.** Someone passes a string where a number is expected. The computation runs, produces garbage, and the garbage gets persisted.

Type annotations don't eliminate these problems, but they shift them: from runtime failures in production to editor warnings and CI failures during development.

**Types serve three distinct roles:**
1. **Documentation** — they communicate intent to readers (including future you)
2. **Static analysis** — they enable tools (mypy, pyright) to catch errors without running code
3. **Runtime validation** — libraries like Pydantic use them as schemas to validate external data

These three roles require different tools. Conflating them is the most common source of confusion about Python typing.

---

## 1. The Python Type System — Core Concepts

### Gradual Typing

Python's type system is *gradual* — you can annotate some code and leave the rest untyped. Unannotated code is treated as `Any` by static checkers, meaning "I make no claims about this." Gradual typing lets you adopt types incrementally.

### Basic Annotations

```python
# Variables
name: str = "alice"
count: int = 0
ratio: float = 0.95
is_ready: bool = False

# Functions
def greet(name: str) -> str:
    return f"Hello, {name}"

# No return value
def log_event(event: str) -> None:
    print(event)
```

### Built-in Generic Types (Python 3.9+)

From Python 3.9, use the built-in types directly as generics — no need to import from `typing`:

```python
# Python 3.9+
def process(items: list[str]) -> dict[str, int]:
    return {item: len(item) for item in items}

def merge(a: set[int], b: set[int]) -> frozenset[int]:
    return frozenset(a | b)

def nested(data: dict[str, list[float]]) -> None: ...
```

For Python 3.8 compatibility, use `from __future__ import annotations` or import from `typing`.

### `Optional` and `None`

`Optional[X]` is shorthand for `X | None`. In Python 3.10+, use the `|` syntax directly:

```python
# Python 3.10+
def find_user(user_id: int) -> User | None:
    ...

# Equivalent
from typing import Optional
def find_user(user_id: int) -> Optional[User]:
    ...
```

> **Important:** `Optional` does not mean "this argument has a default value." It means "this can be `None`." These are different things.

### `Union` Types

```python
# Python 3.10+
def parse_id(raw: str | int) -> int:
    return int(raw)

# Practical: when a function accepts multiple types
def load(source: str | Path | IO[bytes]) -> bytes: ...
```

### `Literal`

Restricts a value to a specific set of literals. Use instead of `str` or `int` when only certain values are valid:

```python
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

def set_log_level(level: LogLevel) -> None: ...

# The checker will reject:
set_log_level("VERBOSE")  # error: Argument of type '"VERBOSE"' is not assignable
```

### `TypeAlias`

Give complex types a name. This improves readability and makes refactoring easier:

```python
from typing import TypeAlias

FeatureVector: TypeAlias = list[float]
BatchFeatures: TypeAlias = list[FeatureVector]
LabelMap: TypeAlias = dict[str, int]

def encode_batch(batch: BatchFeatures) -> LabelMap: ...
```

### `TypeVar` and Generics

Use `TypeVar` to write functions that preserve type information through transformations:

```python
from typing import TypeVar, Callable

T = TypeVar("T")
U = TypeVar("U")

def transform(items: list[T], fn: Callable[[T], U]) -> list[U]:
    return [fn(item) for item in items]

# The checker knows: transform(["a", "b"], len) returns list[int]
result = transform(["a", "b"], len)  # inferred as list[int]
```

### `ParamSpec` and `Concatenate` (for decorators)

Decorators that preserve the signature of the wrapped function:

```python
from typing import ParamSpec, TypeVar, Callable
from functools import wraps
import time

P = ParamSpec("P")
R = TypeVar("R")

def timed(fn: Callable[P, R]) -> Callable[P, R]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        start = time.perf_counter()
        result = fn(*args, **kwargs)
        print(f"{fn.__name__} took {time.perf_counter() - start:.3f}s")
        return result
    return wrapper

@timed
def train_epoch(model: Model, loader: DataLoader) -> float:
    ...

# The checker correctly knows train_epoch takes (model, loader) -> float
```

---

## 2. Structural Typing with `Protocol`

Python's type system supports both nominal typing (inheritance) and structural typing (duck typing). `Protocol` enables structural typing — a class satisfies a `Protocol` if it has the right methods, regardless of inheritance.

This is the correct way to define interfaces in Python without forcing implementors to inherit from a base class.

```python
from typing import Protocol, runtime_checkable

class ModelBackend(Protocol):
    def predict(self, features: list[float]) -> float: ...
    def is_ready(self) -> bool: ...

# Any class with these methods satisfies the protocol
class SKLearnBackend:
    def predict(self, features: list[float]) -> float:
        return self.model.predict([features])[0]

    def is_ready(self) -> bool:
        return self.model is not None

class TorchBackend:
    def predict(self, features: list[float]) -> float:
        tensor = torch.tensor(features)
        return self.model(tensor).item()

    def is_ready(self) -> bool:
        return True

# Both satisfy ModelBackend without inheriting from it
def serve(backend: ModelBackend, features: list[float]) -> float:
    if not backend.is_ready():
        raise RuntimeError("Backend not initialized")
    return backend.predict(features)
```

### `@runtime_checkable`

Add this decorator to enable `isinstance()` checks against the protocol. Use sparingly — it only checks method existence, not signatures.

```python
@runtime_checkable
class Closeable(Protocol):
    def close(self) -> None: ...

assert isinstance(open("file.txt"), Closeable)  # True at runtime
```

### When to Use Protocol vs ABC

| Use `Protocol` when... | Use `ABC` when... |
|------------------------|-------------------|
| Defining interfaces for duck-typed objects | You want to share implementation via inheritance |
| Third-party classes need to satisfy your interface | You want to enforce `@abstractmethod` at instantiation |
| You don't control the implementors | All implementors are in your codebase |

---

## 3. Structured Data: `dataclass`, `TypedDict`, `NamedTuple`

### `dataclass`

Use for internal data containers with behavior. Python's `dataclass` is the default choice for structured data in application code.

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class TrainingJob:
    job_id: str
    model_name: str
    learning_rate: float
    batch_size: int
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def is_large_batch(self) -> bool:
        return self.batch_size >= 256
```

**`@dataclass(frozen=True)`** — creates an immutable dataclass (hashable, safe as dict key):

```python
@dataclass(frozen=True)
class FeatureKey:
    entity_id: str
    feature_name: str
    version: int
```

**`@dataclass(slots=True)`** (Python 3.10+) — uses `__slots__` for memory efficiency. Useful in ML pipelines that create millions of instances:

```python
@dataclass(slots=True)
class DataPoint:
    feature_id: int
    value: float
    timestamp: int
```

**Limits of `dataclass`:**
- No built-in validation (you must implement `__post_init__`)
- No serialization/deserialization out of the box
- Not ideal for data crossing service boundaries (use Pydantic instead)

### `TypedDict`

Use for dicts that must remain dicts (e.g., JSON-like data, kwargs forwarding, config dicts):

```python
from typing import TypedDict, NotRequired

class ModelConfig(TypedDict):
    model_name: str
    num_layers: int
    dropout: float
    checkpoint_path: NotRequired[str]  # optional key

# The checker validates key access
def load_model(config: ModelConfig) -> Model:
    name = config["model_name"]          # OK
    path = config.get("checkpoint_path") # OK, returns str | None
    wrong = config["typo"]               # error: TypedDict has no key "typo"
```

**Limits of `TypedDict`:**
- No runtime validation — it's purely a static hint
- Cannot add methods
- Inheritance is limited

### `NamedTuple`

Use for lightweight, immutable tuples with named fields. Good for return values when you want to unpack:

```python
from typing import NamedTuple

class EvalResult(NamedTuple):
    accuracy: float
    precision: float
    recall: float
    f1: float

result = EvalResult(accuracy=0.92, precision=0.88, recall=0.91, f1=0.895)
acc, prec, rec, f1 = result  # tuple unpacking still works
```

---

## 4. Static Type Checking

Static type checkers analyze your code *without running it*. They are the primary tool for catching type errors at development time.

### mypy

The original Python type checker. Mature, battle-tested, integrates with most editors and CI pipelines.

**Install:**
```bash
uv add --dev mypy
```

**Configuration (`pyproject.toml`):**
```toml
[tool.mypy]
python_version = "3.10"
strict = true                    # enables all strict checks
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_any_generics = true
check_untyped_defs = true
no_implicit_optional = true

# Per-module overrides for third-party libraries without stubs
[[tool.mypy.overrides]]
module = [
    "sklearn.*",
    "lightgbm.*",
]
ignore_missing_imports = true
```

**Running mypy:**
```bash
mypy src/
mypy src/ --pretty          # formatted output
mypy src/ --html-report=mypy_report/  # HTML report
```

**What `strict` enables:**
- `--disallow-untyped-defs`: all functions must be annotated
- `--disallow-any-explicit`: bans explicit `Any`
- `--warn-return-any`: warns when a function returns `Any`
- `--no-implicit-optional`: `x: str = None` is an error (must write `x: str | None = None`)

**Common mypy patterns:**

```python
# Narrowing with isinstance
def process(value: str | int) -> str:
    if isinstance(value, int):
        return str(value)   # mypy knows value is int here
    return value            # mypy knows value is str here

# Type guards
from typing import TypeGuard

def is_string_list(val: list[object]) -> TypeGuard[list[str]]:
    return all(isinstance(x, str) for x in val)

data: list[object] = ["a", "b", "c"]
if is_string_list(data):
    # mypy knows data is list[str] here
    print(data[0].upper())

# Casting (use sparingly — bypasses checking)
from typing import cast
result = cast(list[str], some_dynamic_function())
```

**Limits of mypy:**
- Strict mode produces many errors on legacy codebases — adopt incrementally
- Some third-party libraries lack type stubs (use `ignore_missing_imports`)
- Does not validate runtime values — a function typed as `-> str` can still return `None` if your logic is wrong
- Some valid Python patterns (e.g., dynamic attribute access) require `# type: ignore` annotations

### pyright / pylance

pyright is Microsoft's type checker (the engine behind Pylance in VS Code). It is faster than mypy, with better inference in some cases and tighter IDE integration.

**Install:**
```bash
uv add --dev pyright
```

**Configuration (`pyrightconfig.json` or `pyproject.toml`):**
```json
{
  "typeCheckingMode": "strict",
  "pythonVersion": "3.10",
  "reportMissingImports": true,
  "reportMissingTypeStubs": false,
  "include": ["src"],
  "exclude": ["tests"]
}
```

**mypy vs pyright — practical differences:**

| | mypy | pyright |
|---|---|---|
| Speed | Slower (with cache, acceptable) | Fast |
| IDE integration | Via mypy LSP | Native in VS Code (Pylance) |
| Inference quality | Conservative | More aggressive |
| Plugin ecosystem | Larger | Growing |
| CI/CD adoption | Dominant | Growing |
| `dataclass` support | Good | Excellent |

**Recommendation:** Use **pyright in your editor** (via Pylance) for instant feedback. Use **mypy in CI** for the authoritative check, since it is the most widely adopted and has the richest plugin ecosystem (e.g., `mypy-boto3`, `sqlalchemy-stubs`).

---

## 5. Runtime Validation with Pydantic

Static type checkers work at analysis time — they cannot validate data that arrives at runtime from external sources (HTTP requests, CSV files, database rows, environment variables, CLI arguments). For that, you need runtime validation.

**Pydantic** is the de facto standard for runtime validation in Python. It uses type annotations as schemas, validates data on instantiation, and provides serialization/deserialization.

> **Use Pydantic when data crosses a system boundary.** For internal data that never leaves your code, `dataclass` is sufficient.

### Basic Model

```python
from pydantic import BaseModel, Field, field_validator
from datetime import datetime

class TrainingConfig(BaseModel):
    model_name: str
    learning_rate: float = Field(gt=0, le=1.0)  # 0 < lr <= 1
    batch_size: int = Field(ge=1, le=4096)
    epochs: int = Field(default=10, ge=1)
    tags: list[str] = Field(default_factory=list)

    @field_validator("model_name")
    @classmethod
    def model_name_must_be_slug(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("model_name must be alphanumeric with dashes/underscores")
        return v.lower()

# Valid
config = TrainingConfig(
    model_name="bert-base",
    learning_rate=0.001,
    batch_size=32,
)

# Invalid — raises ValidationError with structured error messages
try:
    bad_config = TrainingConfig(
        model_name="bert base",   # space not allowed
        learning_rate=5.0,        # > 1.0
        batch_size=32,
    )
except ValidationError as e:
    print(e.json())
```

### Nested Models

```python
class DatasetConfig(BaseModel):
    name: str
    path: Path
    split_ratio: float = Field(default=0.8, ge=0.0, le=1.0)

class ExperimentConfig(BaseModel):
    experiment_id: str
    training: TrainingConfig
    dataset: DatasetConfig
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Parses nested dicts automatically
config = ExperimentConfig.model_validate({
    "experiment_id": "exp-001",
    "training": {
        "model_name": "bert-base",
        "learning_rate": 0.001,
        "batch_size": 32,
    },
    "dataset": {
        "name": "squad",
        "path": "/data/squad",
    }
})
```

### Serialization

```python
# To dict
config.model_dump()
config.model_dump(exclude_none=True)
config.model_dump(include={"model_name", "learning_rate"})

# To JSON string
config.model_dump_json()
config.model_dump_json(indent=2)

# From JSON string
config = TrainingConfig.model_validate_json('{"model_name": "bert", ...}')
```

### Strict Mode

By default, Pydantic coerces types (e.g., `"32"` → `32` for an `int` field). Use strict mode when you want to reject coercion:

```python
class StrictConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    batch_size: int

StrictConfig(batch_size="32")  # ValidationError in strict mode
StrictConfig(batch_size=32)    # OK
```

### Settings Management with `pydantic-settings`

A common use case: loading configuration from environment variables and `.env` files.

```bash
uv add pydantic-settings
```

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",
        case_sensitive=False,
    )

    database_url: str
    redis_host: str = "localhost"
    redis_port: int = 6379
    debug: bool = False
    max_workers: int = Field(default=4, ge=1, le=64)

# Reads APP_DATABASE_URL, APP_REDIS_HOST, etc. from env / .env
settings = AppSettings()
```

**Benefits:**
- All environment variable parsing and validation in one place
- Clear error messages when required variables are missing
- Type coercion: `APP_MAX_WORKERS=8` → `int(8)` automatically

### `model_validator` — Cross-Field Validation

```python
from pydantic import model_validator

class TrainValSplit(BaseModel):
    train_ratio: float = Field(ge=0.0, le=1.0)
    val_ratio: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def ratios_must_sum_to_one(self) -> "TrainValSplit":
        total = self.train_ratio + self.val_ratio
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"train_ratio + val_ratio must equal 1.0, got {total}")
        return self
```

### Pydantic Limits

| Limitation | Notes |
|------------|-------|
| Performance | Validation has overhead. Don't wrap every internal function call in a Pydantic model. |
| Not a substitute for business logic | Pydantic validates *shape* and *constraints*, not *domain correctness*. |
| Complex discriminated unions | Verbose to express; use `Annotated` + `Discriminator` |
| Serialization of non-standard types | Custom `__get_pydantic_core_schema__` required |
| Learning curve | v2 (current) has some breaking changes from v1; check migration guide |

---

## 6. `attrs`

`attrs` is an alternative to `dataclass` with more features: validators, converters, and slots support without the Python 3.10 requirement.

```python
import attrs

@attrs.define
class Pipeline:
    name: str = attrs.field(validator=attrs.validators.min_len(1))
    steps: list[str] = attrs.Factory(list)
    max_retries: int = attrs.field(default=3, validator=attrs.validators.ge(0))

    @steps.validator
    def _validate_steps(self, attribute, value):
        if len(value) > 100:
            raise ValueError("Too many steps")
```

**`attrs` vs `dataclass` vs Pydantic:**

| | `dataclass` | `attrs` | `pydantic` |
|---|---|---|---|
| Stdlib | ✅ | ❌ | ❌ |
| Validation | Manual `__post_init__` | Built-in validators | Full schema validation |
| Serialization | ❌ | `cattrs` companion | ✅ |
| Performance | Fast | Fastest | Slower (for validation) |
| Immutability | `frozen=True` | `frozen=True` | `model_config = frozen` |
| Best for | Simple internal data | High-performance internal data | Boundary data, APIs, config |

---

## 7. A Practical Decision Framework

```
Is this data crossing a system boundary?
(HTTP request, file, DB row, env var, CLI arg)
├── YES → Use Pydantic BaseModel
└── NO → Is it shared across many modules?
    ├── YES → dataclass or attrs
    └── NO → Is it a simple return value?
        ├── YES → NamedTuple
        └── NO → dataclass
```

For interfaces that multiple implementations will satisfy:
```
Do you control all implementations?
├── YES → ABC if you want shared behavior, Protocol if interface-only
└── NO → Protocol (structural typing, no inheritance required)
```

---

## Summary

| Tool | Role | When to Use |
|------|------|-------------|
| Type annotations | Documentation + static analysis input | Always, on all public APIs |
| `Protocol` | Interface definition | When defining pluggable backends |
| `dataclass` | Structured internal data | Internal domain objects |
| `TypedDict` | Dict-shaped data with type info | Dict-based configs, kwargs |
| `NamedTuple` | Immutable tuples with names | Return values, lightweight records |
| mypy | Static type checker (CI) | Every Python project |
| pyright | Static type checker (editor) | VS Code / Pylance |
| Pydantic | Runtime validation + serialization | All external data |
| attrs | High-performance validated dataclass | Performance-sensitive internal data |
| pydantic-settings | Environment/config loading | All service configuration |

> **The key insight:** static checkers (mypy, pyright) and runtime validators (Pydantic) are *complementary*, not alternatives. Use both: static checking catches errors in your logic; runtime validation catches errors in your inputs.
