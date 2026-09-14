# Chapter 03 — Testing

> *Tests are not a quality gate you pass at the end. They are a design tool you use throughout.*

This chapter is Python-specific and production-focused. The goal is not to explain what a test is — it's to show how to structure a test suite that scales with a real codebase, catches the bugs that actually occur, and runs fast enough that developers run it.

## What This Chapter Covers

| File | Topic |
|------|-------|
| [01-philosophy-and-pyramid.md](./01-philosophy-and-pyramid.md) | Test pyramid, confidence vs coverage, what to test and what not to |
| [02-pytest-core.md](./02-pytest-core.md) | Fixtures (scopes, factories, conftest), parametrize, marks, configuration |
| [03-mocking-and-isolation.md](./03-mocking-and-isolation.md) | When and how to mock; mock strategies; common pitfalls |
| [04-integration-testing.md](./04-integration-testing.md) | Testing against real databases and services; testcontainers; docker fixtures |
| [05-async-testing.md](./05-async-testing.md) | pytest-asyncio, async fixtures, testing FastAPI and async workers |
| [06-contract-testing.md](./06-contract-testing.md) | Consumer-driven contracts with Pact; API boundary testing |
| [07-property-based-testing.md](./07-property-based-testing.md) | Hypothesis strategies, stateful testing, ML data property tests |
| [08-testing-ml-code.md](./08-testing-ml-code.md) | Data validation tests, model behavioral tests, pipeline smoke tests |
| [09-coverage-and-ci.md](./09-coverage-and-ci.md) | Coverage configuration, CI matrix, test parallelism, performance tests |

## The Running Example

All code examples in this chapter are drawn from a hypothetical `feature-pipeline` service — an ML feature computation and serving system. It has:

- A **feature store** backed by Redis
- A **data ingestion pipeline** that reads from GCS and writes to BigQuery
- A **FastAPI** REST API for serving features
- A **preprocessing library** shared across teams

This gives concrete context for each type of test.

## Reading Order

Read 01 → 02 → 03 in sequence. After that, 04–09 are largely independent and can be read in any order based on need.
