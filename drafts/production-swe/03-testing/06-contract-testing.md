# 06 — Contract Testing

## The Service Boundary Problem

Integration tests verify that your service works. But what verifies that *two services agree on each other's interface*?

In a microservices architecture, Service A (the consumer) makes HTTP calls to Service B (the provider). Both have their own test suites. But:

- Service A tests mock Service B's API — so they only verify behavior against a *fake*
- Service B tests verify its own logic — but may not know exactly how Service A uses it
- Neither test catches the mismatch when Service B adds a new required field or changes a response shape

This mismatch is a **contract violation**. It goes undetected until A calls B in staging or production and gets a 422, a KeyError, or a silent data corruption.

**Contract testing** makes the agreement between producer and consumer explicit and machine-checkable.

---

## 1. Consumer-Driven Contract Testing (CDC)

The key insight of CDC: **the consumer defines the contract, not the provider.**

The consumer knows exactly which endpoints it calls, which fields it uses, and what responses it can handle. The provider doesn't know any of this — it just knows its own spec.

**The workflow:**

```
Consumer (Service A)                    Provider (Service B)
─────────────────────────────────────────────────────────────
1. Write consumer tests
   (what A sends, what A expects B to return)
         │
         ▼
2. Generate a "Pact" contract file
   (JSON describing the interaction)
         │
         └──────── publish to Pact Broker ──────────────▶
                                                         │
                                                         ▼
                                              3. Provider verifies contract
                                                 (run B against the pact)
                                                         │
                                                         ▼
                                              4. Mark as verified in broker
                                                 CI can deploy A safely
```

---

## 2. Pact — The Standard Tool

```bash
uv add --dev pact-python
```

### Writing the Consumer Test (Service A)

```python
# tests/contract/test_feature_service_consumer.py
"""
Contract test: how feature-pipeline (consumer) calls user-service (provider).

This test defines EXACTLY what feature-pipeline sends and expects from user-service.
It generates a Pact contract file that user-service must verify.
"""
import pytest
from pact import Consumer, Provider, Like, EachLike, Term

PACT_MOCK_HOST = "localhost"
PACT_MOCK_PORT = 1234
PACT_DIR = "tests/contract/pacts"

@pytest.fixture(scope="module")
def pact():
    """Set up Pact consumer/provider and mock server."""
    pact = Consumer("feature-pipeline").has_pact_with(
        Provider("user-service"),
        host_name=PACT_MOCK_HOST,
        port=PACT_MOCK_PORT,
        pact_dir=PACT_DIR,
        log_dir="logs/pact",
    )
    pact.start_service()
    yield pact
    pact.stop_service()

def test_get_user_profile_returns_expected_shape(pact):
    """
    When feature-pipeline calls GET /users/{user_id},
    it expects user-service to return a profile with at minimum:
    user_id (string), age (integer), segment (string).
    """
    expected_response = {
        "user_id": Like("user-123"),          # any string
        "age": Like(30),                       # any integer
        "segment": Term(
            r"(bronze|silver|gold|platinum)",  # must match regex
            "gold",                            # example value
        ),
        "is_active": Like(True),               # any boolean
    }
    
    (
        pact
        .given("user user-123 exists")
        .upon_receiving("a request for user profile")
        .with_request(
            method="GET",
            path="/api/v1/users/user-123",
            headers={"Accept": "application/json", "X-Service": "feature-pipeline"},
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=expected_response,
        )
    )
    
    with pact:
        # Call our real client code against the Pact mock server
        client = UserServiceClient(
            base_url=f"http://{PACT_MOCK_HOST}:{PACT_MOCK_PORT}"
        )
        profile = client.get_user_profile("user-123")
    
    # Verify our client parsed the response correctly
    assert profile.user_id == "user-123"
    assert isinstance(profile.age, int)
    assert profile.segment in {"bronze", "silver", "gold", "platinum"}

def test_get_user_profile_handles_404(pact):
    """When user doesn't exist, feature-pipeline expects a 404 with a specific error shape."""
    (
        pact
        .given("user nonexistent-user does not exist")
        .upon_receiving("a request for a nonexistent user profile")
        .with_request(
            method="GET",
            path="/api/v1/users/nonexistent-user",
        )
        .will_respond_with(
            status=404,
            body={"error": "user_not_found", "user_id": Like("nonexistent-user")},
        )
    )
    
    with pact:
        client = UserServiceClient(
            base_url=f"http://{PACT_MOCK_HOST}:{PACT_MOCK_PORT}"
        )
        with pytest.raises(UserNotFoundError):
            client.get_user_profile("nonexistent-user")

def test_get_user_batch_returns_list(pact):
    """Batch endpoint: feature-pipeline expects a list of profiles."""
    (
        pact
        .given("users user-1 and user-2 exist")
        .upon_receiving("a batch request for user profiles")
        .with_request(
            method="POST",
            path="/api/v1/users/batch",
            body={"user_ids": ["user-1", "user-2"]},
        )
        .will_respond_with(
            status=200,
            body={
                "profiles": EachLike(  # one or more items matching this shape
                    {"user_id": Like("user-1"), "age": Like(30), "segment": Like("gold")}
                ),
                "found": Like(2),
                "missing": Like(0),
            }
        )
    )
    
    with pact:
        client = UserServiceClient(base_url=f"http://{PACT_MOCK_HOST}:{PACT_MOCK_PORT}")
        result = client.get_user_batch(["user-1", "user-2"])
    
    assert len(result.profiles) >= 1
    assert result.found >= 1
```

After running this test, Pact writes a contract file:

```json
// tests/contract/pacts/feature-pipeline-user-service.json
{
  "consumer": {"name": "feature-pipeline"},
  "provider": {"name": "user-service"},
  "interactions": [
    {
      "description": "a request for user profile",
      "providerState": "user user-123 exists",
      "request": {
        "method": "GET",
        "path": "/api/v1/users/user-123"
      },
      "response": {
        "status": 200,
        "body": {"user_id": "user-123", "age": 30, "segment": "gold", "is_active": true},
        "matchingRules": {
          "$.body.user_id": {"match": "type"},
          "$.body.age": {"match": "type"},
          "$.body.segment": {"match": "regex", "regex": "(bronze|silver|gold|platinum)"}
        }
      }
    }
  ]
}
```

### Verifying on the Provider Side (Service B)

```python
# In user-service's test suite:
# tests/contract/test_user_service_provider.py
import pytest
from pact import Verifier
from user_service.app import create_app, db

def test_verify_feature_pipeline_contract():
    """
    Verify that user-service honors the contract defined by feature-pipeline.
    """
    verifier = Verifier(
        provider="user-service",
        provider_base_url="http://localhost:8001",
    )
    
    output, _ = verifier.verify_pacts(
        sources=["tests/contract/pacts/feature-pipeline-user-service.json"],
        provider_states_setup_url="http://localhost:8001/_pact/provider_states",
    )
    
    assert output == 0, "Provider verification failed — contract is broken"
```

The provider must implement a `provider_states` endpoint that sets up the state described in `given(...)`:

```python
# In user-service:
@app.post("/_pact/provider_states")
async def setup_provider_state(body: dict):
    state = body.get("state")
    
    if state == "user user-123 exists":
        # Create the test user in the database
        await db.execute(
            "INSERT INTO users (user_id, age, segment) VALUES (?, ?, ?)",
            ("user-123", 30, "gold"),
        )
    elif state == "user nonexistent-user does not exist":
        # Ensure the user doesn't exist
        await db.execute("DELETE FROM users WHERE user_id = ?", ("nonexistent-user",))
    
    return {"state": state, "params": body.get("params", {})}
```

---

## 3. Using a Pact Broker

In a multi-team org, use a Pact Broker to share contracts between teams:

```bash
# Self-hosted (Docker)
docker run -p 9292:9292 \
    -e PACT_BROKER_DATABASE_URL=sqlite:////tmp/pact_broker.sqlite \
    pactfoundation/pact-broker

# Or use PactFlow (SaaS — free tier available)
```

```python
# Consumer: publish contract to broker
pact = Consumer("feature-pipeline").has_pact_with(
    Provider("user-service"),
    broker_base_url="https://your-broker.pactflow.io",
    broker_token=os.getenv("PACT_BROKER_TOKEN"),
    publish_to_broker=True,
    version=os.getenv("GIT_SHA", "0.0.0"),  # tag by git SHA
    branch=os.getenv("GIT_BRANCH", "main"),
)
```

```python
# Provider: verify against broker
verifier = Verifier(provider="user-service", provider_base_url=APP_URL)
verifier.verify_with_broker(
    broker_url="https://your-broker.pactflow.io",
    broker_token=os.getenv("PACT_BROKER_TOKEN"),
    publish_verification_results=True,
    provider_version=os.getenv("GIT_SHA"),
    enable_pending=True,  # don't fail on unverified contracts from other consumers
)
```

---

## 4. A Simpler Alternative: Schema Snapshots

Full Pact setup has organizational overhead. For teams that own both sides of an interface, or for smaller projects, **schema snapshots** provide similar protection at lower cost.

### OpenAPI Schema Snapshots

If your provider has a FastAPI app, snapshot its OpenAPI schema:

```python
# tests/contract/test_api_schema_snapshot.py
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from feature_pipeline.app import create_app

SNAPSHOT_PATH = Path("tests/contract/snapshots/openapi_schema.json")

def test_openapi_schema_matches_snapshot(tmp_path):
    """The OpenAPI schema must not change unexpectedly."""
    client = TestClient(create_app())
    current_schema = client.get("/openapi.json").json()
    
    if not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.write_text(json.dumps(current_schema, indent=2))
        pytest.skip("Snapshot created — run again to verify")
    
    expected_schema = json.loads(SNAPSHOT_PATH.read_text())
    
    assert current_schema == expected_schema, (
        "API schema has changed. If intentional, update the snapshot:\n"
        f"  python -m pytest {__file__} --snapshot-update"
    )
```

This is simpler but less powerful — it catches any schema change, not just breaking ones.

### Pydantic Model Snapshots

For internal library APIs, snapshot the Pydantic model JSON schemas:

```python
# Serialize the model's schema as a snapshot
schema = TrainingConfig.model_json_schema()
snapshot_path = Path("tests/contract/snapshots/training_config_schema.json")

if snapshot_path.exists():
    expected = json.loads(snapshot_path.read_text())
    assert schema == expected, "TrainingConfig schema changed — update snapshot if intentional"
else:
    snapshot_path.write_text(json.dumps(schema, indent=2))
```

---

## Summary

| Approach | Best for | Overhead |
|----------|----------|---------|
| Full Pact + Broker | Multi-team, independently deployed services | High setup, high value |
| Pact without broker | Two teams, contract file checked into both repos | Medium |
| OpenAPI snapshot | Single team, FastAPI service | Low |
| Pydantic schema snapshot | Internal library API stability | Low |

> **The core value:** contract testing moves API compatibility failures from *production runtime* to *CI build time*, before any code is deployed. For services that change independently, this is not optional — it is the safety net that makes independent deployment safe.
