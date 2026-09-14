# 02 — FastAPI In Depth

## FastAPI as an Implementation Layer

FastAPI is not an API design tool — it is an implementation tool. The design decisions (resources, methods, status codes, versioning) belong to the API contract, not to FastAPI. FastAPI's job is to implement that contract with minimal boilerplate, automatic validation, and automatic documentation.

This file covers the FastAPI features that matter in production: route organization, dependency injection, validation, response modeling, middleware, lifespan management, and OpenAPI customization. All examples use the `feature-pipeline` serving API.

**Install:**
```bash
uv add fastapi uvicorn[standard]
```

---

## 1. `APIRouter` for Modular Route Organization

A production FastAPI application should never define all routes in a single `main.py`. Routes are organized into routers by resource or domain area.

```
src/
└── feature_pipeline/
    └── api/
        ├── __init__.py
        ├── main.py          # application factory, router mounting
        ├── deps.py          # shared dependency functions
        ├── routers/
        │   ├── __init__.py
        │   ├── features.py  # /v1/features
        │   ├── pipelines.py # /v1/pipelines
        │   └── health.py    # /health
        └── schemas/
            ├── __init__.py
            ├── features.py  # request/response models
            └── pipelines.py
```

### Router Definition

```python
# src/feature_pipeline/api/routers/features.py
from fastapi import APIRouter, Depends, HTTPException, status
from feature_pipeline.api import deps, schemas
from feature_pipeline.domain import FeatureService

router = APIRouter(
    prefix="/features",
    tags=["features"],
    responses={
        404: {"description": "Feature not found"},
        422: {"description": "Validation error"},
    },
)

@router.get(
    "/{feature_id}",
    response_model=schemas.features.FeatureResponse,
    summary="Retrieve a feature by ID",
)
async def get_feature(
    feature_id: str,
    service: FeatureService = Depends(deps.get_feature_service),
) -> schemas.features.FeatureResponse:
    feature = await service.get(feature_id)
    if feature is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "FEATURE_NOT_FOUND",
                "message": f"Feature '{feature_id}' does not exist.",
            },
        )
    return schemas.features.FeatureResponse.model_validate(feature)
```

### Application Factory

```python
# src/feature_pipeline/api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from feature_pipeline.api.routers import features, pipelines, health
from feature_pipeline.api import middleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — runs before accepting requests
    await startup()
    yield
    # Shutdown — runs after the last request completes
    await shutdown()

def create_app() -> FastAPI:
    app = FastAPI(
        title="Feature Pipeline API",
        version="1.0.0",
        description="Serving API for computed features",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Mount routers with a consistent version prefix
    app.include_router(health.router, tags=["health"])
    app.include_router(features.router, prefix="/v1")
    app.include_router(pipelines.router, prefix="/v1")

    # Register middleware (order matters — added last runs first)
    middleware.register(app)

    return app

app = create_app()
```

---

## 2. Dependency Injection with `Depends()`

`Depends()` is FastAPI's DI mechanism. Dependencies are callables (functions or classes) that FastAPI resolves before calling the route handler. Dependencies can themselves have dependencies — FastAPI builds the full dependency graph automatically.

### Dependency Definition

```python
# src/feature_pipeline/api/deps.py
from typing import Annotated
from fastapi import Depends, Header, HTTPException, status
from feature_pipeline.domain import FeatureService, PipelineService
from feature_pipeline.infrastructure import RedisFeatureStore, get_db_session
from feature_pipeline.settings import Settings, get_settings

# Settings dependency — singleton, resolved once
async def get_settings_dep() -> Settings:
    return get_settings()

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]

# Database session dependency — new session per request
async def get_db():
    async with get_db_session() as session:
        yield session          # request handler runs here; session closes after

DBSession = Annotated[AsyncSession, Depends(get_db)]

# Service dependency — depends on db session
async def get_feature_service(
    db: DBSession,
    settings: SettingsDep,
) -> FeatureService:
    store = RedisFeatureStore(url=settings.redis_url)
    return FeatureService(db=db, store=store)

FeatureServiceDep = Annotated[FeatureService, Depends(get_feature_service)]

# Auth dependency — applies to all protected routes
async def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
    settings: SettingsDep = Depends(get_settings_dep),
) -> str:
    if x_api_key is None or not _is_valid_key(x_api_key, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_API_KEY", "message": "API key missing or invalid."},
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key

AuthDep = Annotated[str, Depends(require_api_key)]
```

### Using Dependencies in Routes

```python
@router.get("/{feature_id}", response_model=FeatureResponse)
async def get_feature(
    feature_id: str,
    _: AuthDep,                   # validates auth; result discarded
    service: FeatureServiceDep,   # typed, resolved by DI
) -> FeatureResponse:
    ...
```

### Router-Level Dependencies

Apply a dependency to every route in a router — useful for auth:

```python
# Apply auth to every route in this router
router = APIRouter(
    prefix="/features",
    tags=["features"],
    dependencies=[Depends(require_api_key)],  # runs for every route
)
```

### Dependency Caching

FastAPI caches dependency results within a single request. If two route parameters both declare `Depends(get_db)`, the session is created once and shared. Use `use_cache=False` to opt out:

```python
# Forces a fresh session for this dependency
db: Annotated[AsyncSession, Depends(get_db, use_cache=False)]
```

---

## 3. Request Validation with Pydantic

FastAPI uses Pydantic v2 for validation. Declare schemas as `BaseModel` subclasses; FastAPI handles the rest.

### Request Bodies

```python
# src/feature_pipeline/api/schemas/features.py
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

class FeatureCreateRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]*$",
        examples=["user_age", "session_count"],
        description="Feature name. Must be lowercase snake_case.",
    )
    pipeline_id: str = Field(description="ID of the owning pipeline.")
    value: float | int | str | bool = Field(description="Feature value.")
    ttl_seconds: int | None = Field(
        default=None,
        ge=1,
        le=86_400 * 30,
        description="Optional TTL in seconds. Max 30 days.",
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_reserved(cls, v: str) -> str:
        reserved = {"id", "type", "version", "created_at"}
        if v in reserved:
            raise ValueError(f"'{v}' is a reserved feature name.")
        return v
```

### Path and Query Parameters

```python
from fastapi import Query, Path
from typing import Annotated

@router.get("/")
async def list_features(
    pipeline_id: Annotated[str, Query(description="Filter by pipeline.")],
    status: Annotated[
        FeatureStatus | None,
        Query(description="Filter by status.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    cursor: Annotated[str | None, Query(description="Pagination cursor.")] = None,
    service: FeatureServiceDep = ...,
) -> FeatureListResponse:
    ...

@router.get("/{feature_id}")
async def get_feature(
    feature_id: Annotated[
        str,
        Path(description="The feature ID.", min_length=1, max_length=64),
    ],
    service: FeatureServiceDep = ...,
) -> FeatureResponse:
    ...
```

### Headers

```python
from fastapi import Header

@router.post("/", status_code=201)
async def create_feature(
    body: FeatureCreateRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    service: FeatureServiceDep = ...,
) -> FeatureResponse:
    ...
```

---

## 4. Response Models

### `response_model` and `response_model_exclude_none`

```python
class FeatureResponse(BaseModel):
    id: str
    name: str
    value: float | int | str | bool
    pipeline_id: str
    created_at: datetime
    expires_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)

@router.get(
    "/{feature_id}",
    response_model=FeatureResponse,
    response_model_exclude_none=True,   # omit null fields from response
)
async def get_feature(...) -> FeatureResponse:
    ...
```

`response_model` does two things:
1. Filters the response — even if the route handler returns extra fields, only declared fields are included. This prevents accidentally leaking internal state.
2. Generates the OpenAPI response schema.

`response_model_exclude_none=True` keeps the response compact by omitting `null` fields. Use this by default; opt into `null` explicitly when clients need to distinguish "not set" from "absent".

### `JSONResponse` vs. Model Return

```python
from fastapi.responses import JSONResponse

# Avoid: bypasses response_model filtering and OpenAPI schema generation
@router.get("/{feature_id}")
async def get_feature(...) -> JSONResponse:
    return JSONResponse(content={"id": "abc"})

# Prefer: return the model, let FastAPI serialize
@router.get("/{feature_id}", response_model=FeatureResponse)
async def get_feature(...) -> FeatureResponse:
    return FeatureResponse(id="abc", ...)
```

`JSONResponse` is appropriate when:
- Returning a response that is already a validated dict (e.g., cached JSON blob)
- Streaming responses
- Setting custom headers or cookies alongside the body

---

## 5. Lifespan Events

Replaces the deprecated `@app.on_event("startup")` / `@app.on_event("shutdown")` pattern:

```python
# src/feature_pipeline/api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from feature_pipeline.infrastructure import RedisPool, DatabasePool
import structlog

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP — runs once, before the first request
    logger.info("startup.begin")

    db_pool = await DatabasePool.connect(settings.database_url)
    redis_pool = await RedisPool.connect(settings.redis_url)

    # Attach to app.state for access in dependencies
    app.state.db_pool = db_pool
    app.state.redis_pool = redis_pool

    logger.info("startup.complete", db_pool_size=db_pool.size)

    yield  # ← requests are handled here

    # SHUTDOWN — runs after the last request completes
    logger.info("shutdown.begin")
    await db_pool.close()
    await redis_pool.close()
    logger.info("shutdown.complete")
```

The `yield` divides startup from shutdown. Resources initialized before `yield` are available throughout the application's lifetime. Resources are cleaned up even if the application crashes during startup (the `asynccontextmanager` guarantees cleanup up to the point of failure).

Access `app.state` in dependencies via the `Request` object:

```python
from fastapi import Request

async def get_db(request: Request) -> AsyncSession:
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        yield conn
```

---

## 6. Middleware

Middleware runs on every request/response cycle. Order of registration matters: middleware added *last* runs *first* on incoming requests and *last* on outgoing responses (LIFO for request, FIFO for response — like a stack).

```python
# src/feature_pipeline/api/middleware.py
import time
import uuid
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import structlog

logger = structlog.get_logger()

def register(app: FastAPI) -> None:
    # GZip — compress responses > 1KB
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # CORS — configure for your actual origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://dashboard.internal.company.com"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request ID — must be innermost (runs first on request, last on response)
    app.middleware("http")(request_id_middleware)
    app.middleware("http")(timing_middleware)
```

### Request ID Middleware

```python
async def request_id_middleware(request: Request, call_next) -> Response:
    # Use client-provided ID (from a gateway) or generate one
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"

    # Bind to structlog context for all log lines in this request
    with structlog.contextvars.bound_contextvars(request_id=request_id):
        response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    return response
```

### Timing Middleware

```python
async def timing_middleware(request: Request, call_next) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2),
    )

    response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 2))
    return response
```

---

## 7. Background Tasks

`BackgroundTasks` runs a function *after* the response is sent to the client, within the same process:

```python
from fastapi import BackgroundTasks

@router.post("/features/", status_code=201)
async def create_feature(
    body: FeatureCreateRequest,
    background_tasks: BackgroundTasks,
    service: FeatureServiceDep,
) -> FeatureResponse:
    feature = await service.create(body)

    # Runs after 201 response is sent — client does not wait
    background_tasks.add_task(emit_feature_created_event, feature_id=feature.id)

    return FeatureResponse.model_validate(feature)
```

**When `BackgroundTasks` is appropriate:**
- Fire-and-forget audit logging
- Cache invalidation after a write
- Sending a notification after an operation

**When to use a proper queue instead:**
- The task must survive a server restart (BackgroundTasks are in-memory — a crash loses them)
- The task might take more than a few seconds
- The task needs retry behavior on failure
- Fan-out to multiple consumers

Use `BackgroundTasks` for sub-second ancillary work. Use a message queue (Redis Streams, Kafka, Pub/Sub — Chapter 05) for anything requiring durability or reliability.

---

## 8. OpenAPI Customization

FastAPI generates an OpenAPI 3.1 spec automatically. Customize it to make the generated docs useful:

```python
@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=FeatureResponse,
    summary="Create a feature",           # short, shown in the route list
    description="""
    Store a computed feature value.

    The feature is associated with a pipeline and optionally expires after `ttl_seconds`.
    If an `Idempotency-Key` header is provided, duplicate requests with the same key
    return the original response without creating a duplicate record.
    """,                                   # long form, shown in the detail view
    responses={
        201: {"description": "Feature created."},
        409: {
            "description": "Duplicate idempotency key.",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "DUPLICATE_IDEMPOTENCY_KEY",
                            "message": "A feature with this idempotency key already exists.",
                        }
                    }
                }
            },
        },
    },
)
async def create_feature(...) -> FeatureResponse: ...
```

### Tags and Organization

Tags group routes in the OpenAPI UI:

```python
# main.py — tags defined at router mount
app.include_router(features.router, prefix="/v1", tags=["Features"])
app.include_router(pipelines.router, prefix="/v1", tags=["Pipelines"])
app.include_router(health.router, tags=["Operations"])
```

### Disabling Docs in Production

OpenAPI docs expose your full API surface including security requirements. Some teams disable them outside development:

```python
from feature_pipeline.settings import settings

app = FastAPI(
    docs_url="/docs" if settings.env == "development" else None,
    redoc_url="/redoc" if settings.env == "development" else None,
    openapi_url="/openapi.json" if settings.env != "production" else None,
)
```

---

## 9. Health Checks

Every FastAPI service should expose a health endpoint. The route is excluded from authentication:

```python
# src/feature_pipeline/api/routers/health.py
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()

class HealthResponse(BaseModel):
    status: str
    version: str
    checks: dict[str, str]

@router.get(
    "/health",
    response_model=HealthResponse,
    include_in_schema=False,   # hide from OpenAPI docs
    status_code=status.HTTP_200_OK,
    tags=["Operations"],
)
async def health_check(request: Request) -> HealthResponse:
    checks: dict[str, str] = {}

    # Check database connectivity
    try:
        await request.app.state.db_pool.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "degraded"

    # Check Redis connectivity
    try:
        await request.app.state.redis_pool.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "degraded"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"

    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content=HealthResponse(
            status=overall,
            version="1.0.0",
            checks=checks,
        ).model_dump(),
    )
```

---

## Summary

| Feature | Recommendation |
|---------|---------------|
| Route organization | `APIRouter` per resource; mount with prefix in `create_app()` |
| Dependency injection | `Annotated[Type, Depends(...)]` pattern; router-level deps for auth |
| Validation | Pydantic v2 `BaseModel`; use `Field()` for constraints and OpenAPI docs |
| Response models | Always declare `response_model=`; use `response_model_exclude_none=True` |
| Lifespan | `@asynccontextmanager` on `lifespan`; attach resources to `app.state` |
| Middleware | Request ID first, timing second, CORS and GZip last; log every request |
| Background tasks | Use for sub-second fire-and-forget; use a queue for anything needing durability |
| Health check | `/health` at root, excluded from auth and OpenAPI schema |

> **The FastAPI application factory pattern (`create_app()`) is the correct unit of composition.** It separates configuration from instantiation, enabling test-time overrides of dependencies and settings without patching globals.
