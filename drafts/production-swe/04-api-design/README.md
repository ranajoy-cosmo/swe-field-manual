# Chapter 04 — API Design

> *An API is a contract. Breaking it silently is a bug; breaking it loudly is a feature.*

An API is the boundary between your code and everyone else's. Unlike internal code — which only you maintain — an API has consumers: other services, other teams, mobile clients, external partners. Changing it carelessly breaks things you can't directly fix. Designing it carefully is one of the highest-leverage decisions in production software.

This chapter covers HTTP API design from first principles through FastAPI implementation, versioning strategy, authentication models, query design patterns, and the correctness properties (idempotency, safety) that make APIs safe to use under failure.

The running example throughout is the `feature-pipeline` serving API: a service that stores computed features, retrieves them for model inference, and exposes a management surface for feature definitions.

## What This Chapter Covers

| File | Topic |
|------|-------|
| [01-rest-principles.md](./01-rest-principles.md) | REST semantics, HTTP methods, status codes, URL design, response envelopes |
| [02-fastapi-in-depth.md](./02-fastapi-in-depth.md) | Routers, dependency injection, validation, middleware, lifespan, OpenAPI |
| [03-api-versioning.md](./03-api-versioning.md) | Versioning strategies, multi-version maintenance, deprecation signaling |
| [04-authentication-and-authorization.md](./04-authentication-and-authorization.md) | API keys, JWT, OAuth2, RBAC, security anti-patterns |
| [05-pagination-filtering-and-sorting.md](./05-pagination-filtering-and-sorting.md) | Cursor vs. offset pagination, filter design, sorting conventions, field selection |
| [06-idempotency-and-safety.md](./06-idempotency-and-safety.md) | Idempotency keys, ETag/If-Match, retry contracts, upsert patterns |

## Reading Order

Read `01` → `02` as a unit: REST principles define what a well-designed API looks like; FastAPI is how you implement it in Python. Read `03` (versioning) before `04` (auth) — versioning affects route structure that auth then protects. Files `05` and `06` are standalone and can be read in any order.

## Prerequisites

- Python 3.10+ and FastAPI basics (routes, path operations)
- Chapter 01 — Foundations: typing, Pydantic v2
- Chapter 02 — Tooling: project layout, `uv`

## What This Chapter Deliberately Omits

- **gRPC / Protocol Buffers**: a separate design space; covered by the same principles but different tooling
- **GraphQL**: high-complexity, different trade-off profile; warrants its own chapter
- **Database persistence for API endpoints**: Chapter 05 — Data and Persistence
- **Rate limiting infrastructure**: Chapter 09 — Deployment and Infrastructure
- **Distributed tracing for APIs**: Chapter 08 — Observability
