# GitHub Actions In-Depth

GitHub Actions is a powerful automation platform, but messy YAML workflows lead to brittle pipelines. 

## Workflow Triggers

Only run jobs when necessary.
- **`push` and `pull_request`**: Typical for CI. Filter by branch and paths to avoid running Python tests on Markdown changes.
- **`workflow_dispatch`**: Manual triggers, essential for operational scripts (e.g., triggering a database rollback).
- **`schedule`**: Cron jobs (e.g., nightly integration tests or dependency updates).
- **`workflow_call`**: Reusable workflows.

## Job Dependencies and the `ci-success` Pattern

Jobs in a workflow run in parallel by default. Use `needs:` to build a DAG (Directed Acyclic Graph).

When using matrix builds and branch protection rules, requiring every single matrix job (e.g., `test (3.10)`, `test (3.11)`) is fragile. Instead, use a single aggregator job at the end of the pipeline and require *only* that job in branch protection.

```yaml
jobs:
  lint:
    # ...
  test:
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    # ...
  ci-success:
    needs: [lint, test]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Check successful
        if: ${{ contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled') }}
        run: exit 1
```
*Require only `ci-success` in GitHub branch protection rules.*

## Matrix Builds

Matrix builds test code against multiple configurations simultaneously. Always use `fail-fast: false` in CI so one failing matrix combination doesn't cancel the others, allowing you to see all failures at once.

```yaml
strategy:
  fail-fast: false
  matrix:
    python-version: ["3.10", "3.11"]
    os: [ubuntu-latest, macos-latest]
```

## Caching with `uv`

Dependency installation is often the slowest part of CI. `uv` is incredibly fast, but caching the downloaded wheels saves network time.

```yaml
steps:
  - uses: actions/checkout@v4
  - name: Install uv
    uses: astral-sh/setup-uv@v2
    with:
      enable-cache: true
      cache-dependency-glob: "uv.lock"
  - name: Install dependencies
    run: uv sync --all-extras --dev
```

## Reusable Workflows

Do not copy-paste CI definitions across 15 microservice repositories. Define a reusable workflow in a central repository.

```yaml
# In central-repo/.github/workflows/python-ci.yml
on:
  workflow_call:
    inputs:
      python-version:
        required: false
        type: string
        default: "3.11"
```

```yaml
# In microservice-a/.github/workflows/ci.yml
jobs:
  call-workflow:
    uses: my-org/central-repo/.github/workflows/python-ci.yml@main
    with:
      python-version: "3.10"
```

## Secrets and Variables

- **Variables (`vars.NAME`)**: Non-sensitive configuration (e.g., `AWS_REGION`).
- **Secrets (`secrets.NAME`)**: Sensitive data (e.g., `AWS_SECRET_ACCESS_KEY`).

Use **Environments** (e.g., `staging`, `production`) to attach protection rules to secrets. For example, a deployment job targeting the `production` environment can be configured to require manual approval before GitHub allows it to access the production secrets.

## Concurrency Groups

If a developer pushes three commits to a PR in rapid succession, the first two CI runs are obsolete. Cancel them automatically to save runner minutes using `concurrency`.

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

## Summary

| Feature | Recommendation | Reason |
|---------|----------------|--------|
| Branch Protection | `ci-success` pattern | Avoids manually updating branch protection rules when matrix dimensions change. |
| Caching | `astral-sh/setup-uv` | Built-in caching avoids complex `actions/cache` key logic. |
| DRY Workflows | `workflow_call` | Allows centralizing CI logic across a multi-repo organization. |
| Redundant Runs | `concurrency` | Cancels obsolete in-progress jobs, saving money and queue time. |
