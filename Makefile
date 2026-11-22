.PHONY: all build test test-coverage serve demo clean

all: build test

test:
	uv run pytest

# Terminal summary plus coverage.xml and htmlcov/ (settings in pyproject.toml).
test-coverage:
	uv run pytest --cov --cov-report=term --cov-report=xml --cov-report=html

# Serve the project above the current directory, and open a browser.
serve:
	uv run szsdlc-ui-win95 --open

build:
	uv build

clean:
	rm -rf ./build ./dist ./htmlcov ./coverage.xml ./.coverage
