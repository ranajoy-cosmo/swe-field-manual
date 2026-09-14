# Event-Driven Architecture

Systems that directly call each other via synchronous HTTP/RPC calls become tightly coupled. If the prediction service calls the notification service to send an email, a failure in the notification service breaks the prediction service. Event-Driven Architecture (EDA) decouples these systems by having components publish events that others subscribe to.

## Domain Events

A Domain Event is a record of something that has happened in the system. It should be named in the past tense (e.g., `ModelDeployed`, `FeatureSetComputed`).

```python
# src/feature_pipeline/domain/events.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Event:
    pass

@dataclass
class ModelDeployed(Event):
    model_id: str
    version: str
    deployed_at: datetime
    deployed_by: str
```

## Synchronous In-Process Event Bus

Before reaching for Kafka or RabbitMQ, an in-memory event bus is the best way to decouple modules within a single monolithic application.

```python
# src/feature_pipeline/domain/messagebus.py
from typing import Callable, Type
from .events import Event, ModelDeployed

# Type alias for a handler function
Handler = Callable[[Event], None]

class MessageBus:
    def __init__(self) -> None:
        self._handlers: dict[Type[Event], list[Handler]] = {}

    def subscribe(self, event_type: Type[Event], handler: Handler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def publish(self, event: Event) -> None:
        for handler in self._handlers.get(type(event), []):
            handler(event)
```

Usage:

```python
# Setup during app initialization
bus = MessageBus()

def notify_slack(event: Event) -> None:
    if isinstance(event, ModelDeployed):
        print(f"Sending Slack alert: Model {event.model_id} deployed.")

bus.subscribe(ModelDeployed, notify_slack)

# Inside a service
bus.publish(ModelDeployed(
    model_id="fraud-detector", 
    version="v2", 
    deployed_at=datetime.utcnow(), 
    deployed_by="system"
))
```

## The Transactional Outbox Pattern

A common EDA failure mode is "dual writes": writing to the database and publishing to a message broker (like Kafka). If the database commits but the Kafka publish fails, the system is inconsistent.

The Outbox Pattern solves this by writing the event to an `outbox` table in the *same database transaction* as the entity update. A separate background worker then reads the outbox table and publishes to Kafka.

```python
# src/feature_pipeline/domain/services.py
def deploy_model(version_id: str, uow: UnitOfWork) -> None:
    with uow:
        model = uow.models.get(version_id)
        model.status = "deployed"
        
        # 1. Update the entity
        uow.models.update(model)
        
        # 2. Save the event in the outbox in the SAME transaction
        event = ModelDeployed(model_id=model.id, ...)
        uow.outbox.add(event)
        
        # 3. Commit both safely
        uow.commit() 
```

## Event Sourcing

In a traditional CRUD system, the database stores the current state. In Event Sourcing, the database stores a sequence of domain events. The current state is derived by replaying the events.

> [!WARNING]
> **Anti-pattern:** Defaulting to Event Sourcing. It introduces immense complexity (event versioning, snapshotting, eventual consistency). Only use it for systems where the audit log is the core feature (e.g., banking ledgers, cart abandonment analysis).

## CQRS (Command Query Responsibility Segregation)

CQRS splits the system into two sides:
- **Commands**: Change state, return nothing (or just an ID/status).
- **Queries**: Read state, do not modify it.

This pairs well with Event-Driven Architecture, as the read models can be updated asynchronously by listening to events emitted by the command side.

```python
# Command side (writes)
@router.post("/models/{id}/deploy")
def deploy(id: str, service: ModelService = Depends(...)):
    service.deploy(id) # Returns 202 Accepted
    
# Query side (reads)
@router.get("/models/active")
def get_active(db: Session = Depends(...)):
    # Can query a heavily denormalized, fast read-replica
    return db.execute("SELECT * FROM active_models_view").fetchall()
```

## Summary

| Decision | Recommendation | Reason |
|----------|----------------|--------|
| Decoupling modules | In-memory message bus | Prevents direct imports between domains without the overhead of Kafka. |
| Reliable publishing | Transactional Outbox | Prevents data loss during network failures when dual-writing to DB and broker. |
| Event Sourcing | Avoid unless required | The complexity tax is rarely worth it for standard ML infrastructure apps. |
| Read/Write scaling | CQRS | Allows optimizing read models independently of the transactional write models. |
