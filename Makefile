# Makefile for builder.py project

.PHONY: help install test demo clean lint type-check all

help: ## Show this help message
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## No dependencies to install (uses Python standard library only)
	@echo "No dependencies needed - builder.py uses only Python standard library"

test: ## Run unit tests
	python -m unittest test_builder.py -v

demo: ## Run demonstration
	python demo.py

clean: ## Clean cache and temporary files
	rm -rf ~/.cache/builder
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -delete

lint: ## Run linting (requires pylint)
	@if command -v pylint >/dev/null 2>&1; then \
		pylint builder.py test_builder.py setup.py demo.py; \
	else \
		echo "pylint not found. Install with: pip install pylint"; \
	fi

type-check: ## Run type checking (requires mypy)
	@if command -v mypy >/dev/null 2>&1; then \
		mypy builder.py; \
	else \
		echo "mypy not found. Install with: pip install mypy"; \
	fi

all: install test ## Install dependencies and run tests

# Test with different builder versions
test-v1.0.0: ## Test with builder version 1.0.0
	sed 's/1\.0\.2/1.0.0/g' builder.yaml > builder.yaml.tmp && mv builder.yaml.tmp builder.yaml
	./builder.py --version

test-v1.0.1: ## Test with builder version 1.0.1
	sed 's/1\.0\.[02]/1.0.1/g' builder.yaml > builder.yaml.tmp && mv builder.yaml.tmp builder.yaml
	./builder.py --version

test-v1.0.2: ## Test with builder version 1.0.2
	sed 's/1\.0\.[01]/1.0.2/g' builder.yaml > builder.yaml.tmp && mv builder.yaml.tmp builder.yaml
	./builder.py --version