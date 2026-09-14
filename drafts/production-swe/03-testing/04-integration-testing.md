# 04 — Integration Testing

## Why Integration Tests Exist

Unit tests verify that each piece works in isolation. Integration tests verify that the pieces work together *and* that your assumptions about external systems are correct.

The wiring between components is where a surprising proportion of production bugs live:
- The SQL query you wrote returns rows in a different order than your code assumes
- The Redis key you set with TTL=300 expires before the cache-aside logic reads it
- The HTTP response your mock returns doesn't match what the real API actually sends
- The Pydantic model you validated doesn't match the actual database schema

Integration tests catch these by using *real infrastructure* — a real database, a real cache, a real message queue — but in an isolated, controlled environment (typically Docker containers started per test session).

---

## 1. The Infrastructure Principle

The right infrastructure for integration tests:

| Requirement | Approach |
|-------------|----------|
| Real behavior | Actual database/cache engine, not an in-memory shim |
| Isolation | Fresh state per test (or per test class) |
| Speed | Session-scoped containers (start once, reuse across tests) |
| Portability | Docker — same environment locally and in CI |
| Cleanup | Automatic container teardown via pytest fixtures |

---

## 2. `testcontainers` — Real Infrastructure in Fixtures

`testcontainers` starts Docker containers programmatically inside pytest fixtures. The container lifecycle is tied to the fixture scope.

```bash
uv add --dev testcontainers
```

### Redis Container

```python
# tests/integration/conftest.py
import pytest
import redis
from testcontainers.redis import RedisContainer

@pytest.fixture(scope="session")
def redis_container():
    """Start a Redis container once for the entire test session."""
    with RedisContainer("redis:7-alpine") as container:
        yield container
    # Container stops and is removed here

@pytest.fixture(scope="session")
def redis_client(redis_container):
    """A Redis client connected to the test container."""
    client = redis.Redis(
        host=redis_container.get_container_host_ip(),
        port=redis_container.get_exposed_port(6379),
        decode_responses=True,
    )
    return client

@pytest.fixture(autouse=True)
def flush_redis(redis_client):
    """Flush Redis before each test to ensure isolation."""
    yield
    redis_client.flushall()
```

### PostgreSQL Container

```python
# tests/integration/conftest.py
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer
from feature_pipeline.db import Base

@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container

@pytest.fixture(scope="session")
def db_engine(pg_container):
    """Create the schema once; reuse the engine across the session."""
    engine = create_engine(pg_container.get_connection_url())
    Base.metadata.create_all(engine)
    return engine

@pytest.fixture
def db_session(db_engine):
    """Provide a transactional session that rolls back after each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    
    yield session
    
    session.close()
    transaction.rollback()   # rollback ensures test isolation without truncating tables
    connection.close()
```

The rollback pattern is crucial: each test runs inside a transaction that is rolled back, leaving the schema intact but removing all data changes. This is much faster than `TRUNCATE` and avoids sequence resets.

### GCS / S3 with Fake Implementations

For cloud storage, use `fake-gcs-server` or `moto` (for AWS S3):

```bash
uv add --dev moto[s3]
```

```python
import boto3
import pytest
from moto import mock_aws

@pytest.fixture
def s3_bucket():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-features")
        yield s3, "test-features"

def test_pipeline_writes_features_to_s3(s3_bucket, pipeline):
    s3_client, bucket_name = s3_bucket
    
    pipeline = FeaturePipeline(storage_backend=S3Backend(bucket=bucket_name))
    pipeline.run(entity_ids=["user-1", "user-2"])
    
    objects = s3_client.list_objects_v2(Bucket=bucket_name)["Contents"]
    assert len(objects) == 2
    assert any(obj["Key"].startswith("features/user-1/") for obj in objects)
```

---

## 3. Testing Database Queries

Integration tests for database interactions verify that your queries do what you think they do — including edge cases in SQL that in-memory fakes won't catch.

```python
# tests/integration/test_feature_repository.py
import pytest
from datetime import datetime, timedelta
from feature_pipeline.repositories import FeatureRepository
from feature_pipeline.models import FeatureRecord

@pytest.mark.integration
class TestFeatureRepository:
    
    def test_save_and_retrieve_feature(self, db_session):
        repo = FeatureRepository(session=db_session)
        record = FeatureRecord(
            entity_id="user-123",
            feature_name="purchase_count",
            value=5.0,
            computed_at=datetime.utcnow(),
        )
        
        repo.save(record)
        retrieved = repo.get(entity_id="user-123", feature_name="purchase_count")
        
        assert retrieved is not None
        assert retrieved.value == pytest.approx(5.0)

    def test_get_latest_returns_most_recent(self, db_session):
        repo = FeatureRepository(session=db_session)
        now = datetime.utcnow()
        
        # Insert two records for the same entity+feature at different times
        for i, offset in enumerate([timedelta(hours=2), timedelta(hours=1)]):
            repo.save(FeatureRecord(
                entity_id="user-123",
                feature_name="age_normalized",
                value=float(i),
                computed_at=now - offset,
            ))
        
        latest = repo.get_latest(entity_id="user-123", feature_name="age_normalized")
        assert latest.value == pytest.approx(1.0)   # most recent record (1 hour ago)

    def test_bulk_save_is_transactional(self, db_session):
        repo = FeatureRepository(session=db_session)
        records = [
            FeatureRecord(entity_id="user-1", feature_name="age", value=0.3),
            FeatureRecord(entity_id="user-2", feature_name="age", value=None),  # invalid
            FeatureRecord(entity_id="user-3", feature_name="age", value=0.7),
        ]
        
        with pytest.raises(ValueError, match="value must not be None"):
            repo.bulk_save(records)
        
        # All-or-nothing: none of the records should be persisted
        assert repo.count(feature_name="age") == 0

    def test_query_returns_empty_for_missing_entity(self, db_session):
        repo = FeatureRepository(session=db_session)
        result = repo.get(entity_id="nonexistent", feature_name="age")
        assert result is None
```

---

## 4. Testing the Full API Stack

Integration tests for an HTTP API test the full request-response cycle through your routing, middleware, validation, business logic, and storage layers. Use FastAPI's `TestClient` or `AsyncClient`.

```python
# tests/integration/test_api.py
import pytest
from fastapi.testclient import TestClient
from feature_pipeline.app import create_app
from feature_pipeline.dependencies import get_feature_store

@pytest.fixture(scope="module")
def app(redis_client):
    """Create the FastAPI app wired to the test Redis instance."""
    feature_store = RedisFeatureStore(client=redis_client)
    application = create_app()
    application.dependency_overrides[get_feature_store] = lambda: feature_store
    return application

@pytest.fixture(scope="module")
def client(app):
    return TestClient(app)

@pytest.mark.integration
class TestFeatureServingAPI:
    
    def test_get_features_returns_200_for_existing_entity(self, client, seeded_features):
        response = client.get("/v1/features/user-123")
        assert response.status_code == 200
        data = response.json()
        assert data["entity_id"] == "user-123"
        assert isinstance(data["features"], dict)

    def test_get_features_returns_404_for_missing_entity(self, client):
        response = client.get("/v1/features/nonexistent-user")
        assert response.status_code == 404
        assert response.json()["error"] == "entity_not_found"

    def test_batch_get_features_returns_partial_results_on_missing(self, client, seeded_features):
        response = client.post(
            "/v1/features/batch",
            json={"entity_ids": ["user-123", "user-999"]},  # one exists, one doesn't
        )
        assert response.status_code == 200
        data = response.json()
        assert data["found"] == 1
        assert data["missing"] == 1
        assert data["missing_ids"] == ["user-999"]

    def test_get_features_validates_entity_id_format(self, client):
        response = client.get("/v1/features/invalid entity id!")
        assert response.status_code == 422   # Unprocessable Entity

    def test_health_endpoint_returns_200_when_healthy(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
```

### Dependency Override Pattern

The `dependency_overrides` pattern is the correct way to swap infrastructure in FastAPI integration tests. It doesn't require patching — it replaces the dependency at the DI level.

```python
# In production:
def get_feature_store() -> FeatureStore:
    return RedisFeatureStore(host=settings.redis_host)

# In tests:
def get_test_feature_store() -> FeatureStore:
    return RedisFeatureStore(client=test_redis_client)

app.dependency_overrides[get_feature_store] = get_test_feature_store
```

---

## 5. Testing Message Queues

For services that consume from or publish to message queues (Kafka, Pub/Sub, SQS), use containerized brokers:

```bash
uv add --dev testcontainers  # includes KafkaContainer
```

```python
# tests/integration/conftest.py
from testcontainers.kafka import KafkaContainer

@pytest.fixture(scope="session")
def kafka_container():
    with KafkaContainer("confluentinc/cp-kafka:7.5.0") as container:
        yield container

@pytest.fixture(scope="session")
def kafka_bootstrap_servers(kafka_container):
    return kafka_container.get_bootstrap_server()
```

```python
# tests/integration/test_feature_consumer.py
from kafka import KafkaProducer, KafkaConsumer
import json, time, pytest

@pytest.mark.integration
def test_consumer_processes_feature_update_event(kafka_bootstrap_servers):
    topic = "feature-updates"
    
    # Publish a test event
    producer = KafkaProducer(
        bootstrap_servers=kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode(),
    )
    producer.send(topic, {"entity_id": "user-123", "feature": "age", "value": 0.5})
    producer.flush()
    
    # Start the consumer and wait for processing
    consumer = FeatureUpdateConsumer(bootstrap_servers=kafka_bootstrap_servers)
    consumer.start(timeout_ms=5000)
    
    # Verify the feature was stored
    assert feature_store.get("user-123:age") == pytest.approx(0.5)
```

---

## 6. Isolation Strategies

When integration tests share infrastructure (session-scoped containers), isolation between tests is critical:

### Strategy 1: Transaction Rollback (PostgreSQL)

*(Shown above in the DB session fixture — the rollback pattern)*

### Strategy 2: Unique Prefixes (Redis, Kafka)

```python
import uuid

@pytest.fixture
def test_namespace():
    """Unique prefix for this test's keys — prevents cross-test pollution."""
    return f"test:{uuid.uuid4().hex[:8]}"

def test_feature_expiry(redis_client, test_namespace):
    key = f"{test_namespace}:user-123:age"
    redis_client.setex(key, 1, "0.5")  # TTL = 1 second
    
    time.sleep(1.1)
    assert redis_client.get(key) is None
```

### Strategy 3: `autouse` Cleanup Fixtures

```python
@pytest.fixture(autouse=True)
def clean_feature_store(redis_client):
    """Flush after every test automatically."""
    yield
    redis_client.flushall()
```

Use `autouse=True` carefully — it affects every test in scope. Prefer `scope="function"` autouse fixtures for per-test cleanup.

---

## 7. Marking and Selecting Integration Tests

Integration tests are slower and require Docker. Never run them as part of the default local test run.

```python
# Decorator on the test or class
@pytest.mark.integration
class TestFeatureRepository:
    ...
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = ["integration: Requires Docker infrastructure"]
```

```bash
# Local development: run only fast tests
pytest tests/unit/

# CI: run everything
pytest tests/ -m "unit or integration"

# Integration only
pytest tests/integration/ -m integration
```

Or configure the default to exclude integration:

```toml
[tool.pytest.ini_options]
addopts = ["-m", "not integration"]  # default: skip integration
```

Then in CI, override:

```yaml
- run: pytest tests/ -m "unit or integration"
```
