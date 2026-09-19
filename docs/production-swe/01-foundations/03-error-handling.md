# 03 — Error Handling

## Why Error Handling Is a Design Decision

Error handling is not an afterthought. In production systems, *the unhappy path is the normal path* — networks fail, disks fill, upstream services return garbage, users send invalid input. The question is not whether errors will occur, but how your system behaves when they do.

Poor error handling has predictable failure modes:

- **Silent failures**: an operation fails, the error is swallowed, the system continues with corrupted state.
- **Overly broad catches**: `except Exception: pass` turns a detectable bug into a mystery.
- **Unhelpful messages**: `"Error occurred"` in production logs is useless. Who called what with what arguments?
- **Leaking implementation details**: stack traces and internal module names in API responses are both a security risk and a poor user experience.
- **Inconsistent error surfaces**: some functions raise, some return `None`, some return `False`. Callers must inspect documentation (if it exists) to know what to expect.

The goal of error handling design is to make errors **explicit**, **informative**, and **recoverable at the right level**.

---

## 1. Exceptions: The Core Mechanism

Python's primary error handling mechanism is exceptions. Before designing a strategy, understand the properties of the exception system.

### Exception Hierarchy

```
BaseException
├── SystemExit
├── KeyboardInterrupt
├── GeneratorExit
└── Exception          ← catch this, never BaseException
    ├── RuntimeError
    ├── ValueError
    ├── TypeError
    ├── LookupError
    │   ├── IndexError
    │   └── KeyError
    ├── OSError
    │   ├── FileNotFoundError
    │   └── PermissionError
    ├── AttributeError
    └── ...
```

**`BaseException`** — never catch this. It includes `KeyboardInterrupt` and `SystemExit`, which should terminate your program.

**`Exception`** — the base for all "expected" exceptions. Catching `Exception` is still broad; prefer specific types.

### Checked vs Unchecked (Python has no distinction)

Python does not distinguish checked and unchecked exceptions. All exceptions are unchecked — they propagate until caught or they crash the process. This puts the discipline entirely on the developer.

The implication: **use docstrings and type stubs to document what exceptions a function raises.** There is no language enforcement, only convention.

---

## 2. Designing a Custom Exception Hierarchy

Don't just raise `ValueError` everywhere. Design an exception hierarchy that reflects your domain. This gives callers the ability to catch *exactly the errors they can handle*.

### The Pattern

```python
# Base exception for your library/service
class PipelineError(Exception):
    """Base exception for all pipeline errors."""

# Category exceptions — callers can catch these if they handle whole categories
class DataError(PipelineError):
    """Errors related to input data."""

class InfrastructureError(PipelineError):
    """Errors related to external systems (DB, network, storage)."""

class ConfigurationError(PipelineError):
    """Errors in configuration at startup. Usually non-recoverable."""

# Specific exceptions — carry context
class SchemaValidationError(DataError):
    def __init__(self, field: str, expected: str, got: str) -> None:
        self.field = field
        self.expected = expected
        self.got = got
        super().__init__(
            f"Schema validation failed for field '{field}': "
            f"expected {expected}, got {got}"
        )

class FeatureStorageError(InfrastructureError):
    def __init__(self, operation: str, key: str, cause: Exception) -> None:
        self.operation = operation
        self.key = key
        self.cause = cause
        super().__init__(
            f"Feature store {operation} failed for key '{key}': {cause}"
        )
```

**Usage:**

```python
# Caller handles only the errors it can act on
try:
    features = feature_store.get(entity_id)
except FeatureStorageError as e:
    logger.warning("Feature store unavailable, using fallback", key=e.key)
    features = fallback_features(entity_id)
except DataError as e:
    logger.error("Data error, cannot proceed", error=str(e))
    raise  # re-raise — can't recover
```

### Carrying Context in Exceptions

The most important property of an exception is that it carries enough context to diagnose the failure *without a debugger*.

```python
# Bad: no context
raise ValueError("Invalid config")

# Good: specific and actionable
raise ConfigurationError(
    f"learning_rate must be in (0, 1], got {learning_rate!r}. "
    "Check your experiment config or the APP_LEARNING_RATE env var."
)
```

Include:
- What was the invalid value (with `!r` repr)
- What was expected (range, type, valid options)
- Where to look to fix it (config key, env var name, file path)

---

## 3. Exception Chaining

When catching one exception and raising another, use `raise ... from ...` to preserve the causal chain. This is critical for debugging.

```python
def load_config(path: Path) -> AppConfig:
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError as e:
        raise ConfigurationError(
            f"Config file not found at {path}. "
            "Set the CONFIG_PATH environment variable."
        ) from e  # preserves original traceback
    except json.JSONDecodeError as e:
        raise ConfigurationError(
            f"Config file at {path} is not valid JSON: {e.msg} at line {e.lineno}"
        ) from e
```

Without `from e`, the original exception is lost and the traceback shows only your wrapper exception. With `from e`, both appear:

```
ConfigurationError: Config file at config.json is not valid JSON: ...
  [Caused by] json.JSONDecodeError: Expecting value: line 5 column 3 (char 42)
```

Use `raise ... from None` only when the original exception is genuinely irrelevant and showing it would confuse the caller.

---

## 4. Catch Specifically, Catch Narrowly

### The Width Problem

Broad catches are the single most common error handling mistake:

```python
# Bad: hides all errors, including bugs
try:
    result = process(data)
except Exception:
    logger.error("Something failed")
    return None

# Bad: catches too broadly, treating a programming error as a data error
try:
    value = record["field_name"]
except Exception as e:
    handle_missing_field(e)
```

The second example would also catch `TypeError` if `record` is `None`, masking a null pointer bug as a missing field.

```python
# Good: catch exactly what you can handle
try:
    value = record["field_name"]
except KeyError:
    handle_missing_field()
```

### The Depth Problem

Catch exceptions at the level where you have enough context to handle or enrich them — not at every level.

```python
# Bad: catch-and-ignore at every level
def step_a() -> None:
    try:
        ...
    except Exception:
        pass  # silent failure

def step_b() -> None:
    try:
        step_a()
    except Exception:
        pass  # silent failure

# Good: let exceptions propagate until they reach a handler with context
def run_pipeline() -> None:
    try:
        step_a()
        step_b()
    except DataError as e:
        logger.error("Pipeline failed on data error", error=str(e))
        raise PipelineError("Pipeline aborted") from e
    except InfrastructureError as e:
        logger.critical("Infrastructure failure", error=str(e))
        alert_oncall(e)
        raise
```

### `finally` for Cleanup

`finally` runs regardless of whether an exception occurred. Use it for cleanup that *must* happen:

```python
def write_checkpoint(model, path: Path) -> None:
    tmp_path = path.with_suffix(".tmp")
    try:
        save_model(model, tmp_path)
        tmp_path.rename(path)  # atomic rename
    except Exception:
        raise
    finally:
        if tmp_path.exists():  # clean up partial write
            tmp_path.unlink()
```

---

## 5. Context Managers for Resource Safety

Context managers (`with` statement) guarantee cleanup even when exceptions occur. They are the correct way to manage any resource with a lifecycle: file handles, DB connections, locks, temporary directories.

### Using `contextlib`

```python
from contextlib import contextmanager
from pathlib import Path
import tempfile
import shutil

@contextmanager
def temporary_workspace():
    """Provides a temporary directory that is cleaned up on exit."""
    workspace = Path(tempfile.mkdtemp())
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

# Usage
with temporary_workspace() as ws:
    process_data(input_path, output_path=ws / "output.csv")
    upload(ws / "output.csv")
# workspace cleaned up here, even if an exception occurred
```

### `contextlib.suppress` — Intentional Ignoring

When you genuinely want to ignore a specific exception, make it explicit:

```python
from contextlib import suppress

# Bad: silently swallows errors
try:
    metrics_client.send(event)
except Exception:
    pass

# Good: explicitly suppresses only the specific exception you expect
with suppress(ConnectionError, TimeoutError):
    metrics_client.send(event)
    # if connection fails, we continue — metrics are not critical
```

### `ExitStack` — Dynamic Context Managers

When you don't know at write-time how many resources to manage:

```python
from contextlib import ExitStack

def process_files(paths: list[Path]) -> None:
    with ExitStack() as stack:
        file_handles = [
            stack.enter_context(open(p)) for p in paths
        ]
        # all files closed on exit, even if an error occurs midway
        merge_and_process(file_handles)
```

---

## 6. The Fail-Fast Principle

Fail-fast means: **detect invalid state as early as possible and raise immediately, rather than propagating invalid state through the system.**

A function that receives bad input and continues anyway will produce wrong output somewhere downstream — possibly far from the site of the original bad input, making diagnosis extremely difficult.

### Assertions vs. Exceptions

Python's `assert` is not for input validation. It is disabled with `python -O` (optimize flag). Use it only for invariants that *should be impossible to violate* — internal logic checks during development.

```python
# Wrong: assert for validation
def process(items: list[str]) -> None:
    assert len(items) > 0, "items must not be empty"

# Correct: explicit exception for validated input
def process(items: list[str]) -> None:
    if not items:
        raise ValueError("items must not be empty")

# Correct: assert for internal invariants
def binary_search(arr: list[int], target: int) -> int:
    low, high = 0, len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        assert 0 <= mid < len(arr)  # this being false is a bug in binary_search itself
        ...
```

### Guard Clauses

Validate inputs at the top of a function before doing any work. This is the "fail-fast" pattern in practice:

```python
# Bad: validation mixed with logic
def train(model, data, config):
    if model:
        if data and len(data) > 0:
            if config.get("learning_rate"):
                # ... actual logic buried three levels deep
```

```python
# Good: guard clauses at the top
def train(model: Model, data: list[DataPoint], config: TrainingConfig) -> TrainResult:
    if model is None:
        raise ValueError("model must not be None")
    if not data:
        raise ValueError("data must not be empty")
    if config.learning_rate <= 0:
        raise ValueError(f"learning_rate must be positive, got {config.learning_rate}")

    # actual logic — guaranteed valid state from here
    ...
```

---

## 7. Result Types — An Alternative Pattern

Some codebases model errors as values rather than exceptions. The `Result` type (from functional programming) makes the possibility of failure explicit in the function's return type.

### The Case For It

- Callers *must* handle the error case — the type checker enforces it
- No hidden control flow — exceptions can jump up the stack invisibly
- Composable — chain operations without try/except at every step

### The Case Against It

- Not idiomatic Python — no native `Result` type
- Verbose without `do-notation` or monadic sugar
- Friction when interfacing with libraries that use exceptions (which is most Python code)

### A Simple Implementation

You don't need a library. A minimal `Result` type:

```python
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E", bound=Exception)

@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T
    is_ok: bool = True

@dataclass(frozen=True)
class Err(Generic[E]):
    error: E
    is_ok: bool = False

Result = Ok[T] | Err[E]

# Usage
def parse_age(raw: str) -> Result[int, ValueError]:
    try:
        age = int(raw)
    except ValueError as e:
        return Err(e)
    if age < 0 or age > 150:
        return Err(ValueError(f"Age {age} is out of plausible range"))
    return Ok(age)

result = parse_age("25")
match result:
    case Ok(value=age):
        print(f"Age: {age}")
    case Err(error=e):
        print(f"Invalid: {e}")
```

### The `returns` Library

The `returns` library provides a full Result/Option monad implementation:

```bash
uv add returns
```

```python
from returns.result import Result, Success, Failure, safe

@safe  # wraps exceptions into Failure
def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text())

result: Result[dict, Exception] = load_config("config.json")

# Pipeline without nested try/except
from returns.pipeline import flow
from returns.pointfree import bind

processed = (
    load_config("config.json")
    .bind(lambda cfg: Success(validate_config(cfg)))
    .map(lambda cfg: cfg["learning_rate"])
)
```

**Practical recommendation:** Use exceptions as your primary mechanism. Reserve `Result` types for:
- Functions at a system boundary where the caller *must* acknowledge the failure
- Pipeline steps where you want to collect multiple errors rather than fail on the first

---

## 8. Logging Errors (Partial Preview)

Error handling and logging are tightly coupled. A few immediate rules (full treatment in chapter 04):

```python
# Log at the point where you have context, not where you catch
def fetch_features(entity_id: str) -> Features:
    try:
        return store.get(entity_id)
    except FeatureStorageError as e:
        # log here — we know entity_id and operation context
        logger.error(
            "Feature fetch failed",
            entity_id=entity_id,
            operation="fetch_features",
            error=str(e),
        )
        raise

# Don't log and then silently swallow
def bad_fetch(entity_id: str) -> Features | None:
    try:
        return store.get(entity_id)
    except FeatureStorageError as e:
        logger.error("Error: %s", e)
        return None  # caller doesn't know something went wrong
```

**Log and re-raise** when you want to add context but let the error propagate. **Log and handle** only when you are the correct level to recover. Never log and swallow.

---

## 9. Handling Errors at Service Boundaries

When your code is a service (HTTP API, async worker, gRPC server), you must translate internal exceptions into appropriate external responses.

### HTTP API Pattern (FastAPI)

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

@app.exception_handler(SchemaValidationError)
async def handle_validation_error(
    request: Request, exc: SchemaValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "field": exc.field,
            "message": str(exc),
        }
    )

@app.exception_handler(InfrastructureError)
async def handle_infra_error(
    request: Request, exc: InfrastructureError
) -> JSONResponse:
    logger.critical("Infrastructure error in request", error=str(exc))
    return JSONResponse(
        status_code=503,
        content={
            "error": "service_unavailable",
            "message": "Temporary infrastructure issue. Retry with backoff.",
            "retry_after": 30,
        }
    )

@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.critical("Unexpected error", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "An unexpected error occurred."}
    )
```

**Rules for boundary error translation:**
- **Never leak internal exceptions** (stack traces, internal module names) to external callers
- Map domain exceptions to HTTP status codes deliberately (422 for validation, 503 for infra, 500 for bugs)
- Always log the full exception with `exc_info=True` internally, even when returning a sanitized response externally
- Include `retry_after` for transient errors so clients can backoff correctly

---

## Summary

| Principle | Implementation |
|-----------|---------------|
| Fail fast | Guard clauses at function top; validate at entry points |
| Catch specifically | Name the exact exception type you handle |
| Catch at the right level | Only catch where you have context to act or enrich |
| Carry context | Exception messages should contain values, expected ranges, fix hints |
| Chain causes | Always use `raise ... from original_exception` |
| Resource safety | Use context managers; never rely on manual cleanup |
| Explicit ignoring | `contextlib.suppress` not bare `except: pass` |
| Boundary translation | Convert internal exceptions to external responses; never leak internals |

> **The measure of error handling quality:** when an error occurs in production at 3am, can an on-call engineer who didn't write this code diagnose the cause, the impact, and the recovery path from the logs alone?
