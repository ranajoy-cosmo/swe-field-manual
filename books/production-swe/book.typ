// Entry point for the Production SWE book.
// Chapters are pandoc-converted from drafts/production-swe/**/*.md into ./generated/
// by `make book SERIES=production-swe` (scripts/build_book.py keeps the includes below in sync).
#import "../template.typ": book

#show: body => book(title: "Production SWE", body)

// --- BEGIN GENERATED INCLUDES (smoke test: single chapter) ---
#include "generated/01-foundations/01-code-quality.typ"
// --- END GENERATED INCLUDES ---
