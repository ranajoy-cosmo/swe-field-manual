# Chapter 09 — Deployment and Infrastructure

> *Code that can't run reliably in production isn't finished.*

This chapter covers the operational layer: how to harden containers, run services on Kubernetes, codify infrastructure, manage network traffic between services, and design systems that scale horizontally without carrying hidden state. It picks up where Chapter 10's containerization file left off and goes deeper on everything that happens after the image is built.

## What This Chapter Covers

| File | Topic |
|------|-------|
| [01-docker-best-practices.md](./01-docker-best-practices.md) | Image security scanning, non-root users, read-only filesystems, SBOM, image signing |
| [02-kubernetes-for-python-services.md](./02-kubernetes-for-python-services.md) | Core objects, probes, rolling updates, PDB, HPA, Helm |
| [03-infrastructure-as-code.md](./03-infrastructure-as-code.md) | Terraform basics, remote state, module structure, CI workflow |
| [04-service-mesh-and-networking.md](./04-service-mesh-and-networking.md) | Istio, mTLS, circuit breakers, traffic splitting, when to skip the mesh |
| [05-scaling-and-stateless-design.md](./05-scaling-and-stateless-design.md) | Twelve-factor, horizontal scaling, session state, graceful shutdown, cold starts |

## Running Example

All examples use the `feature-pipeline` service from the rest of this series: a FastAPI application that serves ML features, backed by PostgreSQL and Redis, deployed to Kubernetes.

## Prerequisites

- [Chapter 10 — Packaging and Release Engineering](../10-packaging-and-release/README.md), specifically `06-containerization-for-apps.md`
- Familiarity with Docker multi-stage builds and `uv`
- Basic Kubernetes vocabulary (Pod, Deployment, Service)
