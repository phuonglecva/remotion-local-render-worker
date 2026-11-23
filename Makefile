.PHONY: bootstrap doctor test lint run-once run setup-drive remotion-install remotion-typecheck

bootstrap:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e ".[dev]"
	cd remotion && npm install

doctor:
	. .venv/bin/activate && render-worker doctor

test:
	. .venv/bin/activate && pytest -q

lint:
	. .venv/bin/activate && ruff check src tests

setup-drive:
	. .venv/bin/activate && render-worker setup-drive

run-once:
	. .venv/bin/activate && render-worker run --once

run:
	. .venv/bin/activate && render-worker run

remotion-install:
	cd remotion && npm install

remotion-typecheck:
	cd remotion && npm run typecheck
