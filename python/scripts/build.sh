#!/bin/bash
# Build script for unistax Python package

set -e

echo "🔨 Building unistax Python package..."

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf dist/ build/ *.egg-info src/*.egg-info

# Install build dependencies
echo "Installing build dependencies..."
pip install --upgrade build twine

# Build the package
echo "Building package..."
python -m build

# List built files
echo ""
echo "✅ Build complete! Files created:"
ls -lh dist/

echo ""
echo "To publish to TestPyPI:"
echo "  python -m twine upload --repository testpypi dist/*"
echo ""
echo "To publish to PyPI:"
echo "  python -m twine upload dist/*"
