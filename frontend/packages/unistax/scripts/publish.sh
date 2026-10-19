#!/bin/bash
# Publish script for @unistax/frontend npm package

set -e

# Check if we're in the right directory
if [ ! -f "package.json" ]; then
    echo "❌ Error: Must run from packages/unistax/ directory"
    exit 1
fi

# Check if logged in to npm
if ! npm whoami &> /dev/null; then
    echo "❌ Error: Not logged in to npm"
    echo "Run: npm login"
    exit 1
fi

# Parse arguments
DRY_RUN="${1:-false}"

echo "📦 Publishing @unistax/frontend..."

# Ensure we have the latest version built
if [ ! -d "dist" ] || [ -z "$(ls -A dist)" ]; then
    echo "No dist/ directory found. Running build first..."
    bash scripts/build.sh
fi

# Run tests
echo "Running tests..."
npm test

# Run linter
echo "Running linter..."
npm run lint

# Check package contents
echo "Checking package contents..."
npm pack --dry-run

if [ "$DRY_RUN" = "true" ] || [ "$1" = "--dry-run" ]; then
    echo "🔍 Dry run complete. Package would include:"
    npm pack --dry-run
    echo ""
    echo "To publish for real, run without --dry-run"
    exit 0
fi

# Confirm publication
echo ""
CURRENT_VERSION=$(node -p "require('./package.json').version")
echo "⚠️  WARNING: You are about to publish @unistax/frontend@$CURRENT_VERSION to npm!"
read -p "Are you sure? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Publish
echo "Publishing..."
npm publish --access public

echo ""
echo "✅ Published successfully!"
echo "Install with:"
echo "  npm install @unistax/frontend"
echo ""
echo "View on npm:"
echo "  https://www.npmjs.com/package/@unistax/frontend"
