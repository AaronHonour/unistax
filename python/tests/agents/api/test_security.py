"""Settings validation, authentication, authorisation and request hardening."""

from __future__ import annotations

import time
from dataclasses import replace

import jwt as pyjwt
import pytest

from unistax.agents.api import AgentAPISettings, Role, create_access_token, create_agent_api

from .conftest import API, SECRET, headers_for

pytestmark = pytest.mark.api


class TestSettings:
    def test_auth_requires_a_key(self):
        with pytest.raises(ValueError, match="no key is configured"):
            AgentAPISettings().validate()

    def test_short_hmac_secret_rejected(self):
        with pytest.raises(ValueError, match="at least 32"):
            AgentAPISettings(jwt_secret="short").validate()

    def test_auth_can_be_explicitly_disabled(self):
        AgentAPISettings(auth_enabled=False).validate()

    def test_wildcard_cors_rejected(self):
        with pytest.raises(ValueError, match="Wildcard"):
            AgentAPISettings(jwt_secret=SECRET, cors_origins=("*",)).validate()

    def test_app_refuses_to_start_unconfigured(self):
        with pytest.raises(ValueError):
            create_agent_api(AgentAPISettings())

    def test_from_env_parses_types(self):
        s = AgentAPISettings.from_env(
            {
                "UNISTAX_AGENT_API_JWT_SECRET": SECRET,
                "UNISTAX_AGENT_API_RATE_LIMIT": "7",
                "UNISTAX_AGENT_API_AUTH_ENABLED": "false",
                "UNISTAX_AGENT_API_CORS_ORIGINS": "https://a.example, https://b.example",
                "UNISTAX_AGENT_API_SHUTDOWN_TIMEOUT": "2.5",
            }
        )
        assert s.rate_limit == 7
        assert s.auth_enabled is False
        assert s.cors_origins == ("https://a.example", "https://b.example")
        assert s.shutdown_timeout == 2.5


class TestAuthentication:
    def test_missing_token_is_401(self, client):
        response = client.get(f"{API}/agents")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_garbage_token_is_401(self, client):
        assert (
            client.get(f"{API}/agents", headers={"Authorization": "Bearer nope"}).status_code == 401
        )

    def test_wrong_signing_key_is_401(self, client, settings):
        other = replace(settings, jwt_secret="another-secret-" + "y" * 32)
        assert (
            client.get(f"{API}/agents", headers=headers_for(other, Role.ADMIN)).status_code == 401
        )

    def test_expired_token_is_401(self, client, settings):
        token = create_access_token(settings, "u", Role.ADMIN, expires_in=-60)
        assert (
            client.get(f"{API}/agents", headers={"Authorization": f"Bearer {token}"}).status_code
            == 401
        )

    def test_token_without_expiry_is_rejected(self, client):
        token = pyjwt.encode({"sub": "u", "role": "admin"}, SECRET, algorithm="HS256")
        assert (
            client.get(f"{API}/agents", headers={"Authorization": f"Bearer {token}"}).status_code
            == 401
        )

    def test_token_without_known_role_is_403(self, client):
        token = pyjwt.encode(
            {"sub": "u", "role": "wizard", "exp": 4_000_000_000}, SECRET, algorithm="HS256"
        )
        assert (
            client.get(f"{API}/agents", headers={"Authorization": f"Bearer {token}"}).status_code
            == 403
        )

    def test_unsigned_alg_none_token_is_rejected(self, client):
        token = pyjwt.encode(
            {"sub": "u", "role": "admin", "exp": 4_000_000_000}, "", algorithm="none"
        )
        assert (
            client.get(f"{API}/agents", headers={"Authorization": f"Bearer {token}"}).status_code
            == 401
        )

    def test_roles_claim_list_is_supported(self, client):
        token = pyjwt.encode(
            {"sub": "u", "roles": ["viewer"], "exp": 4_000_000_000}, SECRET, algorithm="HS256"
        )
        assert (
            client.get(f"{API}/agents", headers={"Authorization": f"Bearer {token}"}).status_code
            == 200
        )

    def test_auth_disabled_allows_anonymous(self, make_client):
        client = make_client(auth_enabled=False, jwt_secret=None)
        assert client.get(f"{API}/agents").status_code == 200


class TestAuthorisation:
    def test_viewer_is_read_only(self, client, viewer):
        assert client.get(f"{API}/agents", headers=viewer).status_code == 200
        assert (
            client.post(
                f"{API}/agents", json={"agent_id": "a", "persona": "engineer"}, headers=viewer
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"{API}/tasks", json={"task_type": "quality_check"}, headers=viewer
            ).status_code
            == 403
        )

    def test_operator_cannot_manage_agents_or_teams(self, client, operator):
        assert (
            client.post(
                f"{API}/agents", json={"agent_id": "a", "persona": "engineer"}, headers=operator
            ).status_code
            == 403
        )
        assert client.post(f"{API}/teams", json={"name": "t"}, headers=operator).status_code == 403

    def test_operator_can_write_knowledge(self, client, operator):
        r = client.post(
            f"{API}/knowledge/nodes",
            json={"node_id": "ds", "node_type": "dataset"},
            headers=operator,
        )
        assert r.status_code == 201

    def test_health_probes_need_no_auth(self, client):
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").json() == {
            "status": "ready",
            "database": True,
            "datasource": "not_configured",
        }


class TestRequestHardening:
    def test_request_id_is_generated_and_echoed(self, client, viewer):
        generated = client.get(f"{API}/agents", headers=viewer).headers["x-request-id"]
        assert generated
        echoed = client.get(f"{API}/agents", headers={**viewer, "X-Request-ID": "trace-123"})
        assert echoed.headers["x-request-id"] == "trace-123"

    def test_unsafe_request_id_is_replaced(self, client, viewer):
        response = client.get(
            f"{API}/agents", headers={**viewer, "X-Request-ID": "bad id\twith spaces"}
        )
        assert response.headers["x-request-id"] != "bad id\twith spaces"

    def test_security_headers(self, client, viewer):
        headers = client.get(f"{API}/agents", headers=viewer).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["cache-control"] == "no-store"

    def test_oversized_body_is_413(self, make_client, admin):
        client = make_client(max_request_bytes=200)
        response = client.post(
            f"{API}/agents",
            json={"agent_id": "a", "persona": "engineer", "pad": "x" * 500},
            headers=admin,
        )
        assert response.status_code == 413

    def test_rate_limit_returns_429_with_headers(self, make_client, viewer):
        client = make_client(rate_limit=3, rate_limit_window=60)
        codes = [client.get(f"{API}/agents", headers=viewer) for _ in range(5)]
        assert [r.status_code for r in codes] == [200, 200, 200, 429, 429]
        assert codes[0].headers["x-ratelimit-limit"] == "3"
        assert codes[0].headers["x-ratelimit-remaining"] == "2"
        assert int(codes[3].headers["retry-after"]) > 0

    def test_rate_limit_is_per_caller(self, make_client, settings):
        client = make_client(rate_limit=2)
        a = headers_for(settings, Role.VIEWER, "alice")
        b = headers_for(settings, Role.VIEWER, "bob")
        assert [client.get(f"{API}/agents", headers=a).status_code for _ in range(3)] == [
            200,
            200,
            429,
        ]
        assert client.get(f"{API}/agents", headers=b).status_code == 200

    def test_expensive_endpoints_have_a_tighter_limit(self, make_client, admin):
        client = make_client(expensive_rate_limit=1)
        client.post(f"{API}/agents", json={"agent_id": "e1", "persona": "engineer"}, headers=admin)
        first = client.post(f"{API}/tasks", json={"task_type": "quality_check"}, headers=admin)
        second = client.post(f"{API}/tasks", json={"task_type": "quality_check"}, headers=admin)
        assert (first.status_code, second.status_code) == (202, 429)

    def test_docs_can_be_disabled(self, make_client):
        client = make_client(docs_enabled=False)
        assert client.get(f"{API}/openapi.json").status_code == 404

    def test_cors_only_for_listed_origins(self, make_client):
        client = make_client(cors_origins=("https://app.example",))
        ok = client.options(
            f"{API}/agents",
            headers={"Origin": "https://app.example", "Access-Control-Request-Method": "GET"},
        )
        bad = client.options(
            f"{API}/agents",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert ok.headers.get("access-control-allow-origin") == "https://app.example"
        assert "access-control-allow-origin" not in bad.headers


def test_rate_limiter_state_is_pruned_when_callers_go_idle(make_client, settings):
    from unistax.agents.api import limits as limits_module

    client = make_client(rate_limit=5, rate_limit_window=1)
    runtime = client.app.state.runtime
    for i in range(30):
        client.get(f"{API}/agents", headers=headers_for(settings, Role.VIEWER, f"user-{i}"))
    assert runtime.limits.general.tracked_keys() == 30

    time.sleep(1.2)  # every window has now expired
    runtime.limits._next_prune = 0  # skip the once-a-minute throttle
    client.get(f"{API}/agents", headers=headers_for(settings, Role.VIEWER, "someone-new"))

    assert runtime.limits.general.tracked_keys() == 1
    assert limits_module.PRUNE_INTERVAL_SECONDS > 0
