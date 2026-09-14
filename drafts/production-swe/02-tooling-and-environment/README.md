# Chapter 02 — Tooling and Environment

> *The local development environment is a production concern.*

A service that works on one machine and breaks on another is not a reliable service — it just hasn't failed at the worst moment yet. This chapter covers everything between "I have Python installed" and "I can run my code reliably, on any machine, from day one."

Environment drift — mismatched Python versions, missing dependencies, inconsistent formatting — is a silent tax. It compounds during onboarding, surfaces as "works on my machine" incidents, and wastes review cycles on fixable issues that a tool should have caught. The goal of this chapter is to eliminate that tax systematically.

## What This Chapter Covers

| File | Topic |
|------|-------|
| [01-project-layout.md](./01-project-layout.md) | `src/` layout, modern project anatomy, mono-repo vs. multi-repo |
| [02-dependency-management.md](./02-dependency-management.md) | `uv` workflow, dependency groups, lockfiles, update strategy |
| [03-linting-and-formatting.md](./03-linting-and-formatting.md) | Ruff deep-dive, mypy vs. pyright, the split CI/editor model |
| [04-pre-commit-hooks.md](./04-pre-commit-hooks.md) | Hook configuration, stages, conventional commits, CI integration |
| [05-editor-and-dev-environment.md](./05-editor-and-dev-environment.md) | `.editorconfig`, VS Code config, dev containers, `Makefile` targets |

## Reading Order

Read sequentially. Project layout (01) and dependency management (02) are prerequisites for everything else — you need to know *what* you're operating on before you configure the tools that operate on it. Linting (03) and pre-commit (04) are tightly coupled and best read together. Editor setup (05) is standalone and can be read at any point.

## Prerequisites

- Python 3.10+ installed
- Familiarity with `pyproject.toml` (covered lightly here; deep-dived in Chapter 10)
- `uv` installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## What This Chapter Deliberately Omits

- **Full `pyproject.toml` anatomy**: Chapter 10 — Packaging and Release Engineering
- **CI/CD pipeline configuration**: Chapter 07 — CI/CD and Automation
- **Full type system and Pydantic**: Chapter 01 — Foundations (typing-and-contracts)
- **Testing configuration**: Chapter 03 — Testing
