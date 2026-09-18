#!/usr/bin/env python3
"""Convert a drafts/<series> markdown tree into Typst chapters via pandoc.

Usage:
    python scripts/build_book.py <series>

For every drafts/<series>/**/*.md file (except the series' own top-level
README.md, which is docs-only front matter), this runs `pandoc` to produce a
matching .typ file under books/<series>/generated/, then rewrites the
generated-includes block in books/<series>/book.typ to reference them all in
sorted (numeric-prefix) order.

Requires the `pandoc` CLI to be installed and on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DRAFTS_DIR = REPO_ROOT / "drafts"
BOOKS_DIR = REPO_ROOT / "books"

BEGIN_MARKER = "// --- BEGIN GENERATED INCLUDES"
END_MARKER = "// --- END GENERATED INCLUDES"


def find_source_files(series_dir: Path) -> list[Path]:
    """Return all chapter markdown files, sorted, excluding the series' own README."""
    top_level_readme = series_dir / "README.md"
    files = [
        path
        for path in sorted(series_dir.rglob("*.md"))
        if path != top_level_readme
    ]
    return files


def convert_to_typst(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pandoc", "--from=gfm", str(src), "-o", str(dest)],
        check=True,
    )


def rewrite_includes(book_typ: Path, generated_dir: Path, typ_files: list[Path]) -> None:
    text = book_typ.read_text()
    begin_idx = text.index(BEGIN_MARKER)
    end_idx = text.index(END_MARKER) + len(END_MARKER)

    relative_paths = [f.relative_to(generated_dir.parent).as_posix() for f in typ_files]
    includes_block = "\n".join(f'#include "{path}"' for path in relative_paths)

    new_section = (
        f"{BEGIN_MARKER} (auto-generated, do not edit by hand) ---\n"
        f"{includes_block}\n"
        f"{END_MARKER} ---"
    )
    book_typ.write_text(text[:begin_idx] + new_section + text[end_idx:])


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/build_book.py <series>", file=sys.stderr)
        sys.exit(1)

    if shutil.which("pandoc") is None:
        print("error: pandoc is required but not found on PATH", file=sys.stderr)
        sys.exit(1)

    series = sys.argv[1]
    series_dir = DRAFTS_DIR / series
    if not series_dir.is_dir():
        print(f"error: no such drafts series: {series_dir}", file=sys.stderr)
        sys.exit(1)

    book_typ = BOOKS_DIR / series / "book.typ"
    if not book_typ.exists():
        print(f"error: missing {book_typ} (create it before running this script)", file=sys.stderr)
        sys.exit(1)

    generated_dir = BOOKS_DIR / series / "generated"
    if generated_dir.exists():
        shutil.rmtree(generated_dir)

    source_files = find_source_files(series_dir)
    typ_files = []
    for src in source_files:
        rel = src.relative_to(series_dir).with_suffix(".typ")
        dest = generated_dir / rel
        convert_to_typst(src, dest)
        typ_files.append(dest)
        print(f"converted {src.relative_to(REPO_ROOT)} -> {dest.relative_to(REPO_ROOT)}")

    rewrite_includes(book_typ, generated_dir, typ_files)
    print(f"updated includes in {book_typ.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
