# Unistax Publishing Guide

Complete guide for publishing both Python (PyPI) and npm packages.

## Overview

The Unistax project consists of two main publishable packages:

1. **Python Package** (`unistax`) - Backend framework
2. **npm Package** (`@unistax/frontend`) - Frontend components

Both packages should maintain version synchronization where possible.

## Current Version

**Version: 0.5.0** (Beta)

## Quick Links

- **PyPI Publishing**: [python/PYPI_PUBLISHING.md](python/PYPI_PUBLISHING.md)
- **npm Publishing**: [frontend/packages/unistax/NPM_PUBLISHING.md](frontend/packages/unistax/NPM_PUBLISHING.md)

## Prerequisites

### For PyPI (Python)

1. Accounts:
   - PyPI: https://pypi.org/account/register/
   - TestPyPI: https://test.pypi.org/account/register/

2. Tools:
   ```bash
   pip install build twine
   ```

3. Credentials:
   - Generate API tokens on PyPI
   - Configure `~/.pypirc` (see `python/.pypirc.example`)

### For npm (JavaScript)

1. Account:
   - npm: https://www.npmjs.com/signup

2. Tools:
   ```bash
   npm login
   ```

3. Verify:
   ```bash
   npm whoami
   ```

## Publishing Checklist

### Pre-Release

- [ ] All tests passing (`pytest`, `npm test`)
- [ ] All linting passing (`ruff`, `black`, `eslint`)
- [ ] Type checking passing (`mypy`, `tsc`)
- [ ] CI/CD green on main branch
- [ ] Version bumped in both packages
- [ ] CHANGELOG updated
- [ ] README updated if needed
- [ ] Breaking changes documented

### Python Package (PyPI)

```bash
# 1. Navigate to Python package
cd python

# 2. Update version in pyproject.toml
# Edit: version = "0.5.1"

# 3. Build
bash scripts/build.sh

# 4. Test on TestPyPI
bash scripts/publish.sh testpypi

# 5. Test installation
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            unistax

# 6. Publish to PyPI
bash scripts/publish.sh pypi

# 7. Verify
pip install unistax
```

### npm Package

```bash
# 1. Navigate to npm package
cd frontend/packages/unistax

# 2. Update version in package.json
npm version patch  # or minor, major

# 3. Build
bash scripts/build.sh

# 4. Test locally
npm pack --dry-run

# 5. Publish
bash scripts/publish.sh

# 6. Verify
npm install @unistax/frontend
```

### Post-Release

- [ ] Create GitHub release with tag
- [ ] Update documentation site
- [ ] Announce on social media/blog
- [ ] Update examples to use new version
- [ ] Monitor for issues

## Version Synchronization

Keep versions synchronized between packages:

| Version | Type    | Python | npm | Notes |
|---------|---------|--------|-----|-------|
| 0.5.0   | Current | ✅     | ✅  | Beta release |
| 0.5.1   | Patch   | 🔄     | 🔄  | Bug fixes only |
| 0.6.0   | Minor   | 🔄     | 🔄  | New features |
| 1.0.0   | Major   | 🔄     | 🔄  | Breaking changes |

## Semantic Versioning

Follow [SemVer](https://semver.org/):

- **MAJOR** (1.0.0): Breaking changes
- **MINOR** (0.5.0): New features, backward compatible
- **PATCH** (0.5.1): Bug fixes only

### Examples:

```bash
# Patch: Bug fixes
0.5.0 → 0.5.1

# Minor: New features
0.5.0 → 0.6.0

# Major: Breaking changes
0.5.0 → 1.0.0

# Pre-release
1.0.0-alpha.1
1.0.0-beta.1
1.0.0-rc.1
```

## Namespace Ownership

### PyPI: `unistax`

Once published, you own the `unistax` namespace on PyPI.

- **Check availability**: https://pypi.org/project/unistax/
- **Collaborators**: Manage via PyPI project settings

### npm: `@unistax/*`

Scoped packages under `@unistax` allow multiple related packages.

- **Main package**: `@unistax/frontend`
- **Future packages**: `@unistax/design-tokens`, `@unistax/performance`, etc.
- **Collaborators**: `npm owner add <username> @unistax/frontend`

## CI/CD Automation

### GitHub Actions Workflow

Create `.github/workflows/publish.yml`:

```yaml
name: Publish Packages

on:
  release:
    types: [published]

jobs:
  publish-python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Build and publish
        run: |
          cd python
          pip install build twine
          python -m build
          python -m twine upload dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}

  publish-npm:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          registry-url: 'https://registry.npmjs.org'
      - name: Build and publish
        run: |
          cd frontend/packages/unistax
          npm ci
          npm run build
          npm publish --access public
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

### Required Secrets

Add to GitHub repository settings:

- `PYPI_API_TOKEN`: From https://pypi.org/manage/account/token/
- `NPM_TOKEN`: From https://www.npmjs.com/settings/tokens

## Manual Release Process

### 1. Prepare Release

```bash
# Update versions
cd python && vim pyproject.toml  # Update version
cd ../frontend/packages/unistax && npm version patch

# Run tests
cd python && pytest
cd ../frontend && npm test

# Commit version bump
git add .
git commit -m "chore: bump version to 0.5.1"
git push
```

### 2. Create Tag

```bash
git tag -a v0.5.1 -m "Release v0.5.1"
git push origin v0.5.1
```

### 3. Publish Packages

```bash
# Python
cd python
bash scripts/publish.sh pypi

# npm
cd frontend/packages/unistax
bash scripts/publish.sh
```

### 4. Create GitHub Release

- Go to https://github.com/AaronHonour/unistax/releases/new
- Choose tag: v0.5.1
- Title: "Release v0.5.1"
- Description: List changes from CHANGELOG
- Publish release

## Troubleshooting

### Version Conflicts

```bash
# Python: Already published this version
# Solution: Increment version and rebuild

# npm: Already published this version
npm version patch
npm publish
```

### Authentication Errors

```bash
# PyPI
cat ~/.pypirc  # Verify credentials

# npm
npm whoami     # Check login status
npm login      # Re-login if needed
```

### Build Failures

```bash
# Python
cd python
rm -rf dist build *.egg-info
bash scripts/build.sh

# npm
cd frontend/packages/unistax
rm -rf dist node_modules
npm install
npm run build
```

## Resources

- [Semantic Versioning](https://semver.org/)
- [PyPI Documentation](https://pypi.org/help/)
- [npm Documentation](https://docs.npmjs.com/)
- [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github)
- [Keep a Changelog](https://keepachangelog.com/)

## Support

For issues with publishing:
- PyPI: https://pypi.org/help/
- npm: https://www.npmjs.com/support
- GitHub: https://github.com/AaronHonour/unistax/issues
