# 05 — Scaling and Stateless Design

## Why Statelessness Is a Production Property

A stateful service — one that stores any per-request data in memory between requests — cannot scale horizontally. The second instance doesn't share the first instance's memory. Load balancers route requests to instances at random; a user's session data may be on instance A while their next request lands on instance B.

The fix is not to add sticky sessions. Sticky sessions are a band-aid that re-introduces the single-instance ceiling: all requests for a user go to the same pod, so you can only scale by adding users, not by adding capacity for existing users.

The correct fix is to move all state out of the process.

This is Principle III of the Twelve-Factor App (processes must be stateless and share-nothing). The twelve-factor model is the canonical reference for building services that scale horizontally and operate without friction in container environments.

---

## 1. The Twelve-Factor App (Relevant Factors for Python Services)

The twelve factors most relevant to Kubernetes-deployed Python services:

| Factor | What it requires | Common violation |
|--------|-----------------|-----------------|
| **III: Processes** | Stateless, share-nothing processes | In-memory session cache, module-level request state |
| **IV: Backing services** | All persistence (DB, cache, queue) is an attached resource accessed via URL | Hardcoded hostnames, filesystem-based storage |
| **VII: Port binding** | Service is self-contained; exports HTTP via a port | Expecting a web server to be pre-installed |
| **IX: Disposability** | Fast startup, graceful shutdown; processes are disposable | Long startup sequences, abrupt shutdown drops in-flight requests |
| **X: Dev/prod parity** | Keep development and production as similar as possible | SQLite in dev, PostgreSQL in prod |
| **XI: Logs** | Treat logs as event streams; write to stdout | Writing to rotating log files |

The full twelve-factor spec: [https://12factor.net](https://12factor.net)

---

## 2. Horizontal vs. Vertical Scaling

| Strategy | How | Limits |
|----------|-----|--------|
| **Vertical (scale up)** | Larger machine (more CPU/RAM) | Hard ceiling at the largest available instance; single point of failure |
| **Horizontal (scale out)** | More instances of the same size | Theoretically unbounded; requires stateless processes |

For most Python ML services, horizontal scaling is correct:

- **Feature serving APIs**: IO-bound (cache hits, DB reads). Horizontal scaling directly increases throughput.
- **Online inference APIs**: CPU or GPU bound per request. Adding replicas adds parallelism.
- **Batch workers**: trivially parallelizable by adding more consumer pods reading from the same queue.

The one exception: a service that holds a large model in GPU memory. Vertical scaling (larger GPU) is sometimes necessary because the model doesn't fit on smaller GPUs. But the serving layer above it (the HTTP API) should still be horizontally scaled.

---

## 3. Session State: Move It Out of the Process

Any per-user state must live in an external store, not in the application process.

### Anti-Pattern: In-Process Session State

```python
# Wrong: module-level dict is process-local
# A different pod has a different dict
_sessions: dict[str, dict] = {}

async def get_session(session_id: str) -> dict:
    return _sessions.get(session_id, {})

async def set_session(session_id: str, data: dict) -> None:
    _sessions[session_id] = data
```

### Correct Pattern: Redis-Backed Sessions

```python
# src/feature_pipeline/session.py
import json
import redis.asyncio as redis

_redis: redis.Redis | None = None

def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        raise RuntimeError("Redis not initialized — call init_redis() first")
    return _redis

async def init_redis(url: str) -> None:
    global _redis
    _redis = await redis.from_url(url, decode_responses=True)

async def get_session(session_id: str) -> dict:
    client = get_redis()
    data = await client.get(f"session:{session_id}")
    return json.loads(data) if data else {}

async def set_session(session_id: str, data: dict, ttl_seconds: int = 3600) -> None:
    client = get_redis()
    await client.setex(
        f"session:{session_id}",
        ttl_seconds,
        json.dumps(data),
    )
```

```python
# src/feature_pipeline/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from feature_pipeline.session import init_redis
from feature_pipeline.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis(settings.redis_url)  # Establish pool at startup
    yield
    # Redis client cleanup handled by the redis.asyncio library on gc

app = FastAPI(lifespan=lifespan)
```

Any pod can serve any request because session state is in Redis, not in the pod's memory. Adding a fourth pod instance requires no data migration.

---

## 4. Connection Pooling

Each pod opens database connections. With 10 pods × 20 connections per pod = 200 connections to PostgreSQL. PostgreSQL's default `max_connections` is 100. Without a connection pooler, horizontal scaling breaks the database.

### PgBouncer

PgBouncer sits between the application and PostgreSQL, multiplexing many application connections onto a small pool of actual database connections.

```
10 pods × 20 connections = 200 app connections
          ↓ PgBouncer (transaction pooling)
PostgreSQL ← 20 actual connections
```

PgBouncer modes:

| Mode | Connection reuse | Limitations |
|------|-----------------|-------------|
| **Session** | One server connection per client session | 1:1 ratio; no benefit over no pooler |
| **Transaction** | Connection returned to pool after each transaction | Can't use `SET`, `LISTEN/NOTIFY`, prepared statements across transactions |
| **Statement** | Connection returned after each statement | Most restrictive; incompatible with most ORMs |

**Transaction mode** is the correct default for FastAPI + SQLAlchemy applications. Most request handlers are single-transaction; the connection is released immediately.

```yaml
# k8s/pgbouncer-config.yaml (ConfigMap)
apiVersion: v1
kind: ConfigMap
metadata:
  name: pgbouncer-config
data:
  pgbouncer.ini: |
    [databases]
    app = host=postgres.production.svc.cluster.local port=5432 dbname=app

    [pgbouncer]
    pool_mode = transaction
    max_client_conn = 500       # Max connections from application pods
    default_pool_size = 25      # Actual connections to PostgreSQL
    min_pool_size = 5
    reserve_pool_size = 5
    server_idle_timeout = 600
    listen_port = 5432
    auth_type = scram-sha-256
```

Application pods connect to PgBouncer, not directly to PostgreSQL:

```python
# settings: DATABASE_URL points to PgBouncer, not PostgreSQL
DATABASE_URL = "postgresql+asyncpg://app:password@pgbouncer:5432/app"
```

### SQLAlchemy Pool Sizing

Even with PgBouncer, configure the application-side pool:

```python
# src/feature_pipeline/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from feature_pipeline.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=5,            # Connections kept open per pod
    max_overflow=10,        # Additional connections allowed under load
    pool_pre_ping=True,     # Verify connection health before use
    pool_recycle=3600,      # Recycle connections after 1 hour (prevents stale state)
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

With `pool_size=5` and `max_overflow=10`, a single pod can hold up to 15 connections to PgBouncer under peak load.

---

## 5. Graceful Shutdown

When Kubernetes terminates a pod (rolling update, node drain, scale-down), it sends `SIGTERM`. The application has `terminationGracePeriodSeconds` (default 30s) to finish in-flight requests and close connections before `SIGKILL` is sent.

### The Problem: Asynchronous Endpoint Removal

Kubernetes removes the pod from the Service endpoint list when it begins terminating — but load balancers propagate this change asynchronously. For a few seconds after `SIGTERM` is received, the pod may still receive new requests from clients that haven't learned it's gone.

### The Solution: PreStop Hook + Graceful Uvicorn Shutdown

```yaml
# In the Deployment container spec
lifecycle:
  preStop:
    exec:
      # Sleep before the app starts shutting down — gives the load balancer
      # time to propagate the endpoint removal.
      command: ["/bin/sh", "-c", "sleep 10"]

terminationGracePeriodSeconds: 45
# Must be > preStop sleep duration + max expected request duration
```

```python
# src/feature_pipeline/main.py
import asyncio
import signal
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Starting feature-pipeline service")
    await init_redis(settings.redis_url)
    await init_db(settings.database_url)

    yield  # Application is running

    # ── Shutdown ──────────────────────────────────────────────────────────────
    # Uvicorn has already stopped accepting new requests by the time
    # this code runs. Finish cleanup of long-lived resources.
    logger.info("Shutting down — closing database connections")
    await engine.dispose()   # Return all connections to the pool / close them
    logger.info("Shutdown complete")

app = FastAPI(lifespan=lifespan)
```

Starting Uvicorn correctly — use the `exec` form in the Dockerfile so the process is PID 1 and receives `SIGTERM` directly:

```dockerfile
# Correct: exec form — Uvicorn is PID 1
CMD ["uvicorn", "feature_pipeline.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "1", "--timeout-graceful-shutdown", "30"]

# Wrong: shell form — sh is PID 1, SIGTERM may not propagate to Python
CMD uvicorn feature_pipeline.main:app ...
```

`--timeout-graceful-shutdown 30` tells Uvicorn to wait up to 30 seconds for in-flight requests to complete before forcibly closing.

### Shutdown Sequence Summary

```
t=0s   Kubernetes removes pod from Service endpoints
t=0s   preStop hook begins: sleep 10
t=0s   SIGTERM sent to Uvicorn (PID 1) -- Uvicorn stops accepting new connections
t=10s  preStop completes; Uvicorn drains in-flight requests (up to 30s)
t=40s  Engine.dispose() closes DB connections; lifespan shutdown completes
t=45s  terminationGracePeriodSeconds deadline — SIGKILL sent if still running
```

---

## 6. Cold Start Optimization

Cold start is the time between pod scheduling and the first request being served. For ML services with large model artifacts, this can be measured in minutes without optimization.

### Model Loading at Startup

```python
# src/feature_pipeline/model.py
from pathlib import Path
import joblib
import structlog

logger = structlog.get_logger()

_model = None

def get_model():
    """Return the loaded model. Raises if model not yet loaded."""
    if _model is None:
        raise RuntimeError("Model not loaded — call load_model() during startup")
    return _model

async def load_model(model_path: Path) -> None:
    """Load model at startup (inside lifespan context). Never lazy-load in a request handler."""
    global _model
    logger.info("Loading model", path=str(model_path))
    # joblib.load is synchronous; run in thread pool to avoid blocking the event loop
    import asyncio
    _model = await asyncio.to_thread(joblib.load, model_path)
    logger.info("Model loaded", type=type(_model).__name__)
```

```python
# In lifespan startup:
await load_model(Path(settings.model_path))
```

**Never lazy-load in a request handler**. The first request after a cold start would take the full model load time. Instead, the startup probe's `failureThreshold` + `periodSeconds` gives the pod time to load the model before it receives traffic.

### Kubernetes Image Pull Optimization

```yaml
# Pull policy: IfNotPresent avoids pulling the image on every restart
# (only pulls if the image is not already cached on the node)
imagePullPolicy: IfNotPresent

# For large images (>2 GB), pre-pull on all nodes using a DaemonSet
# This ensures the image is cached before the pod needs it
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: prepull-feature-pipeline
spec:
  selector:
    matchLabels:
      name: prepull-feature-pipeline
  template:
    spec:
      initContainers:
        - name: pull
          image: ghcr.io/your-org/feature-pipeline:a3f2b1c
          command: ["true"]  # Exit immediately — just pulls the image
      containers:
        - name: pause
          image: gcr.io/google_containers/pause:3.9
```

### Connection Warming

```python
# In lifespan startup, establish the connection pool explicitly
# instead of waiting for the first request to trigger it
async def warmup_db(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

# Similarly for Redis
async def warmup_redis(client) -> None:
    await client.ping()
```

A connection pool that's warm at startup means the first real request doesn't pay the TCP handshake + TLS negotiation + auth roundtrip cost.

### Lazy Loading Anti-Pattern

```python
# Wrong: module-level lazy import triggers on first request
def get_model():
    import joblib
    return joblib.load("model.pkl")  # Runs on the first request — unacceptable latency

# Also wrong: loading inside a request handler
@app.post("/predict")
async def predict(features: FeatureVector) -> Prediction:
    model = joblib.load("model.pkl")  # ← blocks the event loop for seconds
    return model.predict(features.values)
```

---

## Summary

| Concern | Decision |
|---------|----------|
| Process state | Stateless — all session/user state in Redis |
| Session storage | Redis with TTL; key pattern `session:{id}` |
| Connection pooling | PgBouncer (transaction mode) between app and PostgreSQL |
| SQLAlchemy pool | `pool_size=5`, `max_overflow=10`, `pool_pre_ping=True` |
| SIGTERM handling | `exec` form CMD; `preStop sleep 10`; Uvicorn `--timeout-graceful-shutdown 30` |
| Grace period | `terminationGracePeriodSeconds: 45` (preStop + request drain + cleanup) |
| Model loading | Eager load in lifespan startup; never lazy-load in request handlers |
| Cold start | Startup probe gives time; pre-pull DaemonSet for large images |
| Horizontal scaling | Default strategy for all Python services except single-GPU model serving |
