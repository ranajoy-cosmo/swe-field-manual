.PHONY: install docs-serve docs-build book clean

install:
	uv sync

docs-serve:
	uv run mkdocs serve

docs-build:
	uv run mkdocs build --clean

# Usage: make book SERIES=production-swe
book:
	@test -n "$(SERIES)" || (echo "usage: make book SERIES=<series-name>" && exit 1)
	uv run python scripts/build_book.py $(SERIES)
	typst compile books/$(SERIES)/book.typ

clean:
	rm -rf docs
	rm -rf books/*/generated
	find books -maxdepth 2 -name "*.pdf" -delete
