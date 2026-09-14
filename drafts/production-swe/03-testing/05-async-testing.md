# 05 — Async Testing

## Why Async Testing Needs Special Handling

Standard pytest runs tests synchronously. An `async def` test function is just a coroutine object — pytest doesn't know how to run it. You need `pytest-asyncio` to:

1. Run async test functions inside an event loop
2. Support async fixtures
3. Handle async context managers and generators

```bash
uv add --dev pytest-asyncio
```

---

## 1. Configuration

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"    # automatically handle all async tests and fixtures
                          # alternative: "strict" (requires explicit @pytest.mark.asyncio)
```

`asyncio_mode = "auto"` is the recommended setting for codebases with significant async code. It removes the need to decorate every async test individually.

---

## 2. Basic Async Tests

```python
# With asyncio_mode = "auto" — no decorator needed
async def test_async_feature_store_get():
    store = AsyncRedisFeatureStore(host="localhost")
    await store.set("user-123", {"age": 0.5})
    
    result = await store.get("user-123")
    assert result == {"age": 0.5}

# With asyncio_mode = "strict" — requires explicit decoration
@pytest.mark.asyncio
async def test_async_feature_store_get():
    ...
```

---

## 3. Async Fixtures

Fixtures can be `async def` too. They follow the same `yield` pattern:

```python
# tests/conftest.py
import pytest_asyncio
import pytest

@pytest_asyncio.fixture(scope="session")
async def async_redis_client(redis_container):
    """Session-scoped async Redis client."""
    import aioredis
    client = await aioredis.create_redis_pool(
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}"
    )
    yield client
    client.close()
    await client.wait_closed()

@pytest_asyncio.fixture
async def clean_async_store(async_redis_client):
    """Async feature store, flushed after each test."""
    store = AsyncFeatureStore(redis=async_redis_client)
    yield store
    await async_redis_client.flushall()
```

---

## 4. Testing FastAPI Async Routes

FastAPI is async-first. Use `httpx.AsyncClient` with `asgi_transport` for proper async testing:

```python
# tests/integration/test_async_api.py
import pytest
import httpx
from fastapi import FastAPI
from feature_pipeline.app import create_app

@pytest_asyncio.fixture(scope="module")
async def async_client(app: FastAPI):
    """Async HTTP client for the FastAPI app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

async def test_get_features_returns_correct_structure(async_client, seeded_features):
    response = await async_client.get("/v1/features/user-123")
    assert response.status_code == 200
    data = response.json()
    assert "entity_id" in data
    assert "features" in data

async def test_concurrent_requests_are_handled_correctly(async_client, seeded_features):
    """Verify the server handles concurrent requests without race conditions."""
    import asyncio
    
    entity_ids = [f"user-{i}" for i in range(10)]
    tasks = [async_client.get(f"/v1/features/{eid}") for eid in entity_ids]
    
    responses = await asyncio.gather(*tasks)
    
    assert all(r.status_code in {200, 404} for r in responses)
```

---

## 5. Testing Async Workers and Background Tasks

For async services that process tasks from a queue or run background loops:

```python
async def test_background_worker_processes_messages(
    async_redis_client, feature_store
):
    """Test that the background worker consumes and processes messages."""
    worker = FeatureComputeWorker(
        redis=async_redis_client,
        feature_store=feature_store,
        queue_name="feature-jobs",
    )
    
    # Push a job onto the queue
    await async_redis_client.lpush(
        "feature-jobs",
        json.dumps({"entity_id": "user-123", "features": ["age", "income"]}),
    )
    
    # Run worker for one iteration
    await worker.process_one()
    
    # Verify the feature was computed and stored
    result = await feature_store.get("user-123")
    assert result is not None
    assert "age" in result
```

### Testing with Timeouts

Async tests can hang if a coroutine never completes. Use `asyncio.wait_for`:

```python
import asyncio

async def test_worker_does_not_block_on_empty_queue(async_worker):
    """Worker should return quickly when queue is empty, not block indefinitely."""
    try:
        await asyncio.wait_for(async_worker.process_one(), timeout=1.0)
    except asyncio.TimeoutError:
        pytest.fail("Worker blocked for more than 1 second on empty queue")
```

Or use `pytest-timeout`:

```bash
uv add --dev pytest-timeout
```

```python
@pytest.mark.timeout(5)  # fail test if it runs longer than 5 seconds
async def test_worker_processes_message_within_sla(async_worker, message_queue):
    await message_queue.push(test_message)
    await async_worker.process_one()
    ...
```

---

## 6. Async Mocking

`AsyncMock` (stdlib since Python 3.8) mocks async functions. `pytest-mock` wraps it seamlessly:

```python
async def test_pipeline_retries_on_async_timeout(mocker):
    mock_store = AsyncMock(spec=AsyncFeatureStore)
    mock_store.get.side_effect = [
        asyncio.TimeoutError(),   # first call times out
        {"age": 0.5},             # second call succeeds
    ]
    
    pipeline = AsyncFeaturePipeline(store=mock_store)
    result = await pipeline.get_with_retry("user-123", max_retries=2)
    
    assert result == {"age": 0.5}
    assert mock_store.get.call_count == 2

async def test_pipeline_raises_after_max_retries_exceeded(mocker):
    mock_store = AsyncMock(spec=AsyncFeatureStore)
    mock_store.get.side_effect = asyncio.TimeoutError()
    
    pipeline = AsyncFeaturePipeline(store=mock_store, max_retries=3)
    
    with pytest.raises(InfrastructureError, match="Max retries exceeded"):
        await pipeline.get_with_retry("user-123")
    
    assert mock_store.get.call_count == 3
```

---

## 7. Event Loop Scope

A subtle but important configuration: the event loop scope must match the fixture scope.

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
# In pytest-asyncio >= 0.23:
asyncio_default_fixture_loop_scope = "session"
```

If a session-scoped async fixture shares a loop with function-scoped tests, you need a session-scoped loop. Without this, you may see `Event loop is closed` errors on the second test that uses a session-scoped async fixture.

```python
# Explicit loop scope for session fixtures
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def session_level_resource():
    async with SomeAsyncContextManager() as resource:
        yield resource
```

---

## Summary

| Concern | Solution |
|---------|---------|
| Running async tests | `pytest-asyncio` + `asyncio_mode = "auto"` |
| Async fixtures | `@pytest_asyncio.fixture` |
| Testing FastAPI async routes | `httpx.AsyncClient` + `ASGITransport` |
| Async mocks | `AsyncMock` (stdlib) via `mocker` |
| Preventing test hangs | `asyncio.wait_for()` or `@pytest.mark.timeout` |
| Session-scoped async fixtures | Match loop scope: `loop_scope="session"` |
