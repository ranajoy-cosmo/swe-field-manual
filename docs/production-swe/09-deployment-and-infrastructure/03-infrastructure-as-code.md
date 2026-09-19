# 03 — Infrastructure as Code

## Why Infrastructure Must Be Code

Manual infrastructure — clicking through cloud consoles, running `gcloud` commands on a workstation — has the same failure modes as code without version control:

- **No audit trail**: who changed the database firewall rule last Tuesday?
- **No reproducibility**: staging and production drift apart over weeks of incremental changes
- **No rollback**: reverting a misconfiguration requires remembering what it was before
- **No review**: changes go to production without a second pair of eyes

Infrastructure as Code (IaC) applies software engineering discipline to infrastructure: every change is a code change, reviewed in a PR, tested in CI, and applied from a controlled environment.

Terraform is the industry standard for declarative IaC across GCP, AWS, Azure, and Kubernetes itself.

---

## 1. Terraform Basics

### Core Concepts

| Concept | Description |
|---------|-------------|
| **Provider** | Plugin that maps Terraform resources to a specific API (GCP, AWS, K8s) |
| **Resource** | A single infrastructure object (a GCS bucket, a Kubernetes namespace) |
| **Module** | A reusable group of resources with inputs and outputs |
| **State** | Terraform's snapshot of what it believes exists — must match reality |
| **Plan** | A diff: what will be created, changed, or destroyed |
| **Apply** | Executes the plan against the real infrastructure |

### Why Terraform Over Shell Scripts

```bash
# Shell script: imperative
gcloud compute instances create web-server \
    --machine-type e2-medium \
    --zone us-central1-a

# What happens when you run this twice? A second instance is created.
# What happens when the script fails halfway? Partial state.
# How do you know what currently exists? Run the script with dry-run flags that may not exist.
```

```hcl
# Terraform: declarative
resource "google_compute_instance" "web_server" {
  name         = "web-server"
  machine_type = "e2-medium"
  zone         = "us-central1-a"
}

# Run twice: Terraform sees the instance already exists → no action
# Fail halfway: Terraform state captures what succeeded → next apply is safe
# What exists: terraform show
```

---

## 2. Remote State Management

State must never live on a developer workstation. Remote state enables team collaboration and prevents state corruption from concurrent applies.

### GCS Backend (GCP)

```hcl
# infrastructure/environments/prod/backend.tf
terraform {
  backend "gcs" {
    bucket  = "your-org-terraform-state"
    prefix  = "prod/feature-pipeline"  # isolate state per environment
  }
}
```

```hcl
# S3 Backend (AWS) — for reference
terraform {
  backend "s3" {
    bucket         = "your-org-terraform-state"
    key            = "prod/feature-pipeline/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-lock"  # state locking
    encrypt        = true
  }
}
```

GCS provides native state locking — only one `apply` can run at a time, preventing race conditions. Enable versioning on the state bucket to recover from accidental state corruption:

```bash
gcloud storage buckets update gs://your-org-terraform-state \
    --versioning
```

---

## 3. Module Structure for a Python Service

Modules are reusable units. A `python-service` module encodes the standard infrastructure topology for a service: container runtime, database, IAM, networking.

```
infrastructure/
├── modules/
│   └── python-service/       # Reusable module
│       ├── main.tf           # Resource definitions
│       ├── variables.tf      # Input parameters
│       ├── outputs.tf        # Exported values
│       └── README.md
└── environments/
    ├── staging/
    │   ├── backend.tf        # Staging state bucket
    │   ├── main.tf           # Calls python-service module with staging values
    │   └── terraform.tfvars  # Staging-specific variable values
    └── prod/
        ├── backend.tf
        ├── main.tf
        └── terraform.tfvars
```

### Module Definition (`modules/python-service/variables.tf`)

```hcl
variable "service_name" {
  type        = string
  description = "Name of the service (used for all resource names)"
}

variable "environment" {
  type        = string
  description = "Deployment environment: staging | prod"
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "Environment must be 'staging' or 'prod'."
  }
}

variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  default     = "europe-west1"
}

variable "container_image" {
  type        = string
  description = "Full container image reference, including tag or digest"
}

variable "min_instances" {
  type    = number
  default = 1
}

variable "max_instances" {
  type    = number
  default = 10
}

variable "db_tier" {
  type        = string
  default     = "db-f1-micro"
  description = "Cloud SQL instance tier"
}
```

### Module Definition (`modules/python-service/main.tf`)

```hcl
# Cloud Run service (for simpler deployments — no K8s overhead)
resource "google_cloud_run_v2_service" "app" {
  name     = "${var.service_name}-${var.environment}"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.app.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        startup_cpu_boost = true
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_url.secret_id
            version = "latest"
          }
        }
      }

      liveness_probe {
        http_get {
          path = "/health/live"
          port = 8080
        }
        initial_delay_seconds = 10
        period_seconds        = 15
      }

      startup_probe {
        http_get {
          path = "/health/live"
          port = 8080
        }
        failure_threshold = 30
        period_seconds    = 10
      }
    }
  }
}

# Service account with minimal permissions (principle of least privilege)
resource "google_service_account" "app" {
  account_id   = "${var.service_name}-${var.environment}"
  display_name = "${var.service_name} (${var.environment})"
  project      = var.project_id
}

# Allow the service account to read secrets
resource "google_secret_manager_secret_iam_member" "db_url_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

# Secret Manager secret (value set out-of-band — not in Terraform)
resource "google_secret_manager_secret" "db_url" {
  secret_id = "${var.service_name}-${var.environment}-db-url"
  project   = var.project_id

  replication {
    auto {}
  }
}
```

### Environment Instantiation (`environments/prod/main.tf`)

```hcl
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "feature_pipeline" {
  source = "../../modules/python-service"

  service_name    = "feature-pipeline"
  environment     = "prod"
  project_id      = var.project_id
  region          = var.region
  container_image = var.container_image   # injected by CI at deploy time
  min_instances   = 3
  max_instances   = 30
  db_tier         = "db-custom-2-7680"    # 2 vCPU, 7.5 GB RAM
}
```

---

## 4. Terraform Workflow in CI

The principle: `plan` is free to run; `apply` requires human review or is gated on main branch.

```yaml
# .github/workflows/terraform.yml
name: Terraform

on:
  pull_request:
    paths: ["infrastructure/**"]
  push:
    branches: [main]
    paths: ["infrastructure/**"]

permissions:
  contents: read
  id-token: write        # Workload Identity Federation
  pull-requests: write   # Post plan as PR comment

jobs:
  terraform:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: infrastructure/environments/prod

    steps:
      - uses: actions/checkout@v4

      # Authenticate to GCP via Workload Identity — no static service account keys
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.TF_SERVICE_ACCOUNT }}

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.9.0"

      - name: Terraform Init
        run: terraform init

      - name: Terraform Validate
        run: terraform validate

      - name: Terraform Plan
        id: plan
        run: |
          terraform plan \
            -var="container_image=ghcr.io/your-org/feature-pipeline:${{ github.sha }}" \
            -out=tfplan \
            -no-color 2>&1 | tee plan_output.txt

      # Post plan output as PR comment
      - name: Post plan to PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const plan = require('fs').readFileSync('infrastructure/environments/prod/plan_output.txt', 'utf8')
            const body = `### Terraform Plan\n\`\`\`\n${plan.slice(0, 60000)}\n\`\`\``
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body
            })

      # Apply only on merge to main (not on PRs)
      - name: Terraform Apply
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        run: terraform apply -auto-approve tfplan
```

**Why `plan -out=tfplan` + `apply tfplan`**: applying the saved plan file guarantees that exactly the reviewed plan is executed, not a fresh plan that might differ if infrastructure changed between plan and apply.

---

## 5. Terragrunt for DRY Multi-Environment Configs

When managing many environments with identical structure but different values, Terragrunt eliminates boilerplate.

```hcl
# terragrunt.hcl (root)
remote_state {
  backend = "gcs"
  generate = {
    path      = "backend.tf"
    if_exists = "overwrite"
  }
  config = {
    bucket = "your-org-terraform-state"
    prefix = "${path_relative_to_include()}/terraform.tfstate"
  }
}
```

```hcl
# environments/prod/terragrunt.hcl
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../modules//python-service"
}

inputs = {
  service_name    = "feature-pipeline"
  environment     = "prod"
  project_id      = "your-project-prod"
  min_instances   = 3
  max_instances   = 30
  db_tier         = "db-custom-2-7680"
}
```

Terragrunt handles backend configuration generation, preventing the repeated `backend.tf` boilerplate across environments.

---

## 6. Terraform Anti-Patterns

| Anti-pattern | Why it's harmful | Correct approach |
|--------------|-----------------|------------------|
| Storing state in Git | State contains secrets; concurrent applies cause corruption | Remote backend (GCS/S3) with locking |
| Storing secret values in `.tf` files | Secrets appear in state file and CI logs | `google_secret_manager_secret` with out-of-band value injection |
| `terraform apply` from a developer workstation | No audit trail, not reproducible | Apply only from CI with Workload Identity |
| Giant monolithic root module | One change requires planning all resources | Module decomposition; small blast radius |
| `terraform import` without updating `.tf` | State and code diverge | Always write the resource definition before importing |
| Using `count` for environment duplication | Fragile indexing, hard to read diffs | Separate environment directories |

---

## Summary

| Concern | Decision |
|---------|----------|
| State storage | Remote backend (GCS or S3) with native locking; versioning enabled |
| Authentication | Workload Identity Federation from CI — no static service account keys |
| Module structure | `modules/` (reusable) + `environments/` (instantiations) |
| Plan visibility | Post plan as PR comment; require review before apply |
| Apply trigger | Merge to main only; never from developer workstations |
| Secret values | `Secret Manager` resources in Terraform; values set out-of-band |
| Multi-environment | Terragrunt for DRY backend/provider configuration |
