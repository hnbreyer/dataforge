.PHONY: install check format test init serve
PYTHON ?= .venv/bin/python
BIN ?= .venv/bin
install:
	$(PYTHON) -m pip install -e '.[dev]'
check:
	$(BIN)/ruff check src tests scripts
	$(BIN)/ruff format --check src tests scripts
format:
	$(BIN)/ruff check src tests scripts --fix
	$(BIN)/ruff format src tests scripts
test:
	$(BIN)/pytest
init:
	$(BIN)/dataforge init
serve:
	$(BIN)/dataforge serve
