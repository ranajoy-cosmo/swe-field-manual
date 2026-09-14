# Layered Architecture

Software rots when dependencies point in the wrong direction. A change to a database schema should not force a rewrite of business logic. A layered architecture (often implemented as Ports and Adapters or Hexagonal Architecture) enforces a strict dependency rule to protect the core domain.

## The Dependency Rule

The dependency rule states that source code dependencies must point inward, toward higher-level policies. Inner layers must not know anything about outer layers.

The three primary layers:
1. **Domain (Inner)**: Business logic, entities, and domain rules. Has no dependencies on the outside world.
2. **Presentation (Outer)**: HTTP endpoints (FastAPI), CLI commands, or message consumers. Depends on the Domain.
3. **Infrastructure (Outer)**: Database access (SQLAlchemy), cache (Redis), or external API clients. Depends on the Domain (by implementing interfaces defined by the Domain).

## Concrete Python Structure

A typical project structure enforces these boundaries through the filesystem:

```text
src/
└── feature_pipeline/
    ├── api/                # Presentation layer (FastAPI)
    ├── domain/             # Domain layer (Entities, rules, interfaces)
    └── infrastructure/     # Infrastructure layer (SQLAlchemy, Redis)
```

## The Domain Layer is Framework-Agnostic

The domain layer must remain pure. It should contain no imports from `fastapi`, `sqlalchemy`, or `redis`. 

```python
# src/feature_pipeline/domain/models.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class FeatureSet:
    id: str
    name: str
    created_at: datetime
    
    def is_stale(self, max_age_hours: int) -> bool:
        age = datetime.utcnow() - self.created_at
        return age.total_seconds() > (max_age_hours * 3600)
```

## Ports and Adapters (Hexagonal)

The domain defines what it needs from the outside world using interfaces (**Ports**). The infrastructure layer implements those interfaces (**Adapters**). In Python, Ports are typically defined using `typing.Protocol`.

```python
# src/feature_pipeline/domain/ports.py
from typing import Protocol
from .models import FeatureSet

class FeatureStore(Protocol):
    def get_feature_set(self, feature_id: str) -> FeatureSet | None:
        """Retrieve a feature set by ID."""
        ...
    
    def save_feature_set(self, feature_set: FeatureSet) -> None:
        """Persist a feature set."""
        ...
```

The infrastructure layer implements the `FeatureStore` port:

```python
# src/feature_pipeline/infrastructure/redis_store.py
import json
from datetime import datetime
import redis
from feature_pipeline.domain.ports import FeatureStore
from feature_pipeline.domain.models import FeatureSet

class RedisFeatureStore:
    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def get_feature_set(self, feature_id: str) -> FeatureSet | None:
        data = self._client.get(f"feature:{feature_id}")
        if not data:
            return None
        parsed = json.loads(data)
        return FeatureSet(
            id=parsed["id"],
            name=parsed["name"],
            created_at=datetime.fromisoformat(parsed["created_at"])
        )

    def save_feature_set(self, feature_set: FeatureSet) -> None:
        data = {
            "id": feature_set.id,
            "name": feature_set.name,
            "created_at": feature_set.created_at.isoformat()
        }
        self._client.set(f"feature:{feature_set.id}", json.dumps(data))
```

## Anti-Pattern: Fat Route Handlers

Placing business logic directly in the FastAPI route handler couples the presentation layer to the domain and infrastructure simultaneously.

> [!WARNING]
> **Anti-pattern:** The fat route handler. This code cannot be tested without making HTTP requests, and the business rule cannot be reused in a CLI or background task.

```python
# BAD: Fat route handler
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from .database import get_db

router = APIRouter()

@router.post("/features/")
def create_feature(name: str, db: Session = Depends(get_db)):
    # Infrastructure, domain, and presentation all mixed together
    if len(name) < 3:
        raise HTTPException(status_code=400, detail="Name too short")
    
    existing = db.execute("SELECT * FROM features WHERE name = :name", {"name": name}).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Feature exists")
        
    db.execute(
        "INSERT INTO features (name, created_at) VALUES (:name, :created)",
        {"name": name, "created": datetime.utcnow()}
    )
    db.commit()
    return {"status": "created"}
```

## Summary

| Decision | Recommendation | Reason |
|----------|----------------|--------|
| Project Structure | `src/api`, `src/domain`, `src/infra` | Enforces boundaries natively in the import path. |
| Interface Definition | `typing.Protocol` | Provides structural subtyping without forcing infrastructure classes to inherit from domain base classes. |
| Business Logic | Confined to the Domain layer | Allows testing logic without HTTP clients or databases; permits reuse across entrypoints. |
