# SWE Field Manual

A personal repository of software engineering knowledge, processes, and best practices,
built as an automated pipeline from source notes to two published forms:

- **A GitHub-style documentation site** ([docs/](./docs)), built with [MkDocs](https://www.mkdocs.org/) + Material.
- **A Typst book** ([books/](./books)), compiled with [Typst](https://typst.app/).

## Directory Map

| Path | Purpose |
|------|---------|
| [drafts/](./drafts) | Source of truth. Numbered chapter notes in Markdown, organized by series (e.g. `production-swe`). |
| [scripts/](./scripts) | Automation for transforming drafts into books and docs. |
| [books/](./books) | Typst templates and per-series book entry points. Generated chapters and compiled PDFs are build output (gitignored). |
| [docs/](./docs) | Built MkDocs site output (gitignored). Generated from `drafts/` directly. |

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (Python dependency management)
- [pandoc](https://pandoc.org/installing.html) (Markdown → Typst conversion)
- [typst](https://github.com/typst/typst#installation) CLI (compiling the book)

## Quickstart

```sh
make install       # uv sync — installs Python deps (mkdocs, mkdocs-material)
make docs-serve     # preview the docs site locally at http://127.0.0.1:8000
make docs-build      # build the static docs site into docs/
make book SERIES=production-swe   # convert drafts to Typst and compile a PDF
make clean          # remove all generated/build output
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for how to write and organize new content.
