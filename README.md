# SWE Field Manual

A personal repository of software engineering knowledge, processes, and best practices,
published as a MkDocs documentation site:

- **A GitHub-style documentation site** ([docs/](./docs)), built with [MkDocs](https://www.mkdocs.org/) + Material.

## Directory Map

| Path | Purpose |
|------|---------|
| [docs/](./docs) | Source of truth. Publishable Markdown content organized by series. |
| [drafts/](./drafts) | Local unfinished notes that are not included in the site. |

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (Python dependency management)

## Quickstart

```sh
make install       # uv sync — installs Python deps (mkdocs, mkdocs-material)
make docs-serve     # preview the docs site locally at http://127.0.0.1:8000
make docs-build      # build the static docs site into site/
make clean          # remove all generated/build output
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for how to write and organize new content.
