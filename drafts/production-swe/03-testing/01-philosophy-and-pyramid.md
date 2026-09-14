# 01 — Philosophy and the Test Pyramid

## What Tests Are For

The most important thing to understand about testing: **tests are a tool for managing change, not a tool for proving correctness.**

A test suite that never fails is not a sign of quality software — it's a sign of a test suite that isn't exercising anything important. A good test suite tells you immediately when a change broke something that was previously working. It gives you the confidence to refactor, upgrade dependencies, and ship on Fridays.

The failure modes that testing *prevents*:
- A refactor silently changes behavior in a code path that was never manually verified
- A dependency upgrade breaks a subtle assumption in your code
- A configuration change makes a previously impossible input path valid
- A fix for one bug reintroduces a different old bug

The failure modes that testing *does not prevent*:
- Logic errors that were always wrong (you can't test for bugs you don't know about)
- Wrong requirements (tests check that you built the thing right, not that you built the right thing)
- Race conditions, timing issues, and emergent system behaviors at scale

---

## The Test Pyramid

The pyramid communicates a ratio, not a rigid rule:

```
         ▲
        /E\E\        End-to-End: Few, slow, brittle
       /-----\       Test the whole deployed system
      / Integ \
     /---------\     Integration: Moderate, slower
    / rat ion   \    Test components wired together
   /─────────────\
  /   Unit Tests  \  Unit: Many, fast, isolated
 /─────────────────\ Test one function/class in isolation
```

**The practical implication:** if you have 10 E2E tests and 5 unit tests, you have an inverted pyramid — it will be slow, flaky, and hard to debug when it fails.

### Unit Tests (70–80% of your suite)
- Test a single function or class
- All external I/O (DB, network, filesystem, time, randomness) is replaced with fakes
- Must run in milliseconds
- Failures pinpoint exactly which unit broke

### Integration Tests (15–25%)
- Test multiple real components wired together
- May involve a real database (in a Docker container), real filesystem, real subprocess
- Run in seconds to a few minutes
- Failures indicate a wiring or contract problem between components

### End-to-End Tests (5–10%)
- Test the whole system from the outside
- Make real HTTP requests against a running service
- Slow, infrastructure-dependent, occasionally flaky
- Failures indicate the whole deployment is broken

### Contract Tests (often overlooked, sits between integration and E2E)
- Test the interface contract between two services
- Each side independently verifies the contract is met
- Fast (no live services), catches API mismatches before deployment

---

## The Coverage Trap

Code coverage is a useful proxy metric, not a goal.

**What high coverage means:** the covered lines were *executed* during tests. It does not mean they were tested correctly — a test that calls a function but asserts nothing gives 100% line coverage and zero confidence.

**What low coverage means:** some code is definitely not being tested. It's a good signal, but the cause matters:
- Untested error paths (genuinely bad)
- Untested admin utilities (probably fine)
- Untested generated code (ignore it)

**Useful targets:**
- **Line coverage ≥ 80%** for production code — a floor, not a ceiling
- **Branch coverage ≥ 70%** — more meaningful than line coverage; covers both sides of `if/else`
- **0% for generated code** — exclude migrations, auto-generated clients, `__init__.py` re-exports

**Configure coverage to exclude noise:**

```toml
# pyproject.toml
[tool.coverage.run]
branch = true
source = ["src"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "@(abc\\.)?abstractmethod",
]
omit = [
    "*/migrations/*",
    "*/conftest.py",
    "*/__init__.py",
]
```

---

## What to Test

**Test behavior, not implementation.**

The test should describe what the code is supposed to do, not how it does it. A test tied to implementation details (internal variable names, call order of private methods) breaks every time you refactor — even when the behavior is unchanged.

```python
# Bad: tests implementation (internal call sequence)
def test_pipeline_calls_normalize_before_transform():
    with patch("pipeline._normalize") as mock_normalize:
        with patch("pipeline._transform") as mock_transform:
            pipeline.run(data)
            mock_normalize.assert_called_before(mock_transform)

# Good: tests behavior (output given input)
def test_pipeline_produces_valid_features():
    raw = [{"value": 100, "timestamp": "2024-01-01"}]
    features = pipeline.run(raw)
    assert all(0.0 <= f["normalized_value"] <= 1.0 for f in features)
```

**What to test:**
- Happy path: the function does what it says given valid input
- Edge cases: empty input, zero values, boundary values, maximum values
- Error paths: what happens with invalid input — does it raise the right exception with the right message?
- Contracts: if you document that a function returns sorted output, test it
- Regression cases: every bug fixed should get a test that would have caught it

**What not to test:**
- Private methods directly (test them through the public API)
- Third-party library internals (assume requests, pydantic, etc. work)
- One-line getter/setters with no logic
- `__repr__` and `__str__` unless they're part of the public contract

---

## The Testing Vocabulary

Before the code examples: a shared vocabulary used throughout this chapter.

| Term | Meaning |
|------|---------|
| **SUT** | System Under Test — the code being tested |
| **Fixture** | Setup code that provides a known state to a test |
| **Stub** | A fake implementation that returns canned data |
| **Mock** | A fake that records calls and can assert on them |
| **Spy** | A real implementation that also records calls |
| **Fake** | A lightweight working implementation (e.g., in-memory DB) |
| **Parametrize** | Running the same test with multiple input/output pairs |
| **Assertion** | The statement that checks what actually happened |
| **Coverage** | The fraction of code executed by the test suite |
| **Flaky test** | A test that passes and fails non-deterministically |

---

## Test Naming Conventions

Tests are documentation. The name should describe what happens, not repeat the function name.

```python
# Bad: tells you nothing beyond the function name
def test_normalize():
    ...

def test_normalize_fail():
    ...

# Good: describes the behavior and the condition
def test_normalize_returns_zero_to_one_range_for_positive_values():
    ...

def test_normalize_raises_value_error_when_min_equals_max():
    ...

def test_normalize_returns_empty_list_for_empty_input():
    ...
```

A readable pattern: `test_{function/class}_{condition}_{expected_outcome}`

For classes: group tests in a class matching the SUT class name:

```python
class TestFeaturePipeline:
    def test_run_returns_features_for_valid_entity_ids(self): ...
    def test_run_raises_when_entity_ids_is_empty(self): ...
    def test_run_skips_unavailable_features_with_warning(self): ...
```

---

## Directory Structure

```
project/
├── src/
│   └── feature_pipeline/
│       ├── __init__.py
│       ├── pipeline.py
│       ├── storage.py
│       └── api/
│           └── routes.py
└── tests/
    ├── conftest.py              # session-scoped fixtures, shared config
    ├── unit/
    │   ├── conftest.py          # unit-test-specific fixtures
    │   ├── test_pipeline.py
    │   └── test_storage.py
    ├── integration/
    │   ├── conftest.py          # integration fixtures (Docker, real DBs)
    │   ├── test_pipeline_integration.py
    │   └── test_api_routes.py
    ├── contract/
    │   └── test_feature_api_contract.py
    └── e2e/
        └── test_serving_flow.py
```

The marker system (covered in chapter 02) lets you run only the unit tests:
```bash
pytest tests/unit/          # by directory
pytest -m unit              # by marker
pytest -m "not integration" # exclude slow tests locally
```
