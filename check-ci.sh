#!/usr/bin/env bash
# Simple CI check script - runs lint and tests locally

set -e

# Activate venv if not already activated
if [ -z "$VIRTUAL_ENV" ]; then
    source .venv/bin/activate
fi

echo "Running local CI checks..."
echo ""

# Lint check
echo "Running ruff lint..."
python -m ruff check .
echo "Lint passed"
echo ""

# Tests
echo "Running pytest..."
pytest tests/ -q
echo "Tests passed"
echo ""

echo "All checks passed! Ready to push."
