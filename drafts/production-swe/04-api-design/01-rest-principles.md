# 01 — REST Principles

## Why REST Principles Are Not Just Style

REST is not a standard — it is an architectural style described by Roy Fielding in his 2000 dissertation. Most APIs called "REST APIs" are actually HTTP APIs that adopt some REST conventions selectively. That is fine in practice. What matters is that the conventions adopted are adopted *consistently*, so consumers can form accurate mental models of how the API behaves.

The cost of an inconsistently designed API is paid continuously: in client-side error handling that must special-case unusual behaviors, in documentation that can never be accurate because behavior varies, and in onboarding time for every new engineer who must learn the API's idiosyncrasies rather than applying domain knowledge.

The goal of this section is not to be religiously REST-compliant. It is to establish a small set of durable conventions that make the `feature-pipeline` API — and APIs like it — predictable.

---

## 1. Resources, Not Actions

The central discipline of REST is modeling operations as **resources** (nouns) rather than **actions** (verbs).

### The Noun/Verb Test

The action is always expressed by the HTTP method. The URL identifies the resource being acted upon. If your URL contains a verb, the HTTP method is probably wrong.

```
# Bad: verbs in URLs
POST /api/getFeatures
POST /api/createFeatureSet
POST /api/deleteFeatureSet?id=123
GET  /api/computeFeatureValues

# Good: nouns in URLs, verbs in HTTP methods
GET    /v1/features
POST   /v1/feature-sets
DELETE /v1/feature-sets/{id}
POST   /v1/features/{id}/computations   # action on a sub-resource is acceptable
```

The last example (`/computations`) is a pragmatic exception: when an operation is genuinely not a CRUD action — like triggering a computation, sending a notification, or initiating a workflow — a sub-resource noun is cleaner than forcing it into a method mismatch.

### Resource Naming Conventions

- **Plural nouns** for collections: `/features`, `/feature-sets`, `/pipelines`
- **Kebab-case** for multi-word resources: `/feature-sets`, not `/featureSets` or `/feature_sets`
- **Singular noun** for singleton resources: `/v1/pipelines/{id}/config` (a pipeline has exactly one config)
- **Consistent nesting depth**: no more than two levels of nesting (`/resources/{id}/sub-resources/{id}`)

Deeper nesting is a sign that a resource should be promoted to top-level:

```
# Bad: three levels deep — the feature_value could stand alone
GET /v1/pipelines/{pipeline_id}/feature-sets/{set_id}/feature-values/{value_id}

# Good: promote to top level with filtering
GET /v1/feature-values/{value_id}
GET /v1/feature-values?pipeline_id=abc&feature_set_id=xyz
```

---

## 2. HTTP Method Semantics

Each HTTP method carries a specific semantic contract. Using the wrong method breaks consumer assumptions about caching, retrying, and idempotency.

| Method | Semantics | Idempotent | Safe | Body |
|--------|-----------|-----------|------|------|
| `GET` | Retrieve a resource or collection | Yes | Yes | No |
| `POST` | Create a new resource or trigger an action | No | No | Yes |
| `PUT` | Replace a resource entirely | Yes | No | Yes |
| `PATCH` | Partially update a resource | No | No | Yes |
| `DELETE` | Remove a resource | Yes | No | No |
| `HEAD` | Like GET but without response body (for existence checks) | Yes | Yes | No |

### Common Misuses

**POST for everything.**
Seen most often in RPC-style APIs. The problem: clients cannot safely retry POSTs (not idempotent). Infrastructure (load balancers, service meshes) treats GET/HEAD as safe to retry automatically. A POST-for-everything API must implement its own idempotency layer (see file 06).

**GET with a request body.**
Technically permitted by HTTP/1.1, but:
- Many HTTP clients and proxies strip GET request bodies
- Caches cannot cache GET requests with varying bodies
- OpenAPI/FastAPI do not support request bodies on GET endpoints

If a `GET` operation requires complex filtering that can't fit in query parameters, use `POST` to a search endpoint:
```
POST /v1/features/search
{ "filters": {...}, "sort": [...] }
```

**PUT when you mean PATCH.**
`PUT` replaces the *entire resource*. If a client sends `PUT /v1/feature-sets/{id}` with only a `name` field, all other fields should be reset to defaults. If that is not the intent, use `PATCH`.

**DELETE returning the deleted resource.**
`DELETE` should return `204 No Content`. Returning the deleted body in a `200` response creates ambiguity about whether the resource still exists.

---

## 3. Status Codes That Matter

Most APIs need about 12 status codes. Knowing exactly when each applies removes ambiguity for API consumers.

### 2xx — Success

| Code | When to use |
|------|-------------|
| `200 OK` | Successful GET, PATCH, PUT. Response body contains the resource. |
| `201 Created` | Successful POST that created a resource. Include a `Location` header pointing to the new resource. |
| `202 Accepted` | Request accepted for async processing. The operation is not yet complete. Include a `Location` for polling. |
| `204 No Content` | Successful DELETE, or a POST/PUT where no response body is needed. |

### 4xx — Client Error

| Code | When to use |
|------|-------------|
| `400 Bad Request` | Malformed request syntax (invalid JSON, missing required field at the HTTP level). |
| `401 Unauthorized` | Missing or invalid authentication credentials. The client should authenticate and retry. |
| `403 Forbidden` | Authentication is valid, but the client does not have permission for this resource. Do not retry — fix permissions. |
| `404 Not Found` | Resource does not exist. Also use for resources the client should not know about (to avoid information leakage). |
| `409 Conflict` | State conflict — e.g., a duplicate unique key, a version mismatch (optimistic lock failure). |
| `422 Unprocessable Entity` | Request is syntactically valid but semantically invalid (business rule violation, Pydantic validation failure). |
| `429 Too Many Requests` | Rate limit exceeded. Include `Retry-After` header. |

**`401` vs. `403`** — the distinction matters:
- `401`: "I don't know who you are." The client should re-authenticate (e.g., refresh token, send API key).
- `403`: "I know who you are, and you can't do this." Re-authenticating will not help.

**`422` vs. `400`** — FastAPI returns `422` for Pydantic validation failures by default:
- `400`: request is broken at the protocol level (can't even parse the JSON)
- `422`: request is parseable but fails business validation (field out of range, invalid enum value)

### 5xx — Server Error

| Code | When to use |
|------|-------------|
| `500 Internal Server Error` | Unhandled exception. The client should retry with backoff. |
| `503 Service Unavailable` | Intentional unavailability — maintenance, overload. Include `Retry-After`. |

Never expose stack traces in 5xx responses. Log them server-side; return a correlation ID the client can report.

---

## 4. URL Structure

### Path Versioning

```
/v1/features
/v1/feature-sets/{id}
/v2/features          # breaking change — new version
```

Full discussion of versioning strategies is in file `03-api-versioning.md`. The short position: path versioning is the default. It is explicit, debuggable in logs, and supported by every HTTP client and proxy without special handling.

### Query Parameter Conventions

| Purpose | Convention | Example |
|---------|------------|---------|
| Filtering | `?field=value` | `?pipeline_id=abc&status=active` |
| Sorting | `?sort=field` or `?sort=-field` (descending) | `?sort=-created_at` |
| Pagination (offset) | `?page=2&page_size=50` | |
| Pagination (cursor) | `?cursor=<opaque_string>&limit=50` | |
| Field selection | `?fields=id,name,value` | |
| Search | `?q=text` | |

Rules:
- Query parameters are `snake_case`
- Boolean query parameters accept `true`/`false` strings (Pydantic handles coercion)
- Do not encode complex objects in query strings — use a POST body for that

### Path Parameters

Path parameters identify a specific resource. They are always required:
```
/v1/features/{feature_id}
/v1/feature-sets/{set_id}/features/{feature_id}
```

Use the resource name as the prefix for the ID parameter: `feature_id`, not just `id`. This prevents confusion in nested routes where multiple IDs appear.

---

## 5. Request and Response Envelope Conventions

### The Flat vs. Wrapped Debate

Two common response conventions exist:

**Flat** — the resource is the response body directly:
```json
GET /v1/features/abc
{
  "id": "abc",
  "name": "user_age",
  "value": 42,
  "created_at": "2024-01-15T10:00:00Z"
}
```

**Wrapped** — the resource is nested under a key:
```json
GET /v1/features/abc
{
  "data": {
    "id": "abc",
    "name": "user_age",
    "value": 42,
    "created_at": "2024-01-15T10:00:00Z"
  }
}
```

**Recommendation: flat for single resources, wrapped for collections.**

The `data` envelope on collections allows the response to carry pagination metadata alongside the items without putting metadata inside items:

```json
GET /v1/features?pipeline_id=abc
{
  "data": [
    { "id": "1", "name": "user_age", "value": 42 },
    { "id": "2", "name": "session_count", "value": 7 }
  ],
  "pagination": {
    "next_cursor": "eyJpZCI6IjIifQ==",
    "has_more": true,
    "total": 150
  }
}
```

### Error Responses

Standardize error response shape across the entire API:

```json
{
  "error": {
    "code": "FEATURE_NOT_FOUND",
    "message": "Feature 'user_age' does not exist in pipeline 'abc'.",
    "details": {
      "feature_id": "user_age",
      "pipeline_id": "abc"
    },
    "request_id": "req_01hx..."
  }
}
```

| Field | Purpose |
|-------|---------|
| `code` | Machine-readable error code. Use `SCREAMING_SNAKE_CASE`. |
| `message` | Human-readable description. Write for the developer who will read logs. |
| `details` | Optional structured context — helps diagnose the issue without reading server logs. |
| `request_id` | Correlation ID for linking to server-side logs (Chapter 08). |

---

## 6. HATEOAS

HATEOAS (Hypermedia As The Engine Of Application State) means including links in responses that tell clients what operations are available next:

```json
{
  "id": "abc",
  "name": "user_age",
  "value": 42,
  "_links": {
    "self": { "href": "/v1/features/abc" },
    "pipeline": { "href": "/v1/pipelines/xyz" },
    "history": { "href": "/v1/features/abc/history" }
  }
}
```

**When HATEOAS is worth it:**
- The API has a rich graph of related resources that clients need to traverse
- You want clients to be resilient to URL structure changes (clients follow links, not hardcoded paths)
- You are building a general-purpose API with unknown consumer diversity

**When HATEOAS is overhead:**
- Internal service-to-service APIs with a small, known set of clients
- APIs where consumer code is co-deployed and updated with the API
- Teams without bandwidth to maintain accurate `_links` in every response

For ML infrastructure internal APIs, HATEOAS is usually overhead. The `feature-pipeline` API does not use it.

---

## Summary

| Principle | Rule |
|-----------|------|
| URL design | Plural nouns, kebab-case, max two nesting levels |
| Method semantics | GET=retrieve, POST=create/action, PUT=replace, PATCH=update, DELETE=remove |
| Status codes | Use the exact code — 401 vs 403, 400 vs 422, 200 vs 204 all have different semantics |
| Response shape | Flat for single resources; `{ "data": [...], "pagination": {...} }` for collections |
| Error shape | Standardize: `code`, `message`, `details`, `request_id` in every error response |
| HATEOAS | Skip for internal APIs; consider for general-purpose public APIs |

> **The sign of a well-designed API:** a new client engineer can build an integration against it using only the API documentation, without needing to ask how any edge case behaves.
