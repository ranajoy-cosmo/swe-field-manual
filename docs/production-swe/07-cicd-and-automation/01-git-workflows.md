# Git Workflows

The Git workflow dictates how quickly a team can deliver code. Complex branching strategies (like GitFlow) were designed for software released on CDs every 6 months. For modern web services and ML infrastructure, they introduce massive merge conflicts and delay feedback.

## Trunk-Based Development

Trunk-based development is the industry standard for high-performing teams. 

**The core rules:**
1. All developers merge to `main` (the trunk) multiple times a day.
2. `main` is always in a releasable state.
3. Branches are short-lived (less than 24 hours).
4. Code review is synchronous or immediately prioritized.

## Branch Protection Rules

To keep `main` stable, enforce these rules via GitHub/GitLab:

- **Require Pull Request**: No direct commits to `main`.
- **Require Status Checks to Pass**: CI must pass before merging.
- **Require Review**: At least one approved review from a code owner.
- **No Force Pushes**: Never allow `push --force` on `main`.

## Short-Lived Feature Branches

Long-lived branches are a sign that tasks are not broken down sufficiently. 

> [!TIP]
> **How to merge incomplete features:** If a feature takes 3 days, do not keep the branch open for 3 days. Merge the structural changes on day 1 (hidden behind a feature flag or simply unhooked from the main execution path). Merge the logic on day 2. Merge the UI/API exposure on day 3.

## When GitFlow is Appropriate

GitFlow (with its `develop`, `release/*`, and `hotfix/*` branches) is heavy overhead. However, it is appropriate in one specific case: **Library maintenance across multiple major versions.**

If you maintain an open-source library and need to simultaneously patch a critical security bug in `v1.4` while building new features in `v2.0` on `main`, GitFlow-style release branches are necessary. 

For internal microservices or deployed ML pipelines, avoid GitFlow entirely.

## Commit Hygiene

A Git history is documentation. When an incident occurs at 2 AM, the Git log is the first place an engineer looks.

1. **Atomic Commits**: One commit = one logical change. Do not mix formatting changes with a database schema update.
2. **The 50-Character Subject Line Rule**: Keep the first line under 50 characters.
3. **Imperative Mood**: Write "Add caching to feature store" (not "Added" or "Adds").

```text
# GOOD
Add Redis cache to the feature retrieval path

Reduces P99 latency for the inference service from 450ms to 40ms.
Fixes an issue where database connection limits were exhausted during traffic spikes.

# BAD
fixed latency issue and also ran formatter
```

## `git bisect`

Good commit hygiene makes `git bisect` a superpower. If a bug was introduced sometime in the last 100 commits, `bisect` performs a binary search to find the exact commit that broke the tests in ~7 steps.

```bash
git bisect start
git bisect bad HEAD      # Current commit is broken
git bisect good v1.2.0   # Last known good release

# Git checks out a commit halfway between. Run your test:
pytest tests/test_inference.py

# If it fails:
git bisect bad
# If it passes:
git bisect good

# Repeat until Git outputs: "a1b2c3d4 is the first bad commit"
git bisect reset
```

If your commits are not atomic, `bisect` will point to a massive 4,000-line PR, and you will still have to debug the issue manually.

## Summary

| Decision | Recommendation | Reason |
|----------|----------------|--------|
| Branching Strategy | Trunk-based development | Minimizes merge conflicts, enforces small batch sizes. |
| Branch Protection | Require PR, CI, Review | Prevents broken code from reaching the deployment pipeline. |
| Commit Style | Atomic, imperative mood | Creates a readable history and enables `git bisect`. |
| GitFlow | Avoid for services | Designed for boxed software, adds unnecessary overhead for continuous deployment. |
