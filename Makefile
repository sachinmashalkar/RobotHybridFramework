.PHONY: help install dev-install dry-run test smoke ui api parallel grid docker-grid-up docker-grid-down clean lint format report hooks

PY ?= python3
ROBOT_TAGS ?=

help:
	@echo "Targets:"
	@echo "  install          - install runtime dependencies"
	@echo "  dev-install      - install runtime + pre-commit hooks"
	@echo "  dry-run          - resolve suites without running (offline lint)"
	@echo "  test             - run the full suite"
	@echo "  smoke            - run tests tagged 'smoke'"
	@echo "  ui               - run UI suites"
	@echo "  api              - run API suites"
	@echo "  parallel         - run full suite with pabot (PROCESSES=4)"
	@echo "  grid             - run full suite against local grid (USE_GRID=true)"
	@echo "  docker-grid-up   - bring up docker-compose Selenium grid"
	@echo "  docker-grid-down - tear down grid"
	@echo "  lint             - run robocop"
	@echo "  format           - run robotidy"
	@echo "  report           - regenerate metrics + allure from last run"
	@echo "  clean            - remove results/, __pycache__, logs"

install:
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt

dev-install: install hooks

hooks:
	pre-commit install || true

dry-run:
	bash scripts/dry_run.sh

test:
	bash scripts/run_tests.sh

smoke:
	bash scripts/run_tests.sh --tags smoke

ui:
	bash scripts/run_tests.sh --suite tests/ui

api:
	bash scripts/run_tests.sh --suite tests/api

parallel:
	bash scripts/run_tests.sh --parallel $${PROCESSES:-4}

grid:
	USE_GRID=true bash scripts/run_tests.sh --browser chrome

docker-grid-up:
	docker compose -f docker/docker-compose.yml up -d selenium-hub chrome firefox

docker-grid-down:
	docker compose -f docker/docker-compose.yml down

lint:
	robocop resources tests libraries

format:
	robotidy resources tests

report:
	bash scripts/generate_report.sh

clean:
	rm -rf results/ logs/ report.html log.html output.xml selenium-screenshot-*.png
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
