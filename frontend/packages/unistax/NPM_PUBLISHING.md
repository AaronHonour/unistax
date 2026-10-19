# Publishing @unistax/frontend to npm

This guide covers how to publish the `@unistax/frontend` npm package.

## Prerequisites

1. **Create npm account:**
   - Sign up at https://www.npmjs.com/signup

2. **Login to npm:**
   ```bash
   npm login
   # Enter username, password, and email
   # You'll receive a one-time password via email
   ```

3. **Verify login:**
   ```bash
   npm whoami
   # Should display your username
   ```

## Claiming the Package Namespace

### Check Availability

```bash
# Check if @unistax scope is available
npm search @unistax
# Or visit: https://www.npmjs.com/package/@unistax/frontend
```

### Scoped Packages (@unistax/*)

Scoped packages under `@unistax` allow us to:
- Publish multiple related packages under one namespace
- Avoid name conflicts with other packages
- Organize packages logically

**Important:** To publish scoped packages for free, they must be public. Use:
```json
{
  "publishConfig": {
    "access": "public"
  }
}
```

This is already configured in `package.json`.

### First-Time Publishing

When you publish for the first time, you'll claim the `@unistax` scope:

```bash
cd frontend/packages/unistax
npm publish --access public
```

After the first publish, only you (or collaborators you add) can publish packages under `@unistax/*`.

## Publishing Workflow

### 1. Update Version

Edit `package.json`:
```json
{
  "version": "0.5.1"  // Increment version
}
```

Or use npm's version command:
```bash
npm version patch  # 0.5.0 → 0.5.1
npm version minor  # 0.5.0 → 0.6.0
npm version major  # 0.5.0 → 1.0.0
```

### 2. Build the Package

```bash
cd frontend/packages/unistax
bash scripts/build.sh
```

This will:
- Clean previous builds
- Run rollup to build JavaScript
- Build Tailwind CSS
- Output to `dist/` directory

### 3. Test Before Publishing

```bash
# Dry run to see what would be published
npm pack --dry-run

# Or create a tarball to test locally
npm pack
# Creates: unistax-frontend-0.5.0.tgz

# Test installation in another project
cd /path/to/test/project
npm install /path/to/unistax-frontend-0.5.0.tgz
```

### 4. Publish to npm

```bash
# Using the publish script (recommended)
bash scripts/publish.sh

# Or manually
npm publish --access public
```

The `prepublishOnly` script will automatically:
- Run the build
- Run tests
- Ensure everything is ready

### 5. Verify Publication

```bash
# Check on npm
npm view @unistax/frontend

# Install from npm
npm install @unistax/frontend
```

Visit https://www.npmjs.com/package/@unistax/frontend to see your package live!

## What Gets Published?

The `files` field in `package.json` controls what's included:

```json
{
  "files": [
    "dist",
    "src"
  ]
}
```

Additional files always included:
- `package.json`
- `README.md`
- `LICENSE`

Files excluded via `.npmignore`:
- Tests
- Build configuration
- Development files

## Version Management

Follow [Semantic Versioning](https://semver.org/):

- **0.5.0** → **0.5.1**: Bug fixes (PATCH)
- **0.5.0** → **0.6.0**: New features, backward compatible (MINOR)
- **0.5.0** → **1.0.0**: Breaking changes (MAJOR)

Current version: **0.5.0** (Beta)

## Package Exports

The package is configured with modern exports:

```json
{
  "exports": {
    ".": {
      "import": "./dist/index.esm.js",  // ESM
      "require": "./dist/index.js",      // CommonJS
      "types": "./dist/index.d.ts"       // TypeScript
    },
    "./styles.css": "./dist/styles.css"  // CSS import
  }
}
```

Users can import like:
```javascript
// ESM
import { Component } from '@unistax/frontend';
import '@unistax/frontend/styles.css';

// CommonJS
const { Component } = require('@unistax/frontend');
```

## Adding Collaborators

To allow others to publish under `@unistax`:

```bash
# Add a collaborator
npm owner add <username> @unistax/frontend

# List current owners
npm owner ls @unistax/frontend

# Remove a collaborator
npm owner rm <username> @unistax/frontend
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Publish to npm

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          registry-url: 'https://registry.npmjs.org'

      - name: Install dependencies
        run: |
          cd frontend/packages/unistax
          npm ci

      - name: Build package
        run: |
          cd frontend/packages/unistax
          npm run build

      - name: Publish to npm
        run: |
          cd frontend/packages/unistax
          npm publish --access public
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

### Setting up NPM_TOKEN

1. Generate an access token:
   - Go to https://www.npmjs.com/settings/YOUR_USERNAME/tokens
   - Create "Automation" token
   - Copy the token

2. Add to GitHub:
   - Go to repository Settings → Secrets and variables → Actions
   - Create new secret: `NPM_TOKEN`
   - Paste your npm token

## Managing Multiple Packages

If you want to publish other packages under `@unistax`:

```
@unistax/frontend      - Frontend components
@unistax/design-tokens - Design system tokens
@unistax/performance   - Performance utilities
@unistax/layouts       - Layout components
@unistax/atoms         - Atomic components
```

Each package needs its own:
- `package.json` with unique name
- Build process
- Version management

## Troubleshooting

### "Package name too similar"

npm may reject packages with names too similar to existing ones. Use a scope to avoid this.

### "You do not have permission"

- Not logged in: `npm login`
- Not an owner: Ask an existing owner to add you
- Wrong scope: Check package name in `package.json`

### "Package already exists"

- Someone else owns the scope
- You're trying to publish an existing version
- Solution: Increment version or choose different name

### "403 Forbidden"

- Check you're logged in: `npm whoami`
- Verify `publishConfig.access` is set to `"public"`
- Ensure you're an owner: `npm owner ls @unistax/frontend`

### Build errors

```bash
# Clean and rebuild
rm -rf dist node_modules
npm install
npm run build
```

## Best Practices

1. **Always test before publishing:**
   ```bash
   npm pack --dry-run
   ```

2. **Use semantic versioning consistently**

3. **Keep dependencies updated:**
   ```bash
   npm outdated
   npm update
   ```

4. **Document breaking changes** in README and CHANGELOG

5. **Tag releases on GitHub** matching npm versions:
   ```bash
   git tag v0.5.0
   git push --tags
   ```

6. **Use `.npmignore`** to keep published package lean

7. **Test installation** in a separate project before publishing

## Resources

- [npm Documentation](https://docs.npmjs.com/)
- [Scoped Packages](https://docs.npmjs.com/about-scopes)
- [Semantic Versioning](https://semver.org/)
- [Publishing Guide](https://docs.npmjs.com/packages-and-modules/contributing-packages-to-the-registry)
