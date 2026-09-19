# 06 — Idempotency and Safety

## Why Correctness Under Failure Is a Design Requirement

Networks fail. Load balancers time out. Clients retry. Deploys cause brief unavailability. These are not exceptional conditions — they are the normal operating environment of a distributed system.

An API that is not designed with failure in mind will produce incorrect state under retries: duplicate records created, double-charges processed, jobs submitted twice. The properties of safety and idempotency are the formal tools for reasoning about correct behavior under failure.

---

## 1. Safe, Unsafe, and Idempotent Methods

These are HTTP protocol properties, not application-level conventions.

**Safe**: The request has no server-side side effects. Calling it any number of times has the same effect as not calling it at all.

**Idempotent**: Calling the request any number of times has the same effect as calling it once. The *outcome* is the same, though the server may have done work multiple times.

| Method | Safe | Idempotent | Notes |
|--------|------|-----------|-------|
| `GET` | ✅ | ✅ | Read-only. Safe to retry unconditionally. |
| `HEAD` | ✅ | ✅ | Like GET, no body. Safe to retry. |
| `OPTIONS` | ✅ | ✅ | Discovery only. |
| `PUT` | ❌ | ✅ | Replace-entire-resource. Calling twice produces the same final state. |
| `DELETE` | ❌ | ✅ | First call removes. Subsequent calls return 404 or 204 — same final state (resource is gone). |
| `PATCH` | ❌ | ❌ | Usually not idempotent (e.g., `{"value": "+1"}` applied twice doubles the increment). |
| `POST` | ❌ | ❌ | Creates a new resource. Retrying creates duplicates by default. |

### Practical Implications

**Infrastructure automatically retries safe methods.** Load balancers, service meshes, and HTTP clients retry `GET` and `HEAD` on network failures. A `GET` route that has write side effects (e.g., modifying a counter on every read) will behave unexpectedly.

**Client libraries may retry idempotent methods.** `PUT` and `DELETE` are safe to retry — the second call produces no additional side effects.

**`POST` is the problematic method.** It is neither safe nor idempotent by default, which means clients cannot safely retry it on failure without the risk of duplicate operations. The `Idempotency-Key` pattern addresses this.

---

## 2. The `Idempotency-Key` Pattern

The idempotency key pattern makes non-idempotent operations (typically `POST`) safe to retry. The client generates a unique key for each logical operation and includes it in the request header. The server stores the result of the first request and returns it verbatim for subsequent requests with the same key.

**Used by:** Stripe, Braintree, Adyen (payment APIs where duplicate charges are catastrophic). Appropriate for any operation where creating a duplicate would cause harm.

### When to Use Idempotency Keys

**Always use when:**
- Creating a resource that must not be duplicated (payment, job submission, feature creation in a pipeline)
- The client will retry on timeout or transient failure

**Not necessary when:**
- The client is the only possible producer (no race conditions)
- Duplicates are harmless and easy to detect and remove

### Implementation

```python
# src/feature_pipeline/infrastructure/idempotency.py
import json
from datetime import timedelta
from redis.asyncio import Redis
from pydantic import BaseModel

IDEMPOTENCY_TTL = timedelta(hours=24)

class IdempotencyRecord(BaseModel):
    status_code: int
    response_body: dict
    created_at: str

class IdempotencyStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, idempotency_key: str) -> str:
        return f"idempotency:{idempotency_key}"

    async def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        raw = await self._redis.get(self._key(idempotency_key))
        if raw is None:
            return None
        return IdempotencyRecord.model_validate_json(raw)

    async def set(
        self,
        idempotency_key: str,
        record: IdempotencyRecord,
    ) -> None:
        await self._redis.setex(
            self._key(idempotency_key),
            int(IDEMPOTENCY_TTL.total_seconds()),
            record.model_dump_json(),
        )
```

```python
# src/feature_pipeline/api/deps.py
async def get_idempotency_store(request: Request) -> IdempotencyStore:
    return IdempotencyStore(redis=request.app.state.redis_pool)

IdempotencyStoreDep = Annotated[IdempotencyStore, Depends(get_idempotency_store)]
```

```python
# src/feature_pipeline/api/routers/features.py
from datetime import datetime, timezone
from fastapi import Header
from fastapi.responses import JSONResponse

@router.post("/", status_code=201, response_model=FeatureResponse)
async def create_feature(
    body: FeatureCreateRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    service: FeatureServiceDep = ...,
    idem_store: IdempotencyStoreDep = ...,
) -> FeatureResponse:
    # 1. Check for a cached response if key is provided
    if idempotency_key:
        cached = await idem_store.get(idempotency_key)
        if cached:
            return JSONResponse(
                status_code=cached.status_code,
                content=cached.response_body,
                headers={"Idempotency-Key": idempotency_key, "X-Idempotent-Replayed": "true"},
            )

    # 2. Execute the operation
    feature = await service.create(body)
    response_data = FeatureResponse.model_validate(feature).model_dump(mode="json")

    # 3. Cache the result
    if idempotency_key:
        await idem_store.set(
            idempotency_key,
            IdempotencyRecord(
                status_code=201,
                response_body=response_data,
                created_at=datetime.now(timezone.utc).isoformat(),
            ),
        )

    return FeatureResponse.model_validate(feature)
```

### Idempotency Key Rules

| Rule | Reason |
|------|--------|
| Client generates the key | The server cannot know the client's intent — only the client knows this is a retry |
| Key must be unique per operation | A UUID4 is appropriate: `str(uuid.uuid4())` |
| Key scope is the client + endpoint | A key for `/v1/features` is distinct from the same key for `/v1/pipelines` |
| Keys expire after 24 hours | Stale keys should not block future operations with the same key |
| Return the exact original response | Including status code — a `201` on first call returns `201` on retry |

---

## 3. Optimistic Locking with `ETag` / `If-Match`

Optimistic locking prevents concurrent writes from overwriting each other silently. The server generates a version token (ETag) for each resource; clients must provide the current ETag when updating.

This is the correct mechanism for:
- Concurrent edits by multiple users
- Preventing stale writes in distributed systems
- The "read-modify-write" pattern where the modification depends on the current state

### ETag Generation

```python
import hashlib

def compute_etag(data: dict) -> str:
    """Deterministic ETag from resource content."""
    content = json.dumps(data, sort_keys=True, default=str).encode()
    return f'"{hashlib.sha256(content).hexdigest()[:16]}"'
```

### Server-Side Implementation

```python
@router.get("/{feature_id}", response_model=FeatureResponse)
async def get_feature(
    feature_id: str,
    response: Response,
    service: FeatureServiceDep,
) -> FeatureResponse:
    feature = await service.get(feature_id)
    data = FeatureResponse.model_validate(feature)

    etag = compute_etag(data.model_dump(mode="json"))
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"  # revalidate on every request

    return data

@router.patch("/{feature_id}", response_model=FeatureResponse)
async def update_feature(
    feature_id: str,
    body: FeatureUpdateRequest,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    service: FeatureServiceDep = ...,
) -> FeatureResponse:
    # Require If-Match for updates to prevent lost-update problem
    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "IF_MATCH_REQUIRED",
                "message": "The If-Match header is required for updates. "
                           "Fetch the resource first to get the current ETag.",
            },
        )

    current = await service.get(feature_id)
    current_etag = compute_etag(
        FeatureResponse.model_validate(current).model_dump(mode="json")
    )

    if if_match != current_etag:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "code": "ETAG_MISMATCH",
                "message": "The resource has been modified since you last fetched it. "
                           "Fetch the current version and retry.",
            },
        )

    updated = await service.update(feature_id, body)
    return FeatureResponse.model_validate(updated)
```

### Client Flow

```
1. GET /v1/features/abc
   → 200 OK, ETag: "abc123"

2. PATCH /v1/features/abc
   If-Match: "abc123"
   → 200 OK if no concurrent modification

3. If another client modified the resource between steps 1 and 2:
   PATCH /v1/features/abc
   If-Match: "abc123"       (stale ETag)
   → 412 Precondition Failed

4. Client re-fetches, re-applies changes, retries with new ETag
```

---

## 4. The Upsert Pattern

An upsert creates the resource if it does not exist, or updates it if it does. The correct HTTP method depends on the semantics.

### `PUT` as Upsert (Recommended)

`PUT` is idempotent and semantically means "set the resource at this URL to this state." This maps naturally to upsert:

```python
@router.put(
    "/{feature_id}",
    status_code=200,  # or 201 if created — use response to signal
    response_model=FeatureResponse,
)
async def upsert_feature(
    feature_id: str,
    body: FeatureUpsertRequest,
    response: Response,
    service: FeatureServiceDep,
) -> FeatureResponse:
    feature, created = await service.upsert(feature_id, body)

    if created:
        response.status_code = status.HTTP_201_CREATED
        response.headers["Location"] = f"/v1/features/{feature.id}"

    return FeatureResponse.model_validate(feature)
```

Returning `201` on creation and `200` on update tells clients whether they created something new — useful for idempotent client flows that need to distinguish first write from subsequent writes.

### When to Choose PUT vs. PATCH vs. POST for Upserts

| Intent | Method | Idempotent |
|--------|--------|-----------|
| Create or fully replace (caller provides full state) | `PUT` | ✅ |
| Create or partially update (caller provides delta) | `POST /upsert` or `PATCH` | ⚠️ (PATCH only if delta is idempotent) |
| Create only (error on duplicate) | `POST` | ❌ (requires idempotency key for safe retry) |

---

## 5. Retry Contracts

A retry contract documents which errors are safe to retry and how. Every API that is called over a network should publish one — either in its documentation or via response headers.

### What Is Safe to Retry

| Status code | Safe to retry | Notes |
|-------------|--------------|-------|
| `200`, `201`, `204` | No (already succeeded) | |
| `400 Bad Request` | ❌ No | Client error — fixing the request, not retrying it, is the solution |
| `401 Unauthorized` | ❌ No | Fix authentication |
| `403 Forbidden` | ❌ No | Fix permissions |
| `404 Not Found` | ❌ No | Resource does not exist |
| `409 Conflict` | ❌ No | Resolve the conflict first (optimistic lock failure, duplicate key) |
| `422 Unprocessable Entity` | ❌ No | Fix the request |
| `429 Too Many Requests` | ✅ Yes | After `Retry-After` delay |
| `500 Internal Server Error` | ✅ Yes | With exponential backoff |
| `503 Service Unavailable` | ✅ Yes | After `Retry-After` delay |

**Only `5xx` and `429` errors are safe to retry.** Retrying `4xx` errors is never correct — the request is wrong, and the same wrong request will produce the same `4xx`.

### `Retry-After` Header

For `429` and `503`, include a `Retry-After` header:

```python
from fastapi.responses import JSONResponse

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Rate limit exceeded. Retry after the indicated delay.",
            }
        },
        headers={
            "Retry-After": "60",                  # seconds
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(time.time()) + 60),
        },
    )
```

### Exponential Backoff with Jitter

When retrying `5xx` errors, clients must use exponential backoff with jitter to avoid the "thundering herd" — all retries hitting at the same moment after a recovery:

```python
import asyncio
import random
from typing import TypeVar, Callable, Awaitable

T = TypeVar("T")

async def retry_with_backoff(
    operation: Callable[[], Awaitable[T]],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_status: frozenset[int] = frozenset({429, 500, 502, 503, 504}),
) -> T:
    """Retry an async operation with exponential backoff and jitter."""
    import httpx

    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return await operation()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in retryable_status:
                raise  # non-retryable: propagate immediately

            last_exc = exc
            if attempt == max_attempts - 1:
                break

            # Exponential backoff: 1s, 2s, 4s, ... capped at max_delay
            delay = min(base_delay * (2 ** attempt), max_delay)
            # Add jitter: ±25% of the delay
            jitter = delay * 0.25 * (2 * random.random() - 1)
            await asyncio.sleep(delay + jitter)

    raise last_exc  # type: ignore[misc]
```

---

## Summary

| Concept | Key point |
|---------|-----------|
| Safe methods | `GET`, `HEAD` — no side effects; infrastructure retries automatically |
| Idempotent methods | `PUT`, `DELETE` — safe to retry; same outcome regardless of call count |
| `POST` | Neither safe nor idempotent by default |
| Idempotency keys | Client-generated UUID in `Idempotency-Key` header; server caches response for 24h |
| Optimistic locking | `ETag` on GET; `If-Match` required on PATCH/PUT; `412` on mismatch |
| Upsert | Use `PUT` — it is idempotent and semantically correct |
| Retry safety | `5xx` and `429` only; never retry `4xx` |
| Retry strategy | Exponential backoff with jitter; respect `Retry-After` |

| Header | Purpose |
|--------|---------|
| `Idempotency-Key` | Client-supplied deduplication key for `POST` |
| `ETag` | Server-generated resource version token |
| `If-Match` | Client sends ETag; server rejects if stale (`412`) |
| `Retry-After` | Seconds until the client may retry (on `429`, `503`) |

> **Idempotency is not an optimization — it is a correctness requirement.** Any API that can be called over a network will be retried. The question is whether the retry produces the correct outcome or a corrupted state.
