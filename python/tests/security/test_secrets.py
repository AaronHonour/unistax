"""Tests for secrets management implementation."""

import json
import os

import pytest

from unistax.secrets import (
    EnvironmentBackend,
    FileBackend,
    SecretAccessDenied,
    SecretInvalidFormat,
    SecretManager,
    SecretNotFound,
)


@pytest.mark.unit
@pytest.mark.secrets
class TestEnvironmentBackend:
    """Test environment variable backend."""

    def test_get_secret(self):
        """Test getting secret from environment."""
        os.environ["TEST_SECRET"] = "test-value"
        backend = EnvironmentBackend()

        value = backend.get_secret("TEST_SECRET")
        assert value == "test-value"

        # Cleanup
        del os.environ["TEST_SECRET"]

    def test_get_secret_not_found(self):
        """Test getting non-existent secret."""
        backend = EnvironmentBackend()

        with pytest.raises(SecretNotFound):
            backend.get_secret("NONEXISTENT_SECRET")

    def test_get_secret_with_default(self):
        """Test getting secret with default value."""
        backend = EnvironmentBackend()

        value = backend.get_secret("NONEXISTENT_SECRET", default="default-value")
        assert value == "default-value"

    def test_set_secret(self):
        """Test setting secret in environment."""
        backend = EnvironmentBackend()

        backend.set_secret("NEW_SECRET", "new-value")
        assert os.environ["NEW_SECRET"] == "new-value"

        # Cleanup
        del os.environ["NEW_SECRET"]

    def test_delete_secret(self):
        """Test deleting secret from environment."""
        os.environ["DELETE_ME"] = "value"
        backend = EnvironmentBackend()

        backend.delete_secret("DELETE_ME")
        assert "DELETE_ME" not in os.environ

    def test_list_secrets(self):
        """Test listing secrets."""
        # Set up test secrets
        os.environ["APP_SECRET_1"] = "value1"
        os.environ["APP_SECRET_2"] = "value2"
        os.environ["OTHER_VAR"] = "value3"

        backend = EnvironmentBackend(prefix="APP_")

        secrets = backend.list_secrets()
        assert "secret_1" in secrets
        assert "secret_2" in secrets

        # Cleanup
        del os.environ["APP_SECRET_1"]
        del os.environ["APP_SECRET_2"]
        del os.environ["OTHER_VAR"]

    def test_prefix_support(self):
        """Test environment backend with prefix."""
        os.environ["MYAPP_DATABASE_URL"] = "postgres://..."
        backend = EnvironmentBackend(prefix="MYAPP_")

        value = backend.get_secret("DATABASE_URL")
        assert value == "postgres://..."

        # Cleanup
        del os.environ["MYAPP_DATABASE_URL"]

    def test_case_sensitivity(self):
        """Test case sensitivity modes."""
        # Environment variable names are case sensitive on POSIX, so
        # "case insensitive" means keys are upper-cased before lookup.
        os.environ["MYSECRET"] = "value"
        try:
            insensitive = EnvironmentBackend(case_sensitive=False)
            assert insensitive.get_secret("mysecret") == "value"
            assert insensitive.get_secret("MySecret") == "value"

            sensitive = EnvironmentBackend(case_sensitive=True)
            with pytest.raises(SecretNotFound):
                sensitive.get_secret("mysecret")
        finally:
            del os.environ["MYSECRET"]

    def test_from_dotenv(self, tmp_path):
        """Test loading from .env file."""
        # Create .env file
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DATABASE_URL=postgres://localhost/db\n"
            "API_KEY=secret-key\n"
            "# Comment line\n"
            "\n"
            "DEBUG=true\n"
        )

        backend = EnvironmentBackend.from_dotenv(str(env_file))

        assert backend.get_secret("DATABASE_URL") == "postgres://localhost/db"
        assert backend.get_secret("API_KEY") == "secret-key"
        assert backend.get_secret("DEBUG") == "true"

        # Cleanup
        del os.environ["DATABASE_URL"]
        del os.environ["API_KEY"]
        del os.environ["DEBUG"]

    def test_from_dotenv_nonexistent(self, caplog):
        """Test loading from nonexistent .env file."""
        _ = EnvironmentBackend.from_dotenv("/nonexistent/.env")
        assert any("not found" in record.message for record in caplog.records)


@pytest.mark.unit
@pytest.mark.secrets
class TestFileBackend:
    """Test file-based secret backend."""

    def test_basic_operations(self, tmp_path):
        """Test basic file backend operations."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file), mode=0o600)

        # Set secrets
        backend.set_secret("db/password", "secret123")
        backend.set_secret("api/key", "api-key-123")

        # Get secrets
        assert backend.get_secret("db/password") == "secret123"
        assert backend.get_secret("api/key") == "api-key-123"

    def test_get_secret_not_found(self, tmp_path):
        """Test getting non-existent secret."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))

        with pytest.raises(SecretNotFound):
            backend.get_secret("nonexistent")

    def test_get_secret_with_default(self, tmp_path):
        """Test getting secret with default value."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))

        value = backend.get_secret("nonexistent", default="default-value")
        assert value == "default-value"

    def test_delete_secret(self, tmp_path):
        """Test deleting secret."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))

        backend.set_secret("temp", "value")
        assert backend.get_secret("temp") == "value"

        backend.delete_secret("temp")

        with pytest.raises(SecretNotFound):
            backend.get_secret("temp")

    def test_list_secrets(self, tmp_path):
        """Test listing secrets."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))

        backend.set_secret("database/password", "pass1")
        backend.set_secret("database/username", "user1")
        backend.set_secret("api/key", "key1")

        all_secrets = backend.list_secrets()
        assert "database/password" in all_secrets
        assert "database/username" in all_secrets
        assert "api/key" in all_secrets

        database_secrets = backend.list_secrets("database/")
        assert "database/password" in database_secrets
        assert "database/username" in database_secrets
        assert "api/key" not in database_secrets

    def test_readonly_mode(self, tmp_path):
        """Test read-only mode."""
        secrets_file = tmp_path / "secrets.json"

        # Create file with initial data
        with open(secrets_file, "w") as f:
            json.dump({"existing": "value"}, f)

        # Open in read-only mode
        backend = FileBackend(str(secrets_file), readonly=True)

        # Reading should work
        assert backend.get_secret("existing") == "value"

        # Writing should fail
        with pytest.raises(SecretAccessDenied):
            backend.set_secret("new", "value")

        with pytest.raises(SecretAccessDenied):
            backend.delete_secret("existing")

    def test_file_permissions(self, tmp_path):
        """Test file permissions enforcement."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file), mode=0o600)

        backend.set_secret("test", "value")

        # Check file permissions
        stat = secrets_file.stat()
        mode = stat.st_mode & 0o777
        assert mode == 0o600

    def test_insecure_permissions_warning(self, tmp_path, caplog):
        """Test warning for insecure permissions."""
        secrets_file = tmp_path / "secrets.json"

        # Create file with insecure permissions
        secrets_file.write_text("{}")
        secrets_file.chmod(0o644)  # World-readable

        # Opening should warn
        _ = FileBackend(str(secrets_file))
        assert any("insecure permissions" in record.message for record in caplog.records)

    def test_invalid_json(self, tmp_path):
        """Test handling of invalid JSON."""
        secrets_file = tmp_path / "secrets.json"
        secrets_file.write_text("invalid json{")

        with pytest.raises(SecretInvalidFormat):
            FileBackend(str(secrets_file))

    def test_reload(self, tmp_path):
        """Test reloading secrets from file."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))

        backend.set_secret("key1", "value1")

        # Modify file externally
        with open(secrets_file, "w") as f:
            json.dump({"key1": "new-value", "key2": "value2"}, f)

        # Reload
        backend.reload()

        assert backend.get_secret("key1") == "new-value"
        assert backend.get_secret("key2") == "value2"


@pytest.mark.unit
@pytest.mark.secrets
class TestSecretManager:
    """Test secret manager."""

    def test_basic_get(self, tmp_path):
        """Test basic secret retrieval."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        backend.set_secret("API_KEY", "secret-key")

        value = manager.get("API_KEY")
        assert value == "secret-key"

    def test_get_with_default(self, tmp_path):
        """Test getting secret with default value."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        value = manager.get("NONEXISTENT", default="default-value")
        assert value == "default-value"

    def test_get_int(self, tmp_path):
        """Test getting secret as integer."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        backend.set_secret("PORT", "8080")

        port = manager.get_int("PORT")
        assert port == 8080
        assert isinstance(port, int)

    def test_get_int_invalid(self, tmp_path):
        """Test getting invalid integer."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        backend.set_secret("PORT", "not-a-number")

        with pytest.raises(SecretInvalidFormat):
            manager.get_int("PORT")

    def test_get_float(self, tmp_path):
        """Test getting secret as float."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        backend.set_secret("RATE_LIMIT", "100.5")

        rate = manager.get_float("RATE_LIMIT")
        assert rate == 100.5
        assert isinstance(rate, float)

    def test_get_bool(self, tmp_path):
        """Test getting secret as boolean."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("yes", True),
            ("1", True),
            ("on", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("no", False),
            ("0", False),
            ("off", False),
        ]

        for value_str, expected in test_cases:
            backend.set_secret("DEBUG", value_str)
            result = manager.get_bool("DEBUG")
            assert result == expected

    def test_get_bool_invalid(self, tmp_path):
        """Test getting invalid boolean."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        backend.set_secret("DEBUG", "maybe")

        with pytest.raises(SecretInvalidFormat):
            manager.get_bool("DEBUG")

    def test_get_json(self, tmp_path):
        """Test getting secret as JSON."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        config = {"database": "postgres", "port": 5432, "ssl": True}
        backend.set_secret("CONFIG", json.dumps(config))

        result = manager.get_json("CONFIG")
        assert result == config

    def test_get_json_invalid(self, tmp_path):
        """Test getting invalid JSON."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        backend.set_secret("CONFIG", "invalid json{")

        with pytest.raises(SecretInvalidFormat):
            manager.get_json("CONFIG")

    def test_get_list(self, tmp_path):
        """Test getting secret as list."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        backend.set_secret("ALLOWED_HOSTS", "localhost,example.com,*.example.org")

        hosts = manager.get_list("ALLOWED_HOSTS")
        assert hosts == ["localhost", "example.com", "*.example.org"]

    def test_get_list_custom_separator(self, tmp_path):
        """Test getting list with custom separator."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        backend.set_secret("TAGS", "tag1:tag2:tag3")

        tags = manager.get_list("TAGS", separator=":")
        assert tags == ["tag1", "tag2", "tag3"]

    def test_caching(self, tmp_path):
        """Test secret caching."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend, cache_ttl=60)

        backend.set_secret("API_KEY", "value1")

        # First access - cache miss
        value1 = manager.get("API_KEY")
        assert value1 == "value1"

        # Modify secret in backend
        backend.set_secret("API_KEY", "value2")

        # Second access - should return cached value
        value2 = manager.get("API_KEY")
        assert value2 == "value1"  # Still cached

        # Clear cache
        manager.clear_cache()

        # Should get new value
        value3 = manager.get("API_KEY")
        assert value3 == "value2"

    def test_multiple_backends_fallback(self, tmp_path):
        """Test fallback across multiple backends."""
        secrets_file = tmp_path / "secrets.json"
        file_backend = FileBackend(str(secrets_file))
        env_backend = EnvironmentBackend()

        file_backend.set_secret("FILE_SECRET", "from-file")
        os.environ["ENV_SECRET"] = "from-env"

        # Try env first, then file
        manager = SecretManager([env_backend, file_backend])

        assert manager.get("ENV_SECRET") == "from-env"
        assert manager.get("FILE_SECRET") == "from-file"

        # Cleanup
        del os.environ["ENV_SECRET"]

    def test_required_secrets(self, tmp_path):
        """Test required secrets validation."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))

        backend.set_secret("SECRET_KEY", "key123")
        backend.set_secret("DATABASE_URL", "postgres://...")

        # Should succeed with all required secrets present
        _ = SecretManager(
            backend,
            required_secrets=["SECRET_KEY", "DATABASE_URL"],
        )

    def test_missing_required_secrets(self, tmp_path):
        """Test missing required secrets."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))

        backend.set_secret("SECRET_KEY", "key123")
        # DATABASE_URL is missing

        with pytest.raises(SecretNotFound, match="Missing required secrets"):
            SecretManager(
                backend,
                required_secrets=["SECRET_KEY", "DATABASE_URL", "API_KEY"],
            )

    def test_set(self, tmp_path):
        """Test setting secret through manager."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        manager.set("NEW_SECRET", "new-value")
        assert manager.get("NEW_SECRET") == "new-value"

    def test_delete(self, tmp_path):
        """Test deleting secret through manager."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        manager.set("TEMP_SECRET", "value")
        assert manager.exists("TEMP_SECRET") is True

        manager.delete("TEMP_SECRET")
        assert manager.exists("TEMP_SECRET") is False

    def test_list(self, tmp_path):
        """Test listing secrets through manager."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        manager.set("database/password", "pass1")
        manager.set("database/username", "user1")
        manager.set("api/key", "key1")

        all_secrets = manager.list()
        assert "database/password" in all_secrets
        assert "api/key" in all_secrets

        database_secrets = manager.list("database/")
        assert len([s for s in database_secrets if s.startswith("database/")]) == 2

    def test_exists(self, tmp_path):
        """Test checking secret existence."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        assert manager.exists("NONEXISTENT") is False

        manager.set("EXISTS", "value")
        assert manager.exists("EXISTS") is True

    def test_require(self, tmp_path):
        """Test requiring secrets."""
        secrets_file = tmp_path / "secrets.json"
        backend = FileBackend(str(secrets_file))
        manager = SecretManager(backend)

        manager.set("SECRET1", "value1")
        manager.set("SECRET2", "value2")

        # Should succeed
        manager.require("SECRET1", "SECRET2")

        # Should fail
        with pytest.raises(SecretNotFound):
            manager.require("SECRET1", "SECRET2", "MISSING_SECRET")
