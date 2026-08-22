.PHONY: install test test-all lint typecheck fmt check

install:
	uv sync

test:
	uv run pytest -m "not data and not net"

test-all:
	uv run pytest

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy src/

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

check: lint typecheck test
