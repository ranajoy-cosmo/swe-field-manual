# 01 — Docker Best Practices

> Cross-reference: Chapter 10 `06-containerization-for-apps.md` covers multi-stage builds, layer caching, and base image selection. This file picks up where that left off: what makes a container production-hardened.

## Why Image Security Is a Deployment Concern

A container image is a supply chain artifact. Every OS package, Python dependency, and binary inside it has a CVE surface that widens over time. An image that was clean at build time can be exploitable three weeks later when a new vulnerability is disclosed. Security isn't a one-time check; it's a continuous posture applied at build time, push time, and runtime.

The attack surface has four layers:
1. **OS packages** — the Debian/Alpine packages in the base image
2. **Python dependencies** — packages installed via `uv sync`
3. **Your application code** — and any secrets accidentally baked in
4. **The runtime configuration** — running as root, writable filesystems, missing SBOM

This file addresses all four.

---

## 1. Image Vulnerability Scanning

Scan every image after it is built, before it is pushed. Gate the CI pipeline on `CRITICAL` findings.

### Trivy (Recommended Default)

Trivy is the Swiss-Army knife of container scanning: OS packages, language-level dependencies, IaC files, and secrets — one tool.

```bash
# Install
uv tool install trivy  # or: brew install trivy

# Scan a local image — fail CI on CRITICAL severity
trivy image \
    --exit-code 1 \
    --severity CRITICAL,HIGH \
    --ignore-unfixed \
    my-registry/feature-pipeline:a3f2b1c

# Scan a Dockerfile before building
trivy config Dockerfile
```

The `--ignore-unfixed` flag skips CVEs with no available fix — these can't be remediated by upgrading and would create permanent noise in the pipeline.

### Grype + Syft (SBOM-First Workflow)

Grype pairs with Syft to enable a decoupled workflow: generate the SBOM once, rescan it any time without rebuilding the image.

```bash
# Generate SBOM
syft my-registry/feature-pipeline:a3f2b1c -o spdx-json > sbom.spdx.json

# Scan the SBOM — can be re-run without the image
grype sbom:sbom.spdx.json --fail-on critical
```

The advantage: CI can rescan historical images nightly against an updated vulnerability database without rebuilding them.

### In GitHub Actions

```yaml
# .github/workflows/build.yml  (relevant job steps)
jobs:
  build-and-scan:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write  # for uploading SARIF results

    steps:
      - uses: actions/checkout@v4

      - name: Build image
        run: |
          docker build -t $IMAGE_TAG .

      - name: Scan image with Trivy
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ env.IMAGE_TAG }}
          format: sarif
          output: trivy-results.sarif
          exit-code: '1'
          severity: CRITICAL,HIGH
          ignore-unfixed: true

      - name: Upload scan results to GitHub Security
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: trivy-results.sarif
```

Uploading SARIF results surfaces findings in the GitHub Security tab, not just in CI logs.

### Vulnerability Triage

CVSS severity alone is a poor signal — a CRITICAL score CVE with no known exploit path is lower priority than a HIGH score CVE actively exploited in the wild. Use EPSS (Exploit Prediction Scoring System) scores to prioritize remediation:

| Signal | Meaning | Action |
|--------|---------|--------|
| CRITICAL + EPSS > 0.1 | High risk, likely exploited | Block deployment |
| CRITICAL + EPSS < 0.01 | High theoretical risk | Fix in next sprint |
| HIGH + unfixed | Can't be resolved | Accept with documented rationale |
| MEDIUM and below | Low near-term risk | Track in backlog |

---

## 2. Non-Root Users

Never run an application as root inside a container. Root inside a container maps (partially) to root on the host if container isolation is breached.

### The Pattern

```dockerfile
# In the production stage of the multi-stage build
# (after the builder stage — see Ch10 §06 for the full multi-stage template)

FROM python:3.12-slim-bookworm

# Create a dedicated user with no home directory modification needed
RUN useradd \
    --system \
    --create-home \
    --shell /bin/bash \
    --uid 1001 \
    appuser

# Switch to non-root before copying files
USER appuser
WORKDIR /home/appuser/app

COPY --from=builder --chown=appuser:appuser /app/.venv /home/appuser/app/.venv
COPY --from=builder --chown=appuser:appuser /app/src /home/appuser/app/src

ENV PATH="/home/appuser/app/.venv/bin:$PATH"
CMD ["feature-pipeline", "--host", "0.0.0.0", "--port", "8080"]
```

**Why `--uid 1001`**: Some base images already have a user with UID 1000. Using a fixed, explicit UID makes it easier to grant Kubernetes pod security policies and configure file permissions consistently.

### Kubernetes Enforcement

Don't rely on the Dockerfile alone. Enforce non-root at the cluster level:

```yaml
# In your Deployment spec
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        fsGroup: 1001
      containers:
        - name: feature-pipeline
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
```

If the image's `USER` is root and `runAsNonRoot: true` is set, Kubernetes will refuse to start the pod — a hard gate, not a soft warning.

---

## 3. Read-Only Filesystems

A writable root filesystem is an attack vector. If an attacker achieves code execution, they can write malware, modify configuration, or exfiltrate data to local files.

```dockerfile
# No change needed in the Dockerfile — read-only is enforced at runtime
```

```yaml
# Kubernetes: enforce at the pod spec level
securityContext:
  readOnlyRootFilesystem: true

# Applications often need writable paths for:
# - /tmp (temporary files)
# - Uvicorn's Unix socket (if used)
# - Model weights cache (ML workloads)
# Mount these explicitly as emptyDir volumes

volumeMounts:
  - name: tmp
    mountPath: /tmp
  - name: model-cache
    mountPath: /home/appuser/.cache

volumes:
  - name: tmp
    emptyDir: {}
  - name: model-cache
    emptyDir:
      medium: Memory  # RAM-backed: fast for model loading, lost on restart
```

If an application writes anywhere outside the explicitly mounted paths, it will crash immediately — which is the correct behavior. Find the paths during staging before reaching production.

---

## 4. SBOM (Software Bill of Materials)

An SBOM is a machine-readable inventory of every component in the image: OS packages, Python wheels, their versions, and their licenses. It is the foundation of supply chain transparency.

### Generate with Syft

```bash
# During CI, after the image is built and pushed
syft my-registry/feature-pipeline:a3f2b1c \
    -o spdx-json \
    --file sbom.spdx.json

# Attach the SBOM to the image in the registry
oras attach my-registry/feature-pipeline:a3f2b1c \
    --artifact-type application/spdx+json \
    sbom.spdx.json
```

Attaching the SBOM to the image keeps it co-located with the artifact: when the image is promoted from staging to production, the SBOM travels with it.

### License Compliance Scanning

```bash
# Trivy can scan an SBOM for license violations
trivy sbom sbom.spdx.json \
    --severity UNKNOWN \
    --license-full
```

ML infrastructure often pulls in packages with GPL-licensed transitive dependencies. This check catches that before legal review is needed.

---

## 5. Image Signing with Cosign (Sigstore)

Signing answers the question: "Did this image come from our CI pipeline, or was it tampered with in the registry?"

### Keyless Signing (GitHub Actions)

Keyless signing uses OIDC tokens from the CI environment — no long-lived private keys to manage or rotate.

```yaml
# .github/workflows/build.yml
jobs:
  build-sign-push:
    runs-on: ubuntu-latest
    permissions:
      id-token: write      # required for OIDC token (keyless signing)
      contents: read
      packages: write      # to push to GHCR

    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        id: build
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}/feature-pipeline:${{ github.sha }}
          # Outputs the image digest for signing
          outputs: type=image,name=ghcr.io/${{ github.repository }}/feature-pipeline,push-by-digest=true,name-canonical=true,push=true

      - name: Install cosign
        uses: sigstore/cosign-installer@v3

      - name: Sign image
        # Sign by digest (immutable) not by tag (mutable)
        run: |
          cosign sign --yes \
            ghcr.io/${{ github.repository }}/feature-pipeline@${{ steps.build.outputs.digest }}
```

The signature is stored in the registry alongside the image. `cosign verify` confirms authenticity:

```bash
cosign verify \
    --certificate-identity-regexp "https://github.com/your-org/.*" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
    ghcr.io/your-org/feature-pipeline:a3f2b1c
```

### Kubernetes Admission Enforcement

Signatures are only useful if unverified images are blocked from running:

```yaml
# Kyverno policy: require cosign signature on all images in the prod namespace
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-signed-images
spec:
  validationFailureAction: Enforce
  rules:
    - name: verify-image-signature
      match:
        any:
          - resources:
              kinds: ["Pod"]
              namespaces: ["production"]
      verifyImages:
        - imageReferences: ["ghcr.io/your-org/*"]
          attestors:
            - count: 1
              entries:
                - keyless:
                    subject: "https://github.com/your-org/*"
                    issuer: "https://token.actions.githubusercontent.com"
```

---

## 6. Registry Tag Retention

Image registries accumulate thousands of tags over months. An unmanaged registry wastes storage and makes it harder to track what's running in production.

```yaml
# Google Artifact Registry — lifecycle policy (terraform)
resource "google_artifact_registry_repository" "app" {
  repository_id = "feature-pipeline"
  format        = "DOCKER"
  location      = "europe-west1"

  cleanup_policies {
    id     = "keep-tagged-releases"
    action = "KEEP"
    condition {
      tag_prefixes = ["v"]  # keep all version tags
    }
  }

  cleanup_policies {
    id     = "delete-old-sha-tags"
    action = "DELETE"
    condition {
      tag_state    = "TAGGED"
      older_than   = "2592000s"  # 30 days
      tag_prefixes = []           # applies to non-version tags (SHA tags)
    }
  }
}
```

Rule of thumb: keep all version-tagged images indefinitely (they may need rollback), retain SHA tags for 30 days (useful for debugging recent deployments), delete `latest` and `main` variants older than a week.

---

## Summary

| Concern | Decision |
|---------|----------|
| Vulnerability scanning | Trivy (default); Grype + Syft for SBOM-first workflows |
| Scan severity gate | Block on CRITICAL; HIGH with EPSS > 0.1 |
| Runtime user | `useradd --uid 1001`, enforced by `runAsNonRoot: true` in K8s |
| Filesystem | `readOnlyRootFilesystem: true`; writable paths via `emptyDir` volumes |
| SBOM | `syft` at build time; attached to image in registry |
| Image signing | Cosign keyless (GitHub OIDC); enforced by Kyverno admission policy |
| Tag retention | Version tags forever; SHA tags 30 days; automated lifecycle policy |
