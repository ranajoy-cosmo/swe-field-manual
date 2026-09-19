.PHONY: install docs-serve docs-build clean

install:
	uv sync

docs-serve:
	uv run mkdocs serve

docs-build:
	uv run mkdocs build --clean

clean:
	rm -rf site
