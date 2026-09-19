# The Repository Pattern

The Repository pattern mediates between the domain and data mapping layers using a collection-like interface for accessing domain objects. It encapsulates the logic required to access data sources.

## Repository Abstraction

Repositories should be defined as `typing.Protocol` in the domain layer. The domain speaks in terms of entities, not database rows.

```python
# src/feature_pipeline/domain/ports.py
from typing import Protocol
from .models import ModelVersion

class ModelRepository(Protocol):
    def add(self, model: ModelVersion) -> None:
        ...
        
    def get(self, version_id: str) -> ModelVersion | None:
        ...
```

The infrastructure layer provides the SQLAlchemy implementation:

```python
# src/feature_pipeline/infrastructure/repositories.py
from sqlalchemy.orm import Session
from feature_pipeline.domain.ports import ModelRepository
from feature_pipeline.domain.models import ModelVersion
from .orm import ModelVersionORM

class SqlAlchemyModelRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        
    def add(self, model: ModelVersion) -> None:
        # Convert Domain model to ORM model
        orm_model = ModelVersionORM(
            id=model.id,
            name=model.name,
            hyperparameters=model.hyperparameters
        )
        self.session.add(orm_model)
        
    def get(self, version_id: str) -> ModelVersion | None:
        orm_model = self.session.query(ModelVersionORM).filter_by(id=version_id).first()
        if not orm_model:
            return None
        # Convert ORM model to Domain model
        return ModelVersion(
            id=orm_model.id,
            name=orm_model.name,
            hyperparameters=orm_model.hyperparameters
        )
```

## Unit of Work Pattern

The Repository pattern handles accessing data, but the Unit of Work (UoW) pattern handles atomic transactions. A UoW coordinates multiple repositories within a single database transaction.

```python
# src/feature_pipeline/domain/ports.py
from typing import Protocol, ContextManager
from .models import ModelVersion

class UnitOfWork(Protocol, ContextManager):
    models: ModelRepository
    
    def commit(self) -> None:
        ...
        
    def rollback(self) -> None:
        ...
```

Usage in a service:

```python
# src/feature_pipeline/domain/services.py
from .ports import UnitOfWork
from .models import ModelVersion

def promote_model(version_id: str, uow: UnitOfWork) -> None:
    with uow:
        model = uow.models.get(version_id)
        if not model:
            raise ValueError("Model not found")
            
        model.promote_to_production()
        uow.models.add(model) # Ensure tracked
        uow.commit() # Atomic save
```

## Testing Repositories

Because the Repository pattern uses protocols, we can use an in-memory fake for fast unit testing of the domain layer, and integration tests for the SQLAlchemy implementation.

```python
# tests/fakes.py
from feature_pipeline.domain.ports import ModelRepository
from feature_pipeline.domain.models import ModelVersion

class FakeModelRepository:
    def __init__(self) -> None:
        self._models: dict[str, ModelVersion] = {}
        
    def add(self, model: ModelVersion) -> None:
        self._models[model.id] = model
        
    def get(self, version_id: str) -> ModelVersion | None:
        return self._models.get(version_id)
```

## Over-Engineering vs. Value

The Repository pattern introduces overhead (converting between domain models and ORM models). 

> [!TIP]
> **When to use Repository:** When business logic is complex, testing speed is critical, or you may swap storage backends (e.g., migrating from MongoDB to PostgreSQL).
>
> **When NOT to use Repository:** For simple CRUD applications where the database schema maps 1:1 to API responses. In these cases, using SQLAlchemy ORM models directly is perfectly fine.

## Summary

| Decision | Recommendation | Reason |
|----------|----------------|--------|
| Pattern choice | Protocol + Implementation | Decouples domain from database, enabling fast in-memory tests via Fakes. |
| Transaction management | Unit of Work | Groups repository operations into atomic commits, centralizing connection handling. |
| Conversion overhead | Map at boundary | Convert ORM objects to Domain dataclasses within the repository so the Domain never sees SQLAlchemy. |
