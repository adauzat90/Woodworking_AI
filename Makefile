.PHONY: check test lint golden

# One command the cleanup epic gates on: lint + full test suite.
check: lint test

PYTHON ?= python3

lint:
	$(PYTHON) -m ruff check

test:
	$(PYTHON) -m pytest -q

# Regenerate the golden-output fixtures (only when a change is intended).
golden:
	WOODAI_REGEN_GOLDEN=1 $(PYTHON) -m pytest tests/test_golden.py -q
