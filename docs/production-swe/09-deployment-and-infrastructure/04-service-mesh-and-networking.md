# 04 — Service Mesh and Networking

## What a Service Mesh Provides

In a system with more than one service, inter-service communication is infrastructure. Without a service mesh, each service must implement:

- **mTLS**: mutual TLS to authenticate both sides of every connection
- **Retries**: retry logic with backoff for transient failures
- **Timeouts**: per-route timeout enforcement
- **Circuit breaking**: stop sending requests to a failing service
- **Traffic splitting**: route fractions of traffic to different versions
- **Observability**: request traces, service-level metrics, traffic topology

Without a mesh, this logic is either duplicated in every service or omitted entirely. A service mesh moves it to the infrastructure layer — the application remains ignorant of the network policy, and the policy is consistently applied across all services.

Istio is the dominant service mesh. It injects an Envoy proxy sidecar alongside each pod. All traffic in and out of the pod passes through the sidecar — the application binds to `localhost` and speaks to a local proxy, which handles the mesh concerns.

---

## 1. Istio Basics

### Installation and Namespace Configuration

```bash
# Install Istio with the default profile (production uses 'default' or 'production' profile)
istioctl install --set profile=default -y

# Enable automatic sidecar injection for a namespace
kubectl label namespace production istio-injection=enabled
```

With injection enabled, every new pod in the `production` namespace gets an Envoy sidecar automatically. No change to the application manifest is required.

### PeerAuthentication: Enforcing mTLS

```yaml
# k8s/istio/peer-authentication.yaml
# Enforce mTLS for all services in the production namespace
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata:
  name: default
  namespace: production
spec:
  mtls:
    mode: STRICT  # Only encrypted, authenticated connections accepted
                  # PERMISSIVE allows both mTLS and plain text (for migration)
```

In STRICT mode, any unencrypted connection to a pod in this namespace is rejected. This protects against network-level eavesdropping and ensures service identity is verified on every request.

---

## 2. Traffic Management: VirtualService and DestinationRule

These two objects work together. `DestinationRule` defines the properties of a destination (subsets, load balancing, connection pool). `VirtualService` defines the routing rules.

### DestinationRule: Defining Subsets

```yaml
# k8s/istio/destination-rule.yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: feature-pipeline
  namespace: production
spec:
  host: feature-pipeline.production.svc.cluster.local
  trafficPolicy:
    loadBalancer:
      simple: LEAST_CONN   # Route to the pod with fewest active requests
    connectionPool:
      tcp:
        maxConnections: 100
      http:
        http2MaxRequests: 1000
        maxRequestsPerConnection: 10
  subsets:
    - name: stable
      labels:
        version: stable
    - name: canary
      labels:
        version: canary
```

Pods are assigned to subsets via their labels. The Kubernetes Deployment for the canary version would carry `labels: { version: canary }`.

### VirtualService: Routing Rules

```yaml
# k8s/istio/virtual-service-canary.yaml
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: feature-pipeline
  namespace: production
spec:
  hosts:
    - feature-pipeline
  http:
    # Route based on a header first — useful for internal testing
    - match:
        - headers:
            x-canary:
              exact: "true"
      route:
        - destination:
            host: feature-pipeline
            subset: canary
          weight: 100

    # Default: 90/10 traffic split
    - route:
        - destination:
            host: feature-pipeline
            subset: stable
          weight: 90
        - destination:
            host: feature-pipeline
            subset: canary
          weight: 10
```

The header-based match allows internal users or QA automation to force canary routing (`X-Canary: true`) before the percentage-based rollout starts.

### Retries and Timeouts

```yaml
# In the VirtualService http route spec
http:
  - route:
      - destination:
          host: feature-pipeline
          subset: stable
    timeout: 5s          # Abort the request if it takes longer than 5 seconds
    retries:
      attempts: 3        # Retry up to 3 times
      perTryTimeout: 2s  # Each attempt has its own 2s timeout
      retryOn: "gateway-error,connect-failure,retriable-4xx"
      # retriable-4xx: retries on 429 (rate limit); does NOT retry 400/422
```

`retryOn: "retriable-4xx"` is critical to get right. Retrying on 422 Unprocessable Entity (a client error in the request body) would waste resources and obscure bugs. Only `429` (rate limit — a transient condition) is safe to retry among 4xx codes.

---

## 3. Circuit Breakers: Outlier Detection

A circuit breaker stops sending requests to pods that are failing. Istio calls this "outlier detection" — it tracks error rates per upstream pod and ejects misbehaving instances from the load balancing pool.

```yaml
# Added to DestinationRule under trafficPolicy
trafficPolicy:
  outlierDetection:
    consecutiveGatewayErrors: 5    # Eject after 5 consecutive 502/503/504 errors
    consecutive5xxErrors: 5        # Or 5 consecutive 5xx errors
    interval: 10s                  # Check error rates every 10 seconds
    baseEjectionTime: 30s          # Eject for at least 30 seconds
    maxEjectionPercent: 50         # Never eject more than 50% of the pool
                                   # (prevents full-pool ejection if all pods fail)
```

**How it interacts with the application**: The application code doesn't need a circuit breaker library (`pybreaker`, `tenacity` circuit breaker mode). Istio handles it at the proxy layer. The pod still receives traffic on its `localhost` — it's the sidecar proxy that applies the outlier detection.

**What `maxEjectionPercent: 50` prevents**: if a network partition causes all pods to return errors, ejecting 100% of the pool would make the service completely unavailable. Capping at 50% preserves degraded operation.

---

## 4. Canary Deployments at the Mesh Level

The sequence for a safe canary rollout:

```bash
# Step 1: Deploy canary version (separate Deployment, same Service)
kubectl apply -f k8s/deployment-canary.yaml  # image: feature-pipeline:v2, labels: version=canary

# Step 2: Start at 5% traffic
kubectl apply -f - <<EOF
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: feature-pipeline
  namespace: production
spec:
  hosts: [feature-pipeline]
  http:
    - route:
        - destination: {host: feature-pipeline, subset: stable}
          weight: 95
        - destination: {host: feature-pipeline, subset: canary}
          weight: 5
EOF

# Step 3: Monitor error rate and latency (see Chapter 08 — Observability)
# kubectl exec -n istio-system ... istioctl dashboard kiali

# Step 4: Increment gradually — 5% → 20% → 50% → 100%
# Step 5: When at 100%, delete the stable Deployment and normalize the VirtualService
```

This pattern decouples the deployment event (the `kubectl apply`) from the release event (increasing canary weight). Traffic shifting is reversible at any step; rolling back is a weight adjustment, not a redeploy.

---

## 5. When You Don't Need a Service Mesh

A service mesh adds operational complexity: a control plane to manage, sidecar resource overhead (~50–100m CPU per pod, ~50–100 MB RAM), and a steeper debugging experience when traffic behaves unexpectedly.

Skip the mesh if:

| Condition | Rationale |
|-----------|-----------|
| Fewer than ~5 services | The overhead outweighs the benefits; implement retries in app code |
| Low compliance requirements | mTLS enforcement isn't required; network policies suffice |
| Team unfamiliar with Istio | Misconfigured mTLS or routing rules cause subtle, hard-to-debug failures |
| Serverless / Cloud Run | Cloud Run handles mTLS natively; Istio is a Kubernetes primitive |

At small scale, network policies (`NetworkPolicy`) provide isolation, and application-level retry logic with `tenacity` handles transient failures. These are simpler to reason about than Istio's CRDs.

---

## 6. Alternatives to Istio

| Tool | Model | Best for |
|------|-------|----------|
| **Istio** | Sidecar (Envoy) | Full traffic management, mTLS, advanced routing |
| **Linkerd** | Sidecar (Linkerd2-proxy) | Simpler than Istio, lower overhead, K8s-native |
| **Cilium** | eBPF (kernel-level, no sidecar) | High performance, deep network observability |
| **Consul Connect** | Sidecar | Multi-platform (K8s + VMs) |

For most Python ML infrastructure teams: start with Linkerd if a mesh is needed. It has a smaller operational surface and sensible defaults. Graduate to Istio only when advanced traffic management (custom routing predicates, WASM filters) is required.

---

## Summary

| Concern | Decision |
|---------|----------|
| mTLS | `PeerAuthentication` with `STRICT` mode in production namespace |
| Traffic routing | `VirtualService` + `DestinationRule` subsets for canary/stable |
| Retries | Configured in `VirtualService`; never double-implement in app code |
| Timeouts | Per-route in `VirtualService` — single source of truth |
| Circuit breaking | Istio outlier detection; `maxEjectionPercent: 50` prevents full-pool ejection |
| Canary workflow | Deploy → 5% → monitor → increment → clean up stable |
| When to skip | < 5 services, no compliance mandate, or team unfamiliar with Istio |
| Istio alternative | Linkerd for simpler operations; Cilium for eBPF-based networking |
