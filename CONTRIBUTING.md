# Contributing

This repo treats `docs/` as the source of truth for published content. The `drafts/` directory is for
unfinished local notes and is not included in the MkDocs site.

Python dependencies are managed with [uv](https://docs.astral.sh/uv/) via `pyproject.toml` / `uv.lock`
(committed) — no `pip install` or `requirements.txt`.

## Adding or editing content

Published content lives under `docs/<series>/<NN-chapter-name>/<NN-topic-name>.md`.

Use `drafts/` for unfinished notes. When a note is ready to become documentation, rewrite or move it
into the appropriate location under `docs/`.

- **Series** (e.g. `production-swe`) are top-level folders under `docs/`. Each needs a `README.md`
  landing page listing its chapters.
- **Chapters** are numbered folders (e.g. `01-foundations`). Each needs a `README.md` index describing
  its topic files, reading order, and prerequisites.
- **Topic files** are numbered Markdown files within a chapter (e.g. `01-code-quality.md`). Each must
  start with a single `#` H1 — it's used as the page title in the docs site.
- Numeric prefixes control ordering in the docs navigation. Leave gaps (e.g. skipped
  `05`, `08`) if you're reserving space for planned topics.
- Use fenced code blocks with a language tag (` ```python `) — the docs site relies on this for syntax
  highlighting.

## Previewing your changes

```sh
make install
make docs-serve
```

Browse to `http://127.0.0.1:8000` and confirm your new/edited page renders correctly and appears in the
nav in the right place.

## Adding a new series

1. Create `docs/<new-series>/README.md`.
2. Add it to the list in `docs/README.md`.
3. Add the series' chapters and topic files under `docs/<new-series>/`.
