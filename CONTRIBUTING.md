# Contributing

This repo treats `drafts/` as the single source of truth. Everything else (`docs/`, `books/*/generated`,
compiled PDFs) is generated output and should not be hand-edited or committed.

Python dependencies are managed with [uv](https://docs.astral.sh/uv/) via `pyproject.toml` / `uv.lock`
(committed) — no `pip install` or `requirements.txt`.

## Adding or editing content

Content lives under `drafts/<series>/<NN-chapter-name>/<NN-topic-name>.md`.

- **Series** (e.g. `production-swe`) are top-level folders under `drafts/`. Each needs a `README.md`
  landing page listing its chapters.
- **Chapters** are numbered folders (e.g. `01-foundations`). Each needs a `README.md` index describing
  its topic files, reading order, and prerequisites.
- **Topic files** are numbered Markdown files within a chapter (e.g. `01-code-quality.md`). Each must
  start with a single `#` H1 — it's used as the page title in the docs site and the book.
- Numeric prefixes control ordering everywhere (docs nav, book chapter order). Leave gaps (e.g. skipped
  `05`, `08`) if you're reserving space for planned topics.
- Use fenced code blocks with a language tag (` ```python `) — both the docs site and the Typst book
  rely on this for syntax highlighting.

## Previewing your changes

```sh
make install
make docs-serve
```

Browse to `http://127.0.0.1:8000` and confirm your new/edited page renders correctly and appears in the
nav in the right place.

## Building the book

```sh
make book SERIES=production-swe
```

This runs `scripts/build_book.py` (pandoc conversion of every `drafts/<series>/**/*.md` file to Typst)
and then compiles `books/<series>/book.typ` to PDF via the `typst` CLI. Requires `pandoc` and `typst`
on PATH. Pandoc's Markdown → Typst conversion is not perfect for everything (e.g. admonitions/callouts) —
if a chapter renders oddly, check the generated `.typ` file under `books/<series>/generated/` and adjust
`books/template.typ` or the source Markdown as needed.

## Adding a new series

1. Create `drafts/<new-series>/README.md`.
2. Add it to the list in `drafts/README.md`.
3. Create `books/<new-series>/book.typ` (copy the structure from `books/production-swe/book.typ`,
   pointing `#import` at `../template.typ`).
4. Run `make book SERIES=<new-series>` to generate and compile.
