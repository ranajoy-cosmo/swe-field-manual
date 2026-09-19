# Secrets Management

Secrets (API keys, database passwords, TLS certificates) must never be committed to source control. Hardcoded secrets are the fastest way to suffer a data breach.

## The Problem with `.env` Files

Environment variables are the standard way to configure applications (The Twelve-Factor App). During local development, `.env` files parsed by `python-dotenv` are standard practice.

However, relying purely on environment variables in production has limitations:
- They cannot be easily rotated without restarting the application.
- Anyone with shell access to the container can read them (`env` command).
- They are often accidentally logged on crashes.

## Enterprise Secret Managers

Production secrets should live in a dedicated Secret Manager (HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault).

These systems provide:
1. **Encryption at rest**.
2. **Access control (IAM)**: Only specific services can read specific secrets.
3. **Audit logging**: A record of exactly who/what read a secret and when.
4. **Versioning**: Ability to roll back to a previous secret.

## Injecting Secrets

Do not write code that connects directly to Vault to fetch a database password. Keep the application unaware of the secret manager.

**In Kubernetes:**
Use the **External Secrets Operator (ESO)**. It syncs secrets from your cloud provider (e.g., GCP Secret Manager) into native Kubernetes `Secret` objects. Your application mounts them as environment variables or files, remaining completely agnostic.

**In GitHub Actions:**
Never hardcode secrets in CI workflows. Use GitHub Secrets.
Better yet, use **Workload Identity Federation (WIF)** (or OIDC) to avoid storing long-lived cloud credentials in GitHub entirely. GitHub authenticates to AWS/GCP via a short-lived token.

## Detecting Secrets in Code

Assume developers will accidentally commit secrets. Stop them before the commit leaves their machine using a pre-commit hook.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```
Combine this with GitHub Advanced Security (Secret Scanning) to block pushes containing recognized token formats (e.g., AWS keys, Slack tokens).

## Secret Rotation

Secrets must be rotated periodically or immediately upon compromise.

To rotate a database password without downtime:
1. Ensure the database supports multiple active passwords for a user (or create a second user).
2. Generate `Password B`.
3. Configure the Secret Manager to expose `Password B` to the application.
4. Trigger a rolling deployment so new pods use `Password B`.
5. Once all pods are using `Password B`, delete `Password A` from the database.

HashiCorp Vault can do this automatically via **Dynamic Secrets** (generating a unique, temporary database user for every pod that expires when the pod dies).

## Summary

| Feature | Recommendation | Reason |
|---------|----------------|--------|
| Local Dev | `.env` files (gitignored) | Simple, supported by all tools. |
| Production Storage | Cloud Secret Manager (e.g., GCP, AWS) | Provides audit logs, IAM, and versioning. |
| CI Authentication | Workload Identity Federation (OIDC) | Eliminates long-lived admin credentials in GitHub Secrets. |
| Leak Prevention | `detect-secrets` pre-commit hook | Stops secrets from entering the git history. |
