.PHONY: install install-browsers test test-unit test-integration validate run-api run-web

install:
	pip install -r apps/api/requirements.txt

install-browsers:
	python -m playwright install chromium

test:
	PYTHONPATH=. pytest

test-unit:
	PYTHONPATH=. pytest -m "not integration"

test-integration:
	PYTHONPATH=. pytest -m integration

validate:
	PYTHONPATH=. python scripts/validate.py

run-api:
	PYTHONPATH=. uvicorn apps.api.app.main:app --reload

run-web:
	cd apps/web && npm install && npm run dev
