#!/bin/bash
# Publish script for unistax Python package

set -e

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo "❌ Error: Must run from python/ directory"
    exit 1
fi

# Parse arguments
REPO="${1:-testpypi}"

if [ "$REPO" != "pypi" ] && [ "$REPO" != "testpypi" ]; then
    echo "❌ Error: Repository must be 'pypi' or 'testpypi'"
    echo "Usage: $0 [pypi|testpypi]"
    exit 1
fi

echo "📦 Publishing unistax to $REPO..."

# Ensure we have the latest version built
if [ ! -d "dist" ] || [ -z "$(ls -A dist)" ]; then
    echo "No dist/ directory found. Running build first..."
    bash scripts/build.sh
fi

# Check credentials
if [ "$REPO" = "pypi" ]; then
    echo "⚠️  WARNING: You are about to publish to PRODUCTION PyPI!"
    read -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Aborted."
        exit 0
    fi
fi

# Install twine if not available
pip install --upgrade twine

# Check the distribution
echo "Checking package..."
python -m twine check dist/*

# Upload
echo "Uploading to $REPO..."
if [ "$REPO" = "testpypi" ]; then
    python -m twine upload --repository testpypi dist/*
else
    python -m twine upload dist/*
fi

echo ""
echo "✅ Published successfully!"
if [ "$REPO" = "testpypi" ]; then
    echo "Test install with:"
    echo "  pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ unistax"
else
    echo "Install with:"
    echo "  pip install unistax"
fi
