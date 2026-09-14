# Dependency Injection

Global state and module-level singletons make code difficult to test and reason about. Dependency Injection (DI) resolves this by passing dependencies into objects or functions rather than having them instantiate or import their dependencies directly.

## Manual DI (Constructor Injection)

The simplest and most robust form of DI is constructor injection. Pass dependencies as arguments when initializing a class.

```python
# src/feature_pipeline/domain/services.py
from .ports import FeatureStore

class FeatureService:
    # FeatureStore is passed in, not instantiated here
    def __init__(self, store: FeatureStore) -> None:
        self._store = store

    def compute_and_save(self, feature_id: str, data: dict[str, float]) -> None:
        # Business logic using the injected dependency
        pass
```

Testing this service requires no mocking libraries, only a fake implementation of the `FeatureStore` port:

```python
# tests/test_services.py
from feature_pipeline.domain.services import FeatureService
from feature_pipeline.domain.models import FeatureSet

class FakeFeatureStore:
    def __init__(self) -> None:
        self.features: dict[str, FeatureSet] = {}
        
    def get_feature_set(self, feature_id: str) -> FeatureSet | None:
        return self.features.get(feature_id)
        
    def save_feature_set(self, feature_set: FeatureSet) -> None:
        self.features[feature_set.id] = feature_set

def test_feature_service():
    store = FakeFeatureStore()
    service = FeatureService(store)
    # Test service behavior safely and deterministically
```

## FastAPI's `Depends()`

For the web layer, FastAPI provides a powerful DI container via `Depends()`. This is ideal for request-scoped dependencies like database sessions or authenticated users.

```python
# src/feature_pipeline/api/dependencies.py
from typing import Generator
import redis
from fastapi import Depends
from feature_pipeline.infrastructure.redis_store import RedisFeatureStore
from feature_pipeline.domain.services import FeatureService

def get_redis_client() -> Generator[redis.Redis, None, None]:
    client = redis.Redis(host='localhost', port=6379)
    try:
        yield client
    finally:
        client.close()

def get_feature_service(
    client: redis.Redis = Depends(get_redis_client)
) -> FeatureService:
    store = RedisFeatureStore(client)
    return FeatureService(store)
```

The route handler simply requests the service:

```python
# src/feature_pipeline/api/routes.py
from fastapi import APIRouter, Depends
from .dependencies import get_feature_service
from feature_pipeline.domain.services import FeatureService

router = APIRouter()

@router.post("/features/{feature_id}")
def trigger_compute(
    feature_id: str,
    service: FeatureService = Depends(get_feature_service)
) -> dict[str, str]:
    service.compute_and_save(feature_id, {"val": 1.0})
    return {"status": "computing"}
```

## Application-Level DI: `dependency-injector`

For complex applications (especially those with CLI or background worker entrypoints in addition to FastAPI), manual DI setup becomes tedious. `dependency-injector` provides a robust, Pythonic IoC container.

```bash
uv add dependency-injector
```

```python
# src/feature_pipeline/containers.py
from dependency_injector import containers, providers
import redis
from .infrastructure.redis_store import RedisFeatureStore
from .domain.services import FeatureService

class Container(containers.DeclarativeContainer):
    config = providers.Configuration()
    
    redis_client = providers.Resource(
        redis.Redis,
        host=config.redis.host,
        port=config.redis.port,
    )
    
    feature_store = providers.Factory(
        RedisFeatureStore,
        client=redis_client
    )
    
    feature_service = providers.Factory(
        FeatureService,
        store=feature_store
    )
```

## Anti-Pattern: The Service Locator

A Service Locator is a pattern where an object requests its dependencies from a central registry rather than having them injected. It hides the object's true dependencies and makes testing difficult.

> [!WARNING]
> **Anti-pattern:** The Service Locator. The `FeatureService`'s dependency on the database is hidden inside the method implementation.

```python
# BAD: Service Locator pattern
from .registry import get_service

class FeatureService:
    def compute(self) -> None:
        # Hides dependencies. What does this method actually require to run?
        db = get_service("database") 
        db.query(...)
```

## Summary

| Decision | Recommendation | Reason |
|----------|----------------|--------|
| Unit Testing DI | Manual constructor injection + Fakes | Simplest, fastest, requires zero mocking magic. |
| Web Layer DI | FastAPI `Depends()` | Native to the framework, handles request lifecycle properly. |
| Application DI | `dependency-injector` | Scales to dozens of dependencies, handles configuration securely, usable across CLI/Web/Workers. |
| Object construction | Avoid Service Locators | Dependencies should be explicit in the constructor signature, not hidden in method bodies. |
