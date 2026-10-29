.PHONY: demo demo-fake process test lint record

PORT ?= 8000

demo: ## generate samples, extract with the local model, open the review UI
	uv run invoice-tray demo --port $(PORT)

demo-fake: ## same, replaying recorded model answers (no model needed)
	uv run invoice-tray demo --fake-llm --port $(PORT)

record: ## re-record model answers used by --fake-llm and the tests
	uv run invoice-tray demo --record --no-serve

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .
