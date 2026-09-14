# 03 — API Versioning

## Why Versioning Is Not Optional

An API without a versioning strategy is an API that cannot evolve without breaking its consumers. The choice is not whether to version — it is when to introduce versioning and how to signal changes.

Breaking changes are unavoidable in a long-lived API. Fields get renamed, data types change, resources get restructured, behaviors are corrected. The question is whether these changes break consumers silently (they get unexpected data and fail in unpredictable ways) or loudly at the API boundary (they get a clear signal that they need to update).

A versioning strategy allows the API to evolve while giving consumers a stable contract and a defined migration window.

---

## 1. The Three Versioning Strategies

### Strategy 1: URL Path Versioning

The version is part of the URL path:

```
/v1/features/{id}
/v2/features/{id}   # breaking change → new version
```

**Advantages:**
- Immediately obvious in logs, dashboards, and error reports
- No special client configuration — any HTTP client works
- Easy to route differently at the load balancer or API gateway level
- Easy to deprecate (block all requests to `/v1/` after sunset date)

**Disadvantages:**
- URLs are "impure" from a strict REST standpoint — a resource's identity should not include its version
- Clients must update hardcoded URLs when migrating

**Recommendation: use this. It is the practical default for the vast majority of teams.**

### Strategy 2: Request Header Versioning

The version is communicated via a custom request header:

```http
GET /features/abc HTTP/1.1
API-Version: 2024-01
```

```http
GET /features/abc HTTP/1.1
API-Version: 2024-07
```

Used by Stripe (but even Stripe uses URL versioning for major versions), GitHub, and others for date-based versioning:

**Advantages:**
- URLs remain stable — the resource identity is clean
- Fine-grained versioning by date rather than integer

**Disadvantages:**
- Invisible in browser URL bars and server logs unless explicitly logged
- HTTP caches (including browser cache) treat the same URL as the same resource, ignoring headers — requires `Vary: API-Version` header to fix
- Harder to test with simple `curl`; harder to share links
- Many API gateways and load balancers route on URL, not headers

### Strategy 3: Content-Type Versioning (Accept Header)

The version is in the `Accept` header using vendor MIME types:

```http
GET /features/abc HTTP/1.1
Accept: application/vnd.featurepipeline.v2+json
```

Used by GitHub's REST API for media types.

**Advantages:**
- REST-purist: the same resource URL serves different representations
- Allows fine-grained media type negotiation

**Disadvantages:**
- Complex to implement and route in FastAPI
- Not supported by many API clients and gateways without custom configuration
- Unfamiliar to most API consumers; generates more support questions

### Decision: URL Path Versioning for the `feature-pipeline` API

```
/v1/features
/v1/pipelines
/v2/features      # introduced when a breaking change is required
```

The decision criteria:

| Criterion | URL path | Header | Content-Type |
|-----------|----------|--------|-------------|
| Visible in logs | ✅ | ❌ | ❌ |
| Works with all clients | ✅ | ⚠️ (Vary header needed) | ❌ |
| Easy to deprecate at gateway | ✅ | ❌ | ❌ |
| REST purity | ❌ | ✅ | ✅ |
| Implementation complexity | Low | Medium | High |

---

## 2. What Counts as a Breaking Change

A breaking change is any change that causes a correctly-implemented client to fail. This includes:

| Change type | Breaking? |
|------------|-----------|
| Removing a field from a response | ✅ Yes |
| Renaming a field | ✅ Yes |
| Changing a field's type (e.g., `string` → `int`) | ✅ Yes |
| Changing a status code (e.g., `200` → `201`) | ✅ Yes |
| Making an optional field required | ✅ Yes |
| Removing an endpoint | ✅ Yes |
| Changing authentication requirements | ✅ Yes |
| Adding a required request field | ✅ Yes |
| Adding a new optional field to a response | ❌ No (forward-compatible) |
| Adding a new optional query parameter | ❌ No |
| Adding a new endpoint | ❌ No |
| Bug fixes that change incorrect behavior | ⚠️ Sometimes (if clients depended on the bug) |

When in doubt: if a client that works against the current API could break after the change without modification, it is breaking.

---

## 3. Maintaining Multiple Versions

### Router Mounting Strategy

Mount version routers separately under the same app:

```python
# src/feature_pipeline/api/main.py
from feature_pipeline.api.routers.v1 import features as v1_features
from feature_pipeline.api.routers.v2 import features as v2_features

def create_app() -> FastAPI:
    app = FastAPI(...)

    app.include_router(v1_features.router, prefix="/v1")
    app.include_router(v2_features.router, prefix="/v2")

    return app
```

### Shared Business Logic

Route handlers are thin. Business logic lives in the domain layer and is version-independent. Version-specific schemas translate between the API surface and the domain:

```
src/feature_pipeline/
├── api/
│   ├── routers/
│   │   ├── v1/
│   │   │   └── features.py    # v1 route handlers
│   │   └── v2/
│   │       └── features.py    # v2 route handlers
│   └── schemas/
│       ├── v1/
│       │   └── features.py    # v1 request/response models
│       └── v2/
│           └── features.py    # v2 request/response models
└── domain/
    └── feature_service.py     # shared — no version concept
```

```python
# api/routers/v1/features.py — v1 handler
from feature_pipeline.api.schemas.v1 import features as v1_schema
from feature_pipeline.domain import FeatureService

@router.get("/{feature_id}", response_model=v1_schema.FeatureResponse)
async def get_feature(
    feature_id: str,
    service: FeatureServiceDep,
) -> v1_schema.FeatureResponse:
    feature = await service.get(feature_id)   # same domain service
    return v1_schema.FeatureResponse(         # v1-specific serialization
        id=feature.id,
        name=feature.name,
        value=feature.value,
    )

# api/routers/v2/features.py — v2 handler
from feature_pipeline.api.schemas.v2 import features as v2_schema

@router.get("/{feature_id}", response_model=v2_schema.FeatureResponse)
async def get_feature(
    feature_id: str,
    service: FeatureServiceDep,
) -> v2_schema.FeatureResponse:
    feature = await service.get(feature_id)   # same domain service
    return v2_schema.FeatureResponse(         # v2 adds metadata field
        id=feature.id,
        name=feature.name,
        value=feature.value,
        metadata=feature.metadata,            # new in v2
    )
```

The domain service is unversioned. Versioning is entirely a concern of the API layer.

### The Additive-First Rule

Before creating a new version, ask whether the change can be made additively:

- Adding an optional response field: **no new version needed** — existing clients ignore unknown fields
- Adding an optional request field: **no new version needed** — existing clients don't send it; server uses default
- Renaming a field: **new version needed** — cannot add both old and new names without confusion

If a change can be made additive, make it additive. Every new version creates a maintenance burden.

---

## 4. Deprecation Signaling

When a version is deprecated, signal it programmatically in every response from that version. Do not rely on documentation alone.

### Standard Deprecation Headers

Defined in [RFC 9745](https://datatracker.ietf.org/doc/html/rfc9745):

```http
HTTP/1.1 200 OK
Deprecation: true
Sunset: Sat, 01 Feb 2025 00:00:00 GMT
Link: <https://api.featurepipeline.internal/v2/features>; rel="successor-version"
Warning: 299 - "This endpoint is deprecated. Migrate to /v2 before 2025-02-01."
```

| Header | Meaning |
|--------|---------|
| `Deprecation: true` | This resource is deprecated |
| `Sunset` | RFC 9745 — the date after which the resource will be unavailable |
| `Link; rel="successor-version"` | Where to find the replacement |
| `Warning: 299` | Free-text deprecation notice |

### Implementing Deprecation Middleware in FastAPI

```python
# src/feature_pipeline/api/middleware.py
from datetime import datetime, timezone
from email.utils import format_datetime
from fastapi import FastAPI, Request, Response

DEPRECATED_PREFIXES: dict[str, datetime] = {
    "/v1/": datetime(2025, 2, 1, tzinfo=timezone.utc),
}

async def deprecation_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)

    for prefix, sunset_date in DEPRECATED_PREFIXES.items():
        if request.url.path.startswith(prefix):
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = format_datetime(sunset_date, usegmt=True)
            response.headers["Link"] = (
                f'<{request.url.scheme}://{request.url.netloc}/v2{request.url.path[len(prefix)-1:]}>; '
                f'rel="successor-version"'
            )
            break

    return response
```

### The Sunset Date Approach

The Sunset date is a commitment, not a target. Once announced:

1. **Announce at least 6 months before sunset** for external APIs; 4–8 weeks for internal APIs
2. **Log every request to deprecated endpoints** — you need to know who is still using them
3. **Contact consumers directly** if you can identify them via API keys or user accounts
4. **Return `410 Gone`** after the sunset date, not `404`. `410` means "this existed and was intentionally removed" — distinct from "never existed"
5. **Do not extend the date** without a strong reason; extensions train consumers to ignore sunset dates

```python
# After sunset date, return 410
async def handle_sunsetted_version(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=410,
        content={
            "error": {
                "code": "API_VERSION_REMOVED",
                "message": "API v1 was retired on 2025-02-01. Migrate to /v2.",
                "docs": "https://docs.featurepipeline.internal/migration/v1-to-v2",
            }
        },
    )
```

---

## 5. Versioning the OpenAPI Spec

Each version has its own OpenAPI spec. Mount separate apps or use prefix-aware spec generation:

```python
# Separate specs accessible at:
# /v1/openapi.json
# /v2/openapi.json
# /docs → tabbed view of all versions

app_v1 = FastAPI(title="Feature Pipeline API v1", version="1.0.0")
app_v2 = FastAPI(title="Feature Pipeline API v2", version="2.0.0")

# Mount as sub-applications
root_app.mount("/v1", app_v1)
root_app.mount("/v2", app_v2)
```

This gives each version its own `/docs` at `/v1/docs` and `/v2/docs` — useful when both versions are active simultaneously.

---

## Summary

| Decision | Recommendation |
|----------|---------------|
| Versioning strategy | URL path versioning (`/v1/`) — explicit, debuggable, gateway-friendly |
| Business logic | Unversioned; lives in domain layer |
| Version-specific code | Request/response schemas and route handlers only |
| Breaking change threshold | Any change that could break a correctly-implemented client |
| Additive changes | No version bump needed |
| Deprecation notice | `Deprecation`, `Sunset`, `Link` headers on every response from deprecated version |
| Sunset commitment | Minimum 6 weeks for internal, 6 months for external; do not extend casually |
| Post-sunset response | `410 Gone` — not `404` |

> **A versioning strategy is a promise to consumers.** The commitment is not just "we will not break you without notice" — it is also "when we say something is going away on a date, we mean that date."
