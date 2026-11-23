.PHONY: all build publish publish-test clean test test-coverage serve bump-version

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

publish:
	uv publish

publish-test:
	uv publish --repository testpypi

# Used by the Bump Version workflow: PART is major, minor or patch.
bump-version:
	uv run --frozen bump-my-version bump $(PART)

clean:
	rm -rf ./build ./dist ./htmlcov ./coverage.xml ./.coverage
