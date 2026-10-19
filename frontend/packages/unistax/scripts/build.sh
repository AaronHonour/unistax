#!/bin/bash
# Build script for @unistax/frontend npm package

set -e

echo "🔨 Building @unistax/frontend package..."

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf dist/

# Build the package
echo "Building package with rollup..."
npm run build

# Build CSS
echo "Building Tailwind CSS..."
cd ../../..
npm run build:css
cd frontend/packages/unistax

# List built files
echo ""
echo "✅ Build complete! Files created:"
ls -lh dist/

echo ""
echo "To test the package locally:"
echo "  npm pack"
echo "  npm install /path/to/unistax-frontend-0.5.0.tgz"
echo ""
echo "To publish:"
echo "  npm publish"
