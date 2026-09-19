# 02 — pytest Core

## Why pytest Over unittest

Python ships with `unittest`. pytest is the industry standard for production Python. The reasons:

- **No boilerplate**: plain `assert` statements, no `self.assertEqual()` noise
- **Fixtures over setUp/tearDown**: composable, typed, scope-aware
- **Parametrize**: data-driven tests in one decorator
- **Rich plugin ecosystem**: 1000+ plugins covering async, databases, benchmarks, coverage, etc.
- **Better failure output**: diffs, local variable values, assertion rewriting
- **Incremental adoption**: pytest runs `unittest.TestCase` subclasses natively

```bash
uv add --dev pytest pytest-cov pytest-mock
```

---

## 1. pytest Configuration

Everything in `pyproject.toml` — no separate `pytest.ini` needed:

```toml
[tool.pytest.ini_options]
# Where to look for tests
testpaths = ["tests"]

# Default options appended to every pytest invocation
addopts = [
    "--strict-markers",     # fail if an unregistered marker is used
    "--strict-config",      # fail on config warnings
    "-ra",                  # show summary of all non-passing tests
    "--tb=short",           # shorter tracebacks
]

# Register custom markers — prevents typos in markers
markers = [
    "unit: Fast, isolated unit tests",
    "integration: Tests that hit real infrastructure",
    "contract: Consumer-driven contract tests",
    "e2e: End-to-end tests against deployed service",
    "slow: Tests that take > 5 seconds",
]

# Filter warnings
filterwarnings = [
    "error",                           # treat all warnings as errors
    "ignore::DeprecationWarning:boto3", # except known noisy libraries
    "ignore::DeprecationWarning:botocore",
]
```

---

## 2. Fixtures — The Core Abstraction

Fixtures are the dependency injection system of pytest. A test declares what it needs in its arguments; pytest resolves and provides them.

### Basic Fixture

```python
# tests/conftest.py
import pytest
from feature_pipeline.config import AppConfig

@pytest.fixture
def default_config() -> AppConfig:
    return AppConfig(
        redis_host="localhost",
        redis_port=6379,
        batch_size=32,
        log_level="DEBUG",
    )

# tests/unit/test_pipeline.py
from feature_pipeline.pipeline import FeaturePipeline

def test_pipeline_uses_config_batch_size(default_config):
    pipeline = FeaturePipeline(config=default_config)
    assert pipeline.batch_size == 32
```

### Fixture Scopes

Fixtures have four scopes — from fastest to most reused:

| Scope | Created | Destroyed | Use for |
|-------|---------|-----------|---------|
| `function` (default) | Each test | After each test | Most fixtures |
| `class` | First test in a class | After last test in class | Shared state within a class |
| `module` | First test in a module | After last test in module | Expensive setup per file |
| `session` | First test in the session | After all tests | DB connections, Docker containers |

```python
# tests/conftest.py

@pytest.fixture(scope="function")    # default: fresh for every test
def clean_redis_client(redis_server):
    client = redis.Redis(host=redis_server.host, port=redis_server.port)
    yield client
    client.flushdb()  # clean up after each test

@pytest.fixture(scope="session")     # one instance for the entire test run
def redis_server():
    """Start a Redis server once for the entire test session."""
    with RedisContainer() as container:
        yield container
        # container stopped after all tests complete
```

### Fixture Teardown with `yield`

Use `yield` to separate setup from teardown. Everything after `yield` runs after the test completes — even if the test fails.

```python
@pytest.fixture
def temp_feature_store(tmp_path):
    """A file-backed feature store in a temporary directory."""
    store = FileFeatureStore(base_path=tmp_path / "features")
    store.initialize()
    yield store
    # Cleanup is automatic — tmp_path is deleted by pytest after the session
    # But if we need explicit cleanup:
    store.close()
```

### `conftest.py` — Fixture Discovery

pytest automatically discovers `conftest.py` files and makes their fixtures available to all tests at or below that directory level.

```
tests/
├── conftest.py          # fixtures here available everywhere
├── unit/
│   ├── conftest.py      # fixtures here available only to unit/
│   └── test_pipeline.py
└── integration/
    ├── conftest.py      # fixtures here available only to integration/
    └── test_storage.py
```

```python
# tests/conftest.py — session-wide fixtures
@pytest.fixture(scope="session")
def app_config() -> AppConfig:
    return AppConfig.from_env()

# tests/unit/conftest.py — unit-test-specific fixtures
@pytest.fixture
def mock_feature_store() -> MagicMock:
    store = MagicMock(spec=FeatureStore)
    store.get.return_value = {"user_id": "123", "value": 0.5}
    return store

# tests/integration/conftest.py — real infrastructure fixtures
@pytest.fixture(scope="session")
def real_redis(docker_services):
    ...
```

### Factory Fixtures

Instead of a fixture that returns one object, return a factory function. This lets each test customize the object while sharing setup logic.

```python
@pytest.fixture
def make_training_config():
    """Factory fixture: returns a function that creates TrainingConfig instances."""
    def _make(
        model_name: str = "bert-base",
        learning_rate: float = 0.001,
        batch_size: int = 32,
        **overrides,
    ) -> TrainingConfig:
        return TrainingConfig(
            model_name=model_name,
            learning_rate=learning_rate,
            batch_size=batch_size,
            **overrides,
        )
    return _make

# Usage in tests
def test_pipeline_rejects_zero_learning_rate(make_training_config):
    config = make_training_config(learning_rate=0.0)
    with pytest.raises(ValueError, match="learning_rate must be positive"):
        FeaturePipeline(config=config)

def test_pipeline_accepts_large_batch(make_training_config):
    config = make_training_config(batch_size=2048)
    pipeline = FeaturePipeline(config=config)
    assert pipeline.batch_size == 2048
```

### `tmp_path` — Temporary File Fixtures

pytest provides `tmp_path` as a built-in fixture: a `pathlib.Path` pointing to a fresh temporary directory, unique per test and automatically cleaned up.

```python
def test_checkpoint_saves_and_loads(tmp_path, trained_model):
    checkpoint_path = tmp_path / "model.ckpt"
    
    # Save
    trained_model.save_checkpoint(checkpoint_path)
    assert checkpoint_path.exists()
    
    # Load and verify
    restored = Model.load_checkpoint(checkpoint_path)
    assert restored.config == trained_model.config
```

### `monkeypatch` — Environment and Attribute Overrides

`monkeypatch` lets you temporarily override environment variables, module attributes, and built-ins — and automatically restores them after the test.

```python
def test_settings_reads_database_url_from_env(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("APP_ENV", "test")
    
    settings = AppSettings()
    assert settings.database_url == "postgresql://test:test@localhost/test"

def test_pipeline_uses_env_batch_size(monkeypatch):
    monkeypatch.setenv("PIPELINE_BATCH_SIZE", "128")
    pipeline = FeaturePipeline.from_env()
    assert pipeline.batch_size == 128

def test_feature_store_timeout(monkeypatch):
    # Override a module-level constant
    monkeypatch.setattr("feature_pipeline.storage.DEFAULT_TIMEOUT", 0.001)
    store = FeatureStore(host="localhost")
    with pytest.raises(TimeoutError):
        store.get("user-123")
```

---

## 3. Parametrize — Data-Driven Tests

`@pytest.mark.parametrize` runs the same test body with different inputs. It reduces repetition and makes it easy to add new cases.

### Basic Parametrize

```python
import pytest
from feature_pipeline.preprocessing import normalize

@pytest.mark.parametrize("value, min_val, max_val, expected", [
    (0,    0,   100, 0.0),   # minimum
    (100,  0,   100, 1.0),   # maximum
    (50,   0,   100, 0.5),   # midpoint
    (-10, -10,  10,  0.0),   # negative minimum
    (10,  -10,  10,  1.0),   # negative maximum
    (0,   -10,  10,  0.5),   # zero in negative range
])
def test_normalize_produces_expected_output(value, min_val, max_val, expected):
    result = normalize(value, min_val=min_val, max_val=max_val)
    assert abs(result - expected) < 1e-9
```

pytest names each case in the output: `test_normalize[0-0-100-0.0]`, `test_normalize[100-0-100-1.0]`, etc. Use `ids` for readable names:

```python
@pytest.mark.parametrize("raw_input, expected_error", [
    ("",          "input must not be empty"),
    ("   ",       "input must not be empty"),
    ("a" * 1001,  "input exceeds maximum length"),
    ("<script>",  "input contains disallowed characters"),
], ids=["empty", "whitespace_only", "too_long", "xss_attempt"])
def test_validate_input_raises_on_invalid(raw_input, expected_error):
    with pytest.raises(ValueError, match=expected_error):
        validate_input(raw_input)
```

### Parametrize with Fixtures

You can combine `parametrize` with fixtures:

```python
@pytest.fixture(params=["min_max", "z_score", "robust"])
def normalization_method(request) -> str:
    return request.param

def test_normalize_produces_finite_output_for_all_methods(normalization_method):
    """All normalization methods must produce finite floats for valid input."""
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = normalize_features(data, method=normalization_method)
    assert all(math.isfinite(v) for v in result)
    assert len(result) == len(data)
```

This runs the test three times — once per method.

### Indirect Parametrize (Fixture-Based)

When you want to parametrize the fixture itself:

```python
@pytest.fixture
def feature_store(request):
    backend = request.param
    if backend == "redis":
        return RedisFeatureStore(host="localhost")
    elif backend == "memory":
        return InMemoryFeatureStore()

@pytest.mark.parametrize("feature_store", ["redis", "memory"], indirect=True)
def test_store_get_returns_none_for_missing_key(feature_store):
    assert feature_store.get("nonexistent_key") is None
```

---

## 4. Markers — Categorizing Tests

Markers tag tests for selective execution.

```python
import pytest

@pytest.mark.unit
def test_normalize_clamps_to_one():
    assert normalize(200, min_val=0, max_val=100) == 1.0

@pytest.mark.integration
@pytest.mark.slow
def test_pipeline_processes_large_batch(real_redis, real_gcs):
    ...

@pytest.mark.e2e
def test_serving_api_returns_features():
    ...

# Skip a test conditionally
@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)
def test_llm_feature_extraction():
    ...

# Mark as expected to fail (xfail) — useful for known bugs in development
@pytest.mark.xfail(
    reason="Batch normalization not yet implemented for empty batches, tracked in #187",
    strict=True,  # fail the test if it unexpectedly passes
)
def test_normalize_empty_batch():
    result = normalize_batch([])
    assert result == []
```

**Selective execution:**

```bash
pytest -m unit                  # only unit tests
pytest -m "not slow"            # exclude slow tests
pytest -m "integration and not e2e"
pytest tests/unit/ -m unit      # combine directory + marker
```

---

## 5. Testing Exception Paths

Test that your code raises the right exceptions under the right conditions:

```python
def test_pipeline_raises_value_error_for_empty_entity_list():
    pipeline = FeaturePipeline(config=default_config)
    with pytest.raises(ValueError, match="entity_ids must not be empty"):
        pipeline.run(entity_ids=[])

def test_schema_validator_raises_with_field_name():
    bad_record = {"user_id": "123", "age": "not_a_number"}
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_schema(bad_record, schema=USER_SCHEMA)
    
    # Inspect the exception in detail
    assert exc_info.value.field == "age"
    assert "expected int" in str(exc_info.value)

def test_feature_store_raises_on_connection_failure():
    store = FeatureStore(host="nonexistent.host", port=9999)
    with pytest.raises(InfrastructureError) as exc_info:
        store.get("user-123")
    
    # Check exception chaining
    assert exc_info.value.__cause__ is not None
    assert "Connection refused" in str(exc_info.value.__cause__)
```

---

## 6. Asserting on Collections and Approximate Values

```python
# Float comparison — never use ==
import pytest

def test_loss_decreases_during_training():
    losses = train_for_n_steps(model, n=10)
    assert losses[-1] < losses[0], "Loss did not decrease"
    assert losses[-1] == pytest.approx(0.234, abs=0.01)  # ± 0.01

# Collection assertions
def test_pipeline_output_has_expected_keys():
    features = pipeline.run(["user-1"])
    assert set(features[0].keys()) >= {"user_id", "age_normalized", "purchase_count"}

def test_features_all_in_valid_range():
    features = pipeline.run(["user-1", "user-2", "user-3"])
    for feature in features:
        assert 0.0 <= feature["age_normalized"] <= 1.0
        assert feature["purchase_count"] >= 0

# Dict subset assertion (check a dict contains certain key-value pairs)
def test_response_contains_required_fields():
    response = api_client.get("/features/user-1")
    assert response.json() == pytest.approx({
        "user_id": "user-1",
        "features": ...,  # not checked
        "timestamp": ...,
    })
```

---

## 7. A Complete Test File Example

Putting it all together for a real-world scenario:

```python
# tests/unit/test_preprocessing.py
"""
Unit tests for feature_pipeline.preprocessing module.

Tests are isolated — no I/O, no external services.
All dependencies are injected via fixtures or replaced with in-memory fakes.
"""
import math
import pytest
from feature_pipeline.preprocessing import (
    normalize_features,
    validate_feature_schema,
    FeatureTransformer,
)
from feature_pipeline.exceptions import SchemaValidationError


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def make_feature_record():
    def _make(
        user_id: str = "user-123",
        age: int = 30,
        purchase_count: int = 5,
        **overrides,
    ) -> dict:
        return {"user_id": user_id, "age": age, "purchase_count": purchase_count, **overrides}
    return _make

@pytest.fixture
def transformer() -> FeatureTransformer:
    return FeatureTransformer(
        normalization="min_max",
        clip_outliers=True,
        outlier_threshold=3.0,
    )


# ── normalize_features ───────────────────────────────────────────────────────

class TestNormalizeFeatures:
    @pytest.mark.parametrize("values, expected", [
        ([0, 50, 100],     [0.0, 0.5, 1.0]),
        ([1, 1, 1],        [0.0, 0.0, 0.0]),   # all same: returns zeros
        ([-10, 0, 10],     [0.0, 0.5, 1.0]),
        ([100],            [0.0]),              # single element
    ], ids=["normal_range", "all_same", "negative_range", "single_element"])
    def test_produces_values_in_unit_range(self, values, expected):
        result = normalize_features(values, method="min_max")
        assert result == pytest.approx(expected, abs=1e-9)

    def test_returns_empty_list_for_empty_input(self):
        assert normalize_features([], method="min_max") == []

    def test_all_values_finite_for_z_score_method(self):
        data = list(range(100))
        result = normalize_features(data, method="z_score")
        assert all(math.isfinite(v) for v in result)

    def test_raises_value_error_for_unknown_method(self):
        with pytest.raises(ValueError, match="Unknown normalization method"):
            normalize_features([1, 2, 3], method="nonexistent")


# ── validate_feature_schema ──────────────────────────────────────────────────

class TestValidateFeatureSchema:
    def test_accepts_valid_record(self, make_feature_record):
        record = make_feature_record()
        # Should not raise
        validate_feature_schema(record)

    def test_raises_for_missing_required_field(self, make_feature_record):
        record = make_feature_record()
        del record["user_id"]
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_feature_schema(record)
        assert exc_info.value.field == "user_id"

    def test_raises_for_negative_purchase_count(self, make_feature_record):
        record = make_feature_record(purchase_count=-1)
        with pytest.raises(SchemaValidationError, match="purchase_count must be >= 0"):
            validate_feature_schema(record)

    def test_raises_for_wrong_age_type(self, make_feature_record):
        record = make_feature_record(age="thirty")
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_feature_schema(record)
        assert exc_info.value.field == "age"
        assert "expected int" in str(exc_info.value)


# ── FeatureTransformer ───────────────────────────────────────────────────────

class TestFeatureTransformer:
    def test_clips_outliers_beyond_threshold(self, transformer, make_feature_record):
        records = [
            make_feature_record(age=25),
            make_feature_record(age=999),   # clear outlier
            make_feature_record(age=30),
        ]
        result = transformer.fit_transform(records)
        ages = [r["age_normalized"] for r in result]
        assert max(ages) <= 1.0, "Outlier was not clipped"

    def test_fit_stores_statistics(self, transformer, make_feature_record):
        records = [make_feature_record(age=a) for a in [20, 30, 40, 50, 60]]
        transformer.fit(records)
        assert transformer.statistics_["age"]["mean"] == pytest.approx(40.0)
        assert transformer.statistics_["age"]["std"] > 0

    def test_transform_before_fit_raises(self, transformer, make_feature_record):
        with pytest.raises(RuntimeError, match="must call fit\\(\\) before transform\\(\\)"):
            transformer.transform([make_feature_record()])
```
