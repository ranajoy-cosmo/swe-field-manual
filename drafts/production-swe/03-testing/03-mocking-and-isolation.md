# 03 — Mocking and Isolation

## The Purpose of Mocking

Mocking is not a testing technique — it's an isolation technique. You mock to remove the parts of the system that are not the thing you're testing. The test then becomes a precise measurement of one unit's behavior.

When you mock external dependencies:
- The test is fast (no network roundtrip, no DB query)
- The test is deterministic (no flakiness from external state)
- Failures point directly at the unit under test

When you mock *too much*:
- The test stops being useful (you're testing the mock, not the code)
- Refactors that don't change behavior still break tests
- You build false confidence

The discipline is knowing *which* boundary to mock at, and *how much* of it to replace.

---

## 1. What to Mock

**Always mock:**
- External HTTP calls (third-party APIs, internal services)
- Clock and time (anything that calls `datetime.now()`, `time.time()`)
- Random number generators
- Filesystem I/O in unit tests (use `tmp_path` in integration tests instead)
- Email/notification senders
- External queues (Kafka, SQS, Pub/Sub)

**Mock at the integration layer, not in unit tests:**
- Databases (use an in-memory or containerized DB in integration tests)
- Caches (same — use a real Redis container)

**Never mock:**
- The class or function under test itself
- Standard library functions that don't do I/O
- Data classes or simple value objects
- `Pydantic` models (just construct them)

---

## 2. The Mock Stack

Python's mocking ecosystem has three layers:

| Tool | What it provides |
|------|-----------------|
| `unittest.mock` (stdlib) | `MagicMock`, `patch`, `AsyncMock`, `call` |
| `pytest-mock` | `mocker` fixture — wraps `unittest.mock`, auto-resets after each test |
| `responses` / `httpretty` | HTTP-level mocking (intercepts requests/httpx calls) |
| `respx` | httpx-specific mock router |

```bash
uv add --dev pytest-mock responses respx
```

---

## 3. `pytest-mock` — The `mocker` Fixture

`mocker` is the correct way to patch in pytest. It automatically undoes all patches after each test, avoiding test pollution.

### `mocker.patch` — Replace an Object

```python
def test_fetch_user_calls_correct_endpoint(mocker):
    # Patch requests.get inside the api module
    mock_get = mocker.patch("feature_pipeline.api.client.requests.get")
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"user_id": "123", "age": 30}

    result = fetch_user_profile("123")

    # Verify behavior
    assert result.user_id == "123"
    mock_get.assert_called_once_with(
        "https://users.internal/api/v1/users/123",
        timeout=5,
    )
```

**The patch target is critical.** Patch where the name is *used*, not where it's *defined*:

```python
# feature_pipeline/api.py
import requests  # requests is imported here
def call_api(): requests.get(...)  # used here

# In the test, patch where it's used:
mocker.patch("feature_pipeline.api.requests.get")  # correct
mocker.patch("requests.get")                         # wrong — patches the original, not the import
```

### `mocker.patch.object` — Patch a Specific Instance's Method

```python
def test_pipeline_retries_on_failure(mocker, pipeline):
    # Patch one method on an existing object
    mocker.patch.object(
        pipeline.store,
        "get",
        side_effect=[TimeoutError("Redis timeout"), {"value": 0.5}]  # fail then succeed
    )

    result = pipeline.get_features("user-123")
    assert result == {"value": 0.5}
    assert pipeline.store.get.call_count == 2
```

### `side_effect` — Dynamic Return Values

`side_effect` is more powerful than `return_value`:

```python
# Return different values on sequential calls
mock_store.get.side_effect = [
    {"value": 1.0},    # first call returns this
    {"value": 2.0},    # second call returns this
    KeyError("key"),   # third call raises this
]

# Always raise an exception
mock_store.get.side_effect = ConnectionError("Redis unavailable")

# Conditional behavior
def fake_get(key):
    if key.startswith("user"):
        return {"value": 0.5}
    raise KeyError(f"Unknown key: {key}")

mock_store.get.side_effect = fake_get
```

### `MagicMock` with `spec` — Type-Safe Mocks

A plain `MagicMock` accepts any attribute access and returns another `MagicMock`. This can hide bugs:

```python
# Bug: typo in method name — plain MagicMock doesn't catch this
mock_store = MagicMock()
mock_store.fet("user-123")   # typo: should be get() — passes silently
```

Use `spec=` to restrict the mock to the interface of the real class:

```python
mock_store = MagicMock(spec=FeatureStore)
mock_store.fet("user-123")   # AttributeError: spec does not have attribute 'fet'
mock_store.get("user-123")   # OK
```

```python
# In conftest.py — a spec'd fixture
@pytest.fixture
def mock_feature_store() -> MagicMock:
    store = MagicMock(spec=FeatureStore)
    store.get.return_value = {"user_id": "user-123", "value": 0.5}
    store.exists.return_value = True
    return store
```

### `mocker.spy` — Record Calls Without Replacing

A spy wraps a real function — it still runs the original code but also records calls:

```python
def test_normalize_is_called_for_each_feature(mocker, transformer):
    spy = mocker.spy(transformer, "normalize")
    
    transformer.transform(features=["age", "income", "tenure"])
    
    assert spy.call_count == 3
```

---

## 4. Mocking Time

Code that depends on the current time is a classic source of test fragility. `freezegun` freezes time at a specified point:

```bash
uv add --dev freezegun
```

```python
from freezegun import freeze_time
from datetime import datetime

@freeze_time("2024-03-15 12:00:00")
def test_feature_timestamp_is_current_time():
    feature = compute_feature("user-123")
    assert feature.computed_at == datetime(2024, 3, 15, 12, 0, 0)

# As a context manager
def test_expiry_check_uses_current_time():
    with freeze_time("2024-01-01"):
        store.set("key", value, ttl_seconds=3600)
    
    with freeze_time("2024-01-01 01:30:00"):  # 90 minutes later
        assert store.is_expired("key") is True
```

For `mocker`-based time mocking without freezegun:

```python
def test_pipeline_records_processing_time(mocker):
    # Freeze time.perf_counter for duration measurement
    mock_perf = mocker.patch("feature_pipeline.pipeline.time.perf_counter")
    mock_perf.side_effect = [0.0, 1.5]  # start=0.0, end=1.5 → 1.5 seconds
    
    result = pipeline.run(entity_ids=["user-1"])
    assert result.duration_seconds == pytest.approx(1.5)
```

---

## 5. HTTP Mocking with `respx`

When your code uses `httpx` (the modern async-compatible HTTP client), use `respx` to mock at the HTTP protocol level. This tests your HTTP integration code (headers, URL construction, error handling) without making real network calls.

```bash
uv add --dev respx
```

```python
import httpx
import respx
import pytest

@respx.mock
def test_user_service_client_parses_response():
    # Define what the mock server returns
    respx.get("https://users.internal/api/v1/users/123").mock(
        return_value=httpx.Response(
            200,
            json={"user_id": "123", "age": 30, "segment": "premium"},
        )
    )
    
    client = UserServiceClient(base_url="https://users.internal")
    user = client.get_user("123")
    
    assert user.user_id == "123"
    assert user.segment == "premium"

@respx.mock
def test_user_service_client_raises_on_404():
    respx.get("https://users.internal/api/v1/users/nonexistent").mock(
        return_value=httpx.Response(404, json={"detail": "User not found"})
    )
    
    client = UserServiceClient(base_url="https://users.internal")
    with pytest.raises(UserNotFoundError, match="nonexistent"):
        client.get_user("nonexistent")

@respx.mock
def test_client_retries_on_503():
    route = respx.get("https://users.internal/api/v1/users/123")
    route.side_effect = [
        httpx.Response(503),           # first call: service unavailable
        httpx.Response(503),           # second call: still unavailable
        httpx.Response(200, json={"user_id": "123", "age": 30}),  # third: success
    ]
    
    client = UserServiceClient(base_url="https://users.internal", max_retries=3)
    user = client.get_user("123")
    
    assert user.user_id == "123"
    assert route.call_count == 3
```

For `requests`-based code, use `responses`:

```python
import responses as responses_mock

@responses_mock.activate
def test_legacy_client():
    responses_mock.add(
        responses_mock.GET,
        "https://api.example.com/data",
        json={"result": "ok"},
        status=200,
    )
    result = legacy_client.fetch_data()
    assert result["result"] == "ok"
```

---

## 6. Fakes — The Better Alternative to Mocks

A **fake** is a lightweight, working implementation of an interface — simpler than the real thing but behaviorally correct. Fakes are often better than mocks because:

- They test more real behavior (the fake's logic runs)
- They don't break when you refactor internals
- They're reusable across many tests

```python
# A fake feature store — uses a dict instead of Redis
class InMemoryFeatureStore:
    """Fake implementation of FeatureStore for testing."""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        return self._store.get(key)

    def set(self, key: str, value: dict, ttl_seconds: int | None = None) -> None:
        self._store[key] = value  # TTL not implemented — fine for tests

    def exists(self, key: str) -> bool:
        return key in self._store

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

# conftest.py
@pytest.fixture
def feature_store() -> InMemoryFeatureStore:
    return InMemoryFeatureStore()

# Tests use the fake transparently
def test_pipeline_skips_missing_features(feature_store):
    # feature_store is empty — no features set
    pipeline = FeaturePipeline(store=feature_store)
    result = pipeline.run(["user-1", "user-2"])
    assert result.missing_count == 2
```

**When to use a fake vs a mock:**

| Situation | Prefer |
|-----------|--------|
| Testing behavior that depends on stored state | Fake (state persists across calls) |
| Testing that a specific method is called with specific args | Mock |
| Testing retry logic, error paths | Mock (easy to inject failures) |
| Testing a full component workflow | Fake (realistic behavior) |

---

## 7. Common Mocking Pitfalls

### Pitfall 1: Patching the Wrong Target

```python
# feature_pipeline/pipeline.py
from datetime import datetime

def get_current_timestamp() -> datetime:
    return datetime.utcnow()

# Wrong: patches datetime in the datetime module, not where it's used
mocker.patch("datetime.datetime.utcnow")

# Correct: patch where it's imported
mocker.patch("feature_pipeline.pipeline.datetime")
```

### Pitfall 2: Mocking What You Don't Own

Don't mock third-party code. You don't own the contract — your mock may not reflect reality.

```python
# Bad: mocking pydantic internals
mocker.patch("pydantic.BaseModel.__init__", ...)

# Good: construct real Pydantic models with test data
config = TrainingConfig(model_name="test", learning_rate=0.001, batch_size=32)
```

### Pitfall 3: Over-specifying Mock Interactions

Tests that assert exact call signatures of mocks are brittle. Assert on outcomes, not on interactions, unless the interaction *is* the behavior you're testing.

```python
# Bad: brittle — breaks if you reorder internal calls
mock_cache.get.assert_called_with("user:123:features", expire=300)

# Good: assert on the observable outcome
result = pipeline.get_features("user-123")
assert result is not None
assert result["user_id"] == "user-123"
```

### Pitfall 4: Not Resetting Mocks Between Tests

Using `mocker` (pytest-mock) handles this automatically. If using `patch` manually, use `patch` as a context manager or decorator — never assign a patcher without calling `stop()`.

```python
# Bad: patcher leaks between tests
patcher = patch("module.thing")
mock_thing = patcher.start()
# ... test body ...
# forgot: patcher.stop()

# Good: context manager guarantees cleanup
with patch("module.thing") as mock_thing:
    ...

# Good: mocker fixture handles it
def test_something(mocker):
    mock_thing = mocker.patch("module.thing")
    ...  # auto-stopped after test
```

### Pitfall 5: Mocking Makes a Test Pass When It Shouldn't

If removing the mock makes the test meaningless, the test is testing the mock, not the code.

```python
# Useless: this test only proves mocker.patch works
def test_feature_service_returns_features(mocker):
    mocker.patch("feature_pipeline.service.compute", return_value={"value": 0.5})
    service = FeatureService()
    result = service.get_features("user-1")
    assert result == {"value": 0.5}  # this always passes — we set it up ourselves

# Useful: tests that get_features integrates with compute correctly
def test_feature_service_aggregates_multiple_features(mocker):
    mocker.patch(
        "feature_pipeline.service.compute",
        side_effect=lambda feature_name, entity_id: {"name": feature_name, "value": hash(entity_id) % 10}
    )
    service = FeatureService()
    result = service.get_features("user-1", feature_names=["age", "income"])
    assert len(result) == 2
    assert {f["name"] for f in result} == {"age", "income"}
```
