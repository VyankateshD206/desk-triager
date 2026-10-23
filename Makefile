PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: test lint build run eval verify
lint:
	$(PYTHON) -m ruff check triager tests scripts evals demo
	$(PYTHON) -m ruff format --check triager tests scripts evals demo

test:
	$(PYTHON) -m pytest -q

build: lint
	$(PYTHON) scripts/check_frontend.py
	$(PYTHON) -m build --wheel --no-isolation
	$(PYTHON) scripts/verify_package.py

run:
	$(PYTHON) -m uvicorn triager.app:app --host 127.0.0.1 --port 8000 --no-access-log

eval:
	$(PYTHON) -m evals.benchmark --output /tmp/desk-benchmark.json
	$(PYTHON) -m evals.security --output /tmp/desk-security.json
	$(PYTHON) -m evals.detection --output /tmp/desk-detection.json

verify:
	$(PYTHON) scripts/verify_services.py
