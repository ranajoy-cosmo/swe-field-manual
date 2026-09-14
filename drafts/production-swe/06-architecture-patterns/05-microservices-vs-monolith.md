# Microservices vs. Monolith

The decision to split a system into microservices is an organizational one as much as a technical one. Prematurely splitting a monolith leads to the "distributed monolith" anti-pattern, where services must be deployed together but suffer all the penalties of network latency.

## Start with a Modular Monolith

By default, start with a modular monolith. This is a single deployed application with strict internal boundaries (see [Layered Architecture](01-layered-architecture.md)). 

Benefits:
- Single repository, single CI/CD pipeline
- Refactoring across domains is just moving files, not breaking API contracts
- No network latency between components
- Simple end-to-end testing

## Signs You Need to Extract a Service

Do not extract a microservice because a feature is "logically separate". Extract a service when you face one of these hard constraints:

1. **Independent Deployability**: Team A ships daily; Team B ships quarterly. A single monolith slows Team A down.
2. **Different Scaling Profiles**: The ML inference engine needs expensive GPU nodes and auto-scales wildly based on traffic. The admin dashboard needs one CPU node. They shouldn't be deployed together.
3. **Technology Incompatibility**: The data processing pipeline must run in PySpark, but the API is built in FastAPI.
4. **Security Boundaries**: Payment processing code needs strict isolation from general user profile code.

## The Distributed Systems Tax

When you split a service, you immediately incur taxes that you must pay:

- **Network Latency**: In-process calls take nanoseconds. HTTP calls take milliseconds.
- **Partial Failures**: What happens when Service A calls Service B, but Service B times out? You now need retries, circuit breakers, and fallback logic.
- **Eventual Consistency**: You can no longer use a single database transaction. You must handle distributed transactions (e.g., Saga pattern) or accept eventual consistency.
- **Observability Overhead**: You must implement distributed tracing (OpenTelemetry) to track a request across services.

## The Strangler Fig Pattern

When extracting a service from a monolith, never do a "big bang" rewrite. Use the Strangler Fig pattern:

1. **Identify the seam**: Choose a module in the monolith with clear boundaries.
2. **Build the new service**: Implement the functionality in the new microservice.
3. **Route traffic**: Update the API gateway or monolith to route requests for that specific functionality to the new service.
4. **Deprecate**: Remove the old code from the monolith.

```text
       API Gateway
       /         \
   Monolith    New Service
  (Legacy)     (Extracted)
```

## ML Team Considerations

For ML Infrastructure, certain splits are almost always necessary due to differing constraints:

- **Model Training**: A batch process that requires massive compute and runs for hours. Must be separate from the API.
- **Model Serving**: Requires low-latency, high-throughput, and often GPU acceleration. Often separated from the main business API.
- **Feature Computation (Batch)**: Spark/Ray jobs running on a schedule.

However, splitting the "business logic" API into smaller microservices (e.g., `User-Service`, `Project-Service`) is rarely beneficial for a small-to-medium ML engineering team.

## Summary

| Decision | Recommendation | Reason |
|----------|----------------|--------|
| Default Architecture | Modular Monolith | Maximizes development speed and refactoring ease while maintaining boundaries. |
| When to Split | Hard constraints only | Scale profiles, team boundaries, or tech stack incompatibilities justify the distributed tax. |
| Migration Strategy | Strangler Fig | Reduces risk by incrementally routing traffic to the new service. |
| ML Serving | Separate Service | Inference compute requirements differ fundamentally from standard API web traffic. |
