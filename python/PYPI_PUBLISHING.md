# Publishing unistax to PyPI

This guide covers how to publish the `unistax` Python package to PyPI.

## Prerequisites

1. **Create PyPI accounts:**
   - Production: https://pypi.org/account/register/
   - Test: https://test.pypi.org/account/register/

2. **Generate API tokens:**
   - Go to Account Settings → API tokens
   - Create a token for "Entire account" or specific project
   - Save the token securely (starts with `pypi-AgEI...`)

3. **Configure credentials:**
   ```bash
   # Create ~/.pypirc file
   cp .pypirc.example ~/.pypirc
   # Edit ~/.pypirc and add your API tokens
   # IMPORTANT: Keep this file secure and never commit it!
   ```

## Claiming the Package Namespace

### Check Availability

```bash
# Check if 'unistax' is available on PyPI
pip search unistax
# Or visit: https://pypi.org/project/unistax/
```

### First-Time Publishing

The first time you publish, you'll claim the `unistax` namespace:

```bash
# Test on TestPyPI first (recommended)
cd python
bash scripts/publish.sh testpypi

# If successful, publish to production PyPI
bash scripts/publish.sh pypi
```

Once published, you'll own the `unistax` namespace and only you (or collaborators you add) can publish updates.

## Publishing Workflow

### 1. Update Version

Edit `pyproject.toml`:
```toml
[project]
name = "unistax"
version = "0.5.1"  # Increment version
```

### 2. Build the Package

```bash
cd python
bash scripts/build.sh
```

This will:
- Clean old builds
- Create source distribution (`.tar.gz`)
- Create wheel distribution (`.whl`)
- Output files in `dist/` directory

### 3. Test on TestPyPI (Recommended)

```bash
# Publish to TestPyPI
bash scripts/publish.sh testpypi

# Test installation
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            unistax
```

### 4. Publish to Production PyPI

```bash
# After testing, publish to production
bash scripts/publish.sh pypi
```

### 5. Verify Installation

```bash
# Test installation from PyPI
pip install unistax

# Or with specific extras
pip install unistax[database,cache,api]
pip install unistax[all]  # All optional dependencies
```

## Manual Publishing (Alternative)

If you prefer manual control:

```bash
# Build
python -m build

# Check distribution
python -m twine check dist/*

# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*

# Upload to PyPI
python -m twine upload dist/*
```

## Version Management

Follow [Semantic Versioning](https://semver.org/):

- **0.5.0** → **0.5.1**: Bug fixes (PATCH)
- **0.5.0** → **0.6.0**: New features, backward compatible (MINOR)
- **0.5.0** → **1.0.0**: Breaking changes (MAJOR)

Current version: **0.5.0** (Beta)

## Package Metadata

The package is configured with:

- **Name**: `unistax`
- **Author**: Aaron Honour
- **License**: MIT
- **Repository**: https://github.com/AaronHonour/unistax
- **Python**: >=3.10

## Extras Available

Users can install optional dependencies:

```bash
pip install unistax[database]     # Database support
pip install unistax[cache]        # Redis, Memcached
pip install unistax[api]          # FastAPI, Uvicorn
pip install unistax[tracing]      # OpenTelemetry
pip install unistax[tasks]        # Celery, APScheduler
pip install unistax[storage]      # S3, Azure, GCS
pip install unistax[queue]        # Message queues
pip install unistax[notifications] # Twilio, SendGrid
pip install unistax[security]     # bcrypt, PyJWT
pip install unistax[performance]  # orjson, msgpack, lz4
pip install unistax[all]          # Everything
pip install unistax[dev]          # Development tools
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          cd python
          pip install build twine

      - name: Build package
        run: |
          cd python
          python -m build

      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: |
          cd python
          python -m twine upload dist/*
```

## Troubleshooting

### "Package already exists"

If you get this error:
- You don't own the namespace (someone else published first)
- Choose a different name or contact PyPI support

### "Invalid credentials"

- Check your `~/.pypirc` file
- Verify API token is correct
- Ensure token has proper permissions

### "Distribution already exists"

- You're trying to upload the same version twice
- Increment version in `pyproject.toml` and rebuild

### Import errors after installation

```bash
# Ensure you're in a fresh environment
pip install --upgrade unistax

# Or with all dependencies
pip install unistax[all]
```

## Resources

- [PyPI Help](https://pypi.org/help/)
- [Python Packaging Guide](https://packaging.python.org/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [PEP 517/518](https://peps.python.org/pep-0517/) - Build system standards
