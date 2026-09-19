# 05 — Pagination, Filtering, and Sorting

## Why Query Design Is a First-Class API Concern

Collection endpoints are the hardest part of an API to design well. They expose the most combinatorial surface (any filter combined with any sort combined with any pagination state), have the highest performance risk (unbounded queries against large tables), and are the most frequently misused by clients (fetching everything and filtering in-process).

Good query design moves computation to the right layer (the database, not the client), provides consistent behavior across endpoints, and makes the API safe to evolve without breaking consumers.

---

## 1. Pagination

Returning all records from a collection endpoint is a denial-of-service vector and a performance antipattern. Pagination is not optional for any collection that can grow beyond a few hundred records.

### Offset Pagination

The simplest approach. The client specifies a page number and a page size:

```
GET /v1/features?page=3&page_size=50
```

**Implementation:**

```python
# src/feature_pipeline/api/schemas/pagination.py
from pydantic import BaseModel, Field

class OffsetPaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size

class OffsetPaginationResponse[T](BaseModel):
    data: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool
```

```python
# Route handler
@router.get("/", response_model=OffsetPaginationResponse[FeatureResponse])
async def list_features(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    service: FeatureServiceDep = ...,
) -> OffsetPaginationResponse[FeatureResponse]:
    params = OffsetPaginationParams(page=page, page_size=page_size)
    features, total = await service.list(offset=params.offset, limit=params.limit)

    return OffsetPaginationResponse(
        data=[FeatureResponse.model_validate(f) for f in features],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=-(-total // page_size),  # ceiling division
        has_next=page * page_size < total,
        has_previous=page > 1,
    )
```

**Limitations of offset pagination:**
- **Inconsistent under mutation:** if a record is inserted between page 1 and page 2 fetches, some records shift — the client sees a duplicate or misses a record
- **Performance degrades at high offsets:** `SELECT ... OFFSET 10000 LIMIT 50` scans 10,050 rows to return 50
- **Total count is expensive:** `COUNT(*)` on large tables with complex filters can be slow

**Use offset pagination when:**
- The dataset is relatively stable (records are not inserted or deleted between page fetches)
- Total count is needed for UI purposes (page count, total results display)
- The dataset is small enough that high-offset queries are not a performance concern

### Cursor-Based Pagination

The server encodes the position of the last returned record into an opaque cursor. The client passes the cursor to get the next page:

```
GET /v1/features?limit=50
→ { "data": [...], "next_cursor": "eyJpZCI6IjUwIn0=", "has_more": true }

GET /v1/features?cursor=eyJpZCI6IjUwIn0=&limit=50
→ { "data": [...], "next_cursor": "eyJpZCI6IjEwMCJ9", "has_more": true }

GET /v1/features?cursor=eyJpZCI6IjEwMCJ9&limit=50
→ { "data": [...], "next_cursor": null, "has_more": false }
```

**Implementation:**

```python
import base64
import json
from pydantic import BaseModel

class Cursor(BaseModel):
    """Internal cursor state. Opaque to clients."""
    last_id: str
    last_created_at: str  # for stable sort ordering

def encode_cursor(last_id: str, last_created_at: str) -> str:
    payload = Cursor(last_id=last_id, last_created_at=last_created_at)
    return base64.urlsafe_b64encode(payload.model_dump_json().encode()).decode()

def decode_cursor(cursor: str) -> Cursor:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        return Cursor.model_validate_json(raw)
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {exc}") from exc

class CursorPaginationResponse[T](BaseModel):
    data: list[T]
    next_cursor: str | None
    has_more: bool
```

```python
@router.get("/", response_model=CursorPaginationResponse[FeatureResponse])
async def list_features(
    cursor: Annotated[str | None, Query(description="Pagination cursor.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    service: FeatureServiceDep = ...,
) -> CursorPaginationResponse[FeatureResponse]:
    cursor_state = decode_cursor(cursor) if cursor else None
    features = await service.list_after_cursor(cursor=cursor_state, limit=limit + 1)

    has_more = len(features) > limit
    page_items = features[:limit]

    next_cursor = None
    if has_more and page_items:
        last = page_items[-1]
        next_cursor = encode_cursor(last.id, last.created_at.isoformat())

    return CursorPaginationResponse(
        data=[FeatureResponse.model_validate(f) for f in page_items],
        next_cursor=next_cursor,
        has_more=has_more,
    )
```

The `limit + 1` trick: fetch one extra record. If it exists, there are more pages. Avoids an extra `COUNT` query.

**The cursor must encode a stable, ordered position.** Sorting by `(created_at DESC, id DESC)` gives a stable order even when `created_at` timestamps collide.

**Use cursor pagination when:**
- The dataset is large (millions of records)
- Records are frequently inserted or deleted during pagination
- Total count is not required
- Real-time streams of data are being paginated

### Choosing Between Offset and Cursor

| Criterion | Offset | Cursor |
|-----------|--------|--------|
| Total count needed | ✅ | ❌ (expensive) |
| Consistent under mutation | ❌ | ✅ |
| Deep page performance | ❌ | ✅ |
| Arbitrary page jump | ✅ | ❌ |
| Simplicity | High | Medium |

**Recommendation for the `feature-pipeline` API:**
- Feature listing (high volume, real-time writes): cursor pagination
- Pipeline listing (low volume, stable): offset pagination

---

## 2. Filtering

### Query Parameter Design

Use flat query parameters for filtering. Each parameter filters on one field:

```
GET /v1/features?pipeline_id=abc&status=active&created_after=2024-01-01T00:00:00Z
```

**Pydantic coercion handles type conversion:**

```python
from datetime import datetime
from enum import StrEnum

class FeatureStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    PENDING = "pending"

@router.get("/")
async def list_features(
    pipeline_id: Annotated[str | None, Query(description="Filter by pipeline.")] = None,
    status: Annotated[FeatureStatus | None, Query(description="Filter by status.")] = None,
    created_after: Annotated[datetime | None, Query(description="ISO 8601 timestamp.")] = None,
    created_before: Annotated[datetime | None, Query(description="ISO 8601 timestamp.")] = None,
    service: FeatureServiceDep = ...,
) -> CursorPaginationResponse[FeatureResponse]:
    ...
```

FastAPI + Pydantic handles `?status=active` → `FeatureStatus.ACTIVE` and `?created_after=2024-01-01T00:00:00Z` → `datetime` automatically.

### Limiting the Filter Surface

Do not expose every database column as a filterable parameter. Filters become implicit indexes — if a field is filterable without a database index, the query will do a full table scan.

**Rules:**
1. Only expose filters for indexed columns
2. Document which combinations are efficient (or restrict them at the API layer)
3. Require at least one selective filter for queries on very large tables

```python
# Enforce a required high-cardinality filter before allowing others
@router.get("/")
async def list_features(
    pipeline_id: Annotated[str, Query(description="Required. Filter by pipeline.")],
    # Optional secondary filters:
    status: Annotated[FeatureStatus | None, Query()] = None,
) -> CursorPaginationResponse[FeatureResponse]:
    # pipeline_id is required — this is enforced by Pydantic (no default)
    ...
```

### Complex Filters via POST

When filtering logic is too complex for query parameters (nested conditions, OR clauses, range arrays), use a dedicated search endpoint:

```python
class FeatureSearchRequest(BaseModel):
    pipeline_ids: list[str] | None = None
    statuses: list[FeatureStatus] | None = None
    name_pattern: str | None = Field(
        default=None,
        description="SQL LIKE pattern, e.g. 'user_%'",
        max_length=64,
    )
    value_range: tuple[float, float] | None = None
    created_between: tuple[datetime, datetime] | None = None

@router.post("/search", response_model=CursorPaginationResponse[FeatureResponse])
async def search_features(
    body: FeatureSearchRequest,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    service: FeatureServiceDep = ...,
) -> CursorPaginationResponse[FeatureResponse]:
    ...
```

Note: this endpoint uses `POST` because the filter state is in the body, not for RPC reasons. This is a pragmatic REST trade-off, not an anti-pattern.

---

## 3. Sorting

### The Convention

```
?sort=field            # ascending
?sort=-field           # descending (leading minus)
?sort=-created_at,name # multi-field: created_at desc, name asc
```

This convention (from JSON:API) is compact and readable. The leading `-` for descending order is less ambiguous than `?order=desc&sort_by=created_at`.

**Implementation:**

```python
from enum import StrEnum

class SortField(StrEnum):
    NAME = "name"
    CREATED_AT = "created_at"
    VALUE = "value"

def parse_sort(sort_param: str) -> list[tuple[SortField, bool]]:
    """Parse '?sort=-created_at,name' into [(created_at, DESC), (name, ASC)]."""
    result = []
    for part in sort_param.split(","):
        part = part.strip()
        if part.startswith("-"):
            field_name = part[1:]
            descending = True
        else:
            field_name = part
            descending = False

        try:
            field = SortField(field_name)
        except ValueError:
            raise ValueError(f"Invalid sort field: '{field_name}'. Allowed: {list(SortField)}")

        result.append((field, descending))
    return result

@router.get("/")
async def list_features(
    sort: Annotated[str, Query(description="Sort fields. Prefix with '-' for descending.")] = "-created_at",
    service: FeatureServiceDep = ...,
) -> CursorPaginationResponse[FeatureResponse]:
    sort_spec = parse_sort(sort)
    ...
```

### Allowlist vs. Arbitrary Sort

**Always use an allowlist.** Arbitrary sort fields mapped directly to SQL column names are a SQL injection risk and a performance risk (sorting on an unindexed column causes a full table scan).

```python
# Bad: user-controlled column name in SQL
ORDER BY {user_provided_field}  # SQL injection risk

# Good: allowlist enforced at the schema level
class SortField(StrEnum):
    NAME = "name"
    CREATED_AT = "created_at"

# SortField(user_input) raises ValueError if not in the enum
```

---

## 4. Field Selection (Sparse Fieldsets)

Field selection allows clients to request only the fields they need, reducing response payload size:

```
GET /v1/features?fields=id,name,value
→ { "data": [{ "id": "abc", "name": "user_age", "value": 42 }] }
```

### When Field Selection Is Worth Implementing

**Worth it:**
- Responses are large (many fields, deeply nested)
- Mobile clients on constrained bandwidth
- High-volume endpoints where payload size matters

**Not worth it:**
- Small, simple responses (< 5 fields)
- Internal service-to-service APIs where the client schema is controlled

### Implementation

```python
from pydantic import BaseModel

class FeatureResponse(BaseModel):
    id: str
    name: str
    value: float | int | str | bool
    pipeline_id: str
    created_at: datetime
    expires_at: datetime | None = None
    tags: list[str] = []
    metadata: dict[str, str] = {}

ALLOWED_FIELDS = frozenset(FeatureResponse.model_fields.keys())

def apply_field_selection(
    data: FeatureResponse,
    fields: set[str],
) -> dict:
    """Return only the requested fields from the response model."""
    if not fields:
        return data.model_dump(exclude_none=True)

    invalid = fields - ALLOWED_FIELDS
    if invalid:
        raise ValueError(f"Invalid fields requested: {invalid}. Allowed: {ALLOWED_FIELDS}")

    return data.model_dump(include=fields, exclude_none=True)

@router.get("/{feature_id}")
async def get_feature(
    feature_id: str,
    fields: Annotated[
        str | None,
        Query(description="Comma-separated field names, e.g. 'id,name,value'")
    ] = None,
    service: FeatureServiceDep = ...,
) -> dict:  # return dict when field selection is active
    feature = await service.get(feature_id)
    response = FeatureResponse.model_validate(feature)

    requested_fields = {f.strip() for f in fields.split(",")} if fields else set()
    return apply_field_selection(response, requested_fields)
```

---

## Summary

| Decision | Recommendation |
|----------|---------------|
| Pagination default | Cursor for large/mutable collections; offset when total count is needed |
| Cursor encoding | Base64-encoded JSON with stable sort anchor (e.g., `id + created_at`) |
| Filter parameters | Flat query params; allowlist indexed fields only |
| Complex filters | `POST /search` with a structured request body |
| Sort convention | `?sort=field` (asc), `?sort=-field` (desc); comma-separated for multi-field |
| Sort allowlist | Use `StrEnum` to enforce allowed sort fields |
| Field selection | Implement for large payloads; skip for small internal APIs |
| Max page size | Enforce a hard cap (e.g., `le=500`); never allow unbounded |

> **The most dangerous collection endpoint is one with no limit and no index-backed filter.** A single client calling `GET /features` with no parameters against a 50M-row table will bring down the service. Default limits and required filters are not optional constraints — they are the first line of defense.
