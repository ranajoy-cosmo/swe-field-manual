# Release Strategies

A deployment is moving code to a server. A release is exposing that code to users. Decoupling deployment from release is the key to safe, low-stress operations.

## Blue/Green Deployment

You maintain two identical production environments: Blue and Green.
1. Traffic routes to Blue.
2. Deploy the new version to Green.
3. Run smoke tests against Green.
4. Flip the router/load balancer to send traffic to Green.

**Pros**: Instant rollback (flip the router back to Blue).
**Cons**: Requires 2x the infrastructure cost. Hard to manage with database schema changes.

## Canary Deployment

Route a small percentage of traffic to the new version to verify stability before a full rollout.
1. Deploy new version to a subset of pods (e.g., 5%).
2. Monitor error rates and latency (SLOs) for 15 minutes.
3. If stable, increase to 20%, then 50%, then 100%.
4. If errors spike, automatically rollback to 0%.

**Pros**: Limits the blast radius of a bad release.
**Cons**: Requires sophisticated metrics and load balancing (often via a Service Mesh like Istio).

## Rolling Deployment

The default in Kubernetes. Replace instances one at a time.
1. Bring up a new pod.
2. Wait for it to pass readiness probes.
3. Shut down an old pod.
4. Repeat until all pods are replaced.

**Pros**: No extra infrastructure cost.
**Cons**: Rollback takes time (you have to roll backward, replacing pods one by one).

## Feature Flags

The ultimate way to decouple deployment from release. Ship code to production hidden behind a flag.

```python
# src/feature_pipeline/api/routes.py
from flagsmith import Flagsmith

flagsmith = Flagsmith(environment_key="<your-key>")

@router.post("/predict")
def predict(data: dict):
    flags = flagsmith.get_environment_flags()
    
    if flags.is_feature_enabled("use_v2_model"):
        return model_v2.predict(data)
    else:
        return model_v1.predict(data)
```

Feature flags allow you to:
- Merge incomplete code to `main` without breaking production.
- Turn a feature on for a specific subset of users (e.g., internal employees only).
- Instantly "rollback" a feature in milliseconds without running a deployment pipeline.

## Database Migrations and Deployments

The hardest part of any release strategy is state. You cannot do a Blue/Green deployment if the new code requires a dropped column.

**The Rule: Database migrations must always be backward compatible with the currently running code.**

To rename a column:
1. **Deploy 1**: Add the new column. Update code to write to both, read from old.
2. **Backfill**: Copy data from old to new.
3. **Deploy 2**: Update code to read from new, write to new.
4. **Deploy 3**: Drop the old column.

Never run database migrations automatically on application startup in production. Run them as a separate step in the CI/CD pipeline (e.g., a Kubernetes Job or a GitHub Action) *before* the application deployment begins.

## Summary

| Strategy | When to Use | Trade-off |
|----------|-------------|-----------|
| Blue/Green | Critical services, zero downtime required | High infrastructure cost. |
| Canary | High traffic services, ML model rollouts | Requires advanced observability and traffic shaping. |
| Rolling | Standard web services (K8s default) | Slow rollbacks. |
| Feature Flags | Complex features, risky changes | Introduces technical debt (flags must be cleaned up). |
