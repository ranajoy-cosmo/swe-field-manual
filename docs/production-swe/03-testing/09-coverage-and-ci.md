# 08 — Coverage, CI, and Test Performance

## The Goal: Tests That Run

A test suite that takes 45 minutes to run locally doesn't get run locally. Tests that only run in CI catch bugs 30 minutes after the code is written, not immediately. The goal is a test suite that developers *want* to run — fast, reliable, and informative.

---

## 1. Coverage Configuration

### `pytest-cov` Setup

```bash
uv add --dev pytest-cov
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = [
    "--cov=src",
    "--cov-report=term-missing:skip-covered",  # show missing lines, skip 100% files
    "--cov-report=html:htmlcov",                # HTML report for local browsing
    "--cov-report=xml:coverage.xml",            # XML for CI/codecov upload
    "--cov-fail-under=80",                      # fail if overall coverage < 80%
]

[tool.coverage.run]
branch = true          # branch coverage, not just line coverage
source = ["src"]
omit = [
    "*/tests/*",
    "*/migrations/*",
    "*/__init__.py",
    "*/conftest.py",
]

[tool.coverage.report]
precision = 2
show_missing = true
skip_covered = true    # don't list files with 100% coverage
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "def __str__",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "@(abc\\.)?abstractmethod",
    "\\.\\.\\.",      # bare ellipsis (Protocol stubs, abstract bodies)
]
```

### Per-Module Coverage Thresholds

For different minimum coverage requirements per module:

```toml
[tool.coverage.report]
# Require 90% coverage for the core domain, less for adapters
fail_under = 80    # global floor

[tool.coverage.paths]
# Map installed paths back to source paths (for CI environments)
source = ["src/", ".tox/*/lib/*/site-packages/"]
```

Alternatively, use `# pragma: no cover` on lines that are genuinely untestable:

```python
def __repr__(self) -> str:  # pragma: no cover
    return f"FeaturePipeline(batch_size={self.batch_size})"

if __name__ == "__main__":  # pragma: no cover
    main()
```

### Reading the Coverage Report

```
Name                              Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------------------------------
src/feature_pipeline/pipeline.py     87      4     32      2    93%   45-48, 112
src/feature_pipeline/storage.py      52     12     18      4    74%   23, 67-78
```

**Reading the output:**
- `Miss`: lines never executed
- `Branch`: number of possible branches (both sides of `if`)
- `BrPart`: branches where only one side was tested
- `Missing: 45-48, 112`: lines 45–48 and 112 were never executed

The `Missing` column is the most actionable — those are the lines to add tests for.

---

## 2. CI Pipeline Structure

### Three-Stage Design

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  # ── Stage 1: Static Analysis (fastest, no tests) ──────────────────────────
  quality:
    name: Code Quality
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - run: uv sync --frozen --dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/
      - run: uv run mypy src/

  # ── Stage 2: Unit Tests (fast, no infrastructure) ─────────────────────────
  unit-tests:
    name: Unit Tests (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    needs: quality
    strategy:
      fail-fast: false   # run all Python versions even if one fails
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: ${{ matrix.python-version }}
          enable-cache: true
      - run: uv sync --frozen --dev
      - run: uv run pytest tests/unit/ -m unit --cov --cov-report=xml
      - uses: codecov/codecov-action@v4
        if: matrix.python-version == '3.12'  # upload once
        with:
          files: coverage.xml
          token: ${{ secrets.CODECOV_TOKEN }}

  # ── Stage 3: Integration Tests (slower, needs Docker) ─────────────────────
  integration-tests:
    name: Integration Tests
    runs-on: ubuntu-latest
    needs: unit-tests
    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: --health-cmd "redis-cli ping" --health-interval 10s
      postgres:
        image: postgres:16-alpine
        ports: ["5432:5432"]
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test
        options: --health-cmd "pg_isready -U test" --health-interval 10s
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - run: uv sync --frozen --dev
      - run: uv run pytest tests/integration/ -m integration
        env:
          DATABASE_URL: postgresql://test:test@localhost/test
          REDIS_URL: redis://localhost:6379/0
```

### Using GitHub Actions Services vs Testcontainers

Two approaches to infrastructure in CI:

| Approach | Pros | Cons |
|----------|------|------|
| GitHub Actions `services:` | No Docker-in-Docker needed; simpler | Fixed versions, no programmatic control |
| testcontainers | Same setup as local; programmatic; version control | Requires Docker-in-Docker in CI (available on ubuntu-latest) |

Use `services:` for simple single-instance needs. Use testcontainers when you need multiple versions, dynamic configuration, or complex multi-container setups.

---

## 3. Test Parallelism with `pytest-xdist`

`pytest-xdist` distributes tests across multiple processes, reducing total run time proportionally to available cores.

```bash
uv add --dev pytest-xdist
```

```bash
# Run with 4 workers
pytest tests/unit/ -n 4

# Auto-detect CPU count
pytest tests/unit/ -n auto

# In CI (GitHub Actions has 2 cores on ubuntu-latest)
pytest tests/unit/ -n 2
```

### Making Tests Safe for Parallelism

Parallel tests run in separate processes — shared state causes race conditions:

```python
# Bad: global state shared across parallel tests
_cache: dict = {}

def test_caching():
    _cache["key"] = "value"
    assert _cache["key"] == "value"

# Good: each test creates its own isolated state
def test_caching(tmp_path):
    cache = FileCache(base_path=tmp_path)
    cache.set("key", "value")
    assert cache.get("key") == "value"
```

For tests that truly cannot run in parallel (e.g., they need a specific port), use the `xdist` group marker:

```python
@pytest.mark.xdist_group("serial")  # all tests in this group run serially in one worker
def test_needs_port_8080():
    ...
```

---

## 4. Test Caching and Incremental Runs

### `--lf` (Last Failed) and `--ff` (Failed First)

```bash
# Run only the tests that failed in the last run
pytest --lf

# Run failed tests first, then the rest
pytest --ff

# Stop on first failure
pytest -x

# Stop after N failures
pytest --maxfail=3
```

### Cache Invalidation with `uv`

In CI, cache the uv virtual environment to avoid reinstalling on every run:

```yaml
- uses: astral-sh/setup-uv@v3
  with:
    enable-cache: true        # caches .venv based on uv.lock hash
    cache-dependency-glob: "uv.lock"
```

---

## 5. Performance Testing with `pytest-benchmark`

For code where performance is part of the contract (inference latency, feature computation throughput):

```bash
uv add --dev pytest-benchmark
```

```python
# tests/performance/test_inference_benchmark.py
import pytest

@pytest.mark.benchmark(group="inference", min_rounds=100)
def test_single_inference_latency(benchmark, inference_pipeline):
    """Single entity inference P95 latency must be < 10ms."""
    features = {"age_normalized": 0.5, "purchase_count": 10, "recency_score": 0.7}
    
    result = benchmark(inference_pipeline.predict, entity_id="user-1", features=features)
    
    # benchmark.stats is populated after the run
    assert benchmark.stats["median"] * 1000 < 10, \
        f"Median latency {benchmark.stats['median'] * 1000:.2f}ms exceeds 10ms SLA"

@pytest.mark.benchmark(group="preprocessing")
def test_batch_normalization_throughput(benchmark, raw_feature_batch):
    """Batch normalization should process 1000 records in < 50ms."""
    result = benchmark(normalize_batch, raw_feature_batch)
    
    # benchmark.stats["mean"] is in seconds
    throughput = len(raw_feature_batch) / benchmark.stats["mean"]
    assert throughput >= 20_000, \
        f"Throughput {throughput:.0f} records/s below 20k/s target"
```

```bash
# Run benchmarks
pytest tests/performance/ --benchmark-only
pytest tests/performance/ --benchmark-json=benchmark_results.json

# Compare against previous run (detect regressions)
pytest tests/performance/ --benchmark-compare=benchmark_results.json \
    --benchmark-compare-fail=mean:10%    # fail if mean degrades by > 10%
```

---

## 6. Handling Flaky Tests

Flaky tests are tests that pass and fail non-deterministically. They are worse than no tests — they erode confidence in the entire test suite and train people to re-run rather than investigate.

### Identifying Flakiness

```bash
# Run tests N times to find flaky ones
uv add --dev pytest-repeat
pytest --count=10 tests/  # run each test 10 times
```

### Common Flakiness Causes and Fixes

| Cause | Fix |
|-------|-----|
| Timing-dependent (sleep, poll) | Use explicit waiting with timeout |
| Shared global state | Isolate state per test (fixtures) |
| Port conflicts in parallel | Use ephemeral ports (`:0`) |
| Ordering dependency | Use `--randomly-seed=12345` to detect |
| Non-deterministic sorting | Sort or normalize the assertion |
| Floating point comparison | Use `pytest.approx()` |

```python
# Bad: timing-dependent
def test_worker_processes_job():
    queue.push(job)
    time.sleep(2)  # hope it processed in time
    assert result_store.get("job-1") is not None

# Good: explicit polling with timeout
def test_worker_processes_job():
    queue.push(job)
    
    deadline = time.monotonic() + 10.0  # 10 second timeout
    while time.monotonic() < deadline:
        result = result_store.get("job-1")
        if result is not None:
            return
        time.sleep(0.1)
    
    pytest.fail("Job was not processed within 10 seconds")
```

### Quarantine Flaky Tests

When you can't fix a flaky test immediately, quarantine it — don't let it block CI:

```python
@pytest.mark.flaky(reruns=3, reruns_delay=1)  # requires pytest-rerunfailures
def test_sometimes_flaky_integration():
    ...
```

```bash
uv add --dev pytest-rerunfailures
pytest tests/ --reruns 3 --reruns-delay 1
```

---

## 7. Complete CI Configuration Reference

A production-ready CI configuration for a Python ML service:

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true   # cancel in-progress CI when new commit is pushed

env:
  UV_SYSTEM_PYTHON: 1
  PYTHON_VERSION: "3.12"

jobs:
  lint:
    name: Lint & Type Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - run: uv sync --frozen --dev
      - run: uv run ruff check . --output-format=github
      - run: uv run ruff format --check .
      - run: uv run mypy src/ --no-error-summary

  unit:
    name: Unit Tests
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: ${{ matrix.python }}
          enable-cache: true
      - run: uv sync --frozen --dev
      - run: |
          uv run pytest tests/unit/ \
            -n auto \
            --cov=src \
            --cov-report=xml \
            --cov-fail-under=80 \
            -q
      - uses: codecov/codecov-action@v4
        if: matrix.python == '3.12' && github.event_name == 'push'
        with:
          files: coverage.xml

  integration:
    name: Integration Tests
    runs-on: ubuntu-latest
    needs: unit
    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: testdb
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 10s
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - run: uv sync --frozen --dev
      - run: |
          uv run pytest tests/integration/ \
            -m integration \
            --timeout=60 \
            -q
        env:
          DATABASE_URL: postgresql://postgres:test@localhost/testdb
          REDIS_URL: redis://localhost:6379/0
          LOG_LEVEL: WARNING

  # Summary job — required branch protection check
  ci-success:
    name: CI Success
    runs-on: ubuntu-latest
    needs: [lint, unit, integration]
    if: always()
    steps:
      - name: Check all jobs succeeded
        run: |
          if [[ "${{ needs.lint.result }}" != "success" ]] || \
             [[ "${{ needs.unit.result }}" != "success" ]] || \
             [[ "${{ needs.integration.result }}" != "success" ]]; then
            echo "One or more CI jobs failed"
            exit 1
          fi
```

The `ci-success` job is a single required check for branch protection. Without it, you'd need to list every individual matrix job as a required check (fragile when the matrix changes).

---

## Summary

| Concern | Tool / Practice |
|---------|----------------|
| Coverage tracking | `pytest-cov` + branch coverage + `--cov-fail-under` |
| CI stages | Lint → Unit (matrix) → Integration (sequential) |
| Test parallelism | `pytest-xdist` with `-n auto` |
| Caching in CI | `astral-sh/setup-uv` with `enable-cache: true` |
| Last-failed local dev | `pytest --lf` / `pytest --ff` |
| Performance tests | `pytest-benchmark` with regression threshold |
| Flaky test handling | `pytest-rerunfailures` + quarantine + explicit polling |
| Branch protection | Single `ci-success` aggregator job |
