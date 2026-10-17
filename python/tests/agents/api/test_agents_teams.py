"""Agent and team management."""

from __future__ import annotations

import pytest

from .conftest import API, create_agent

pytestmark = pytest.mark.api


def make_team(client, admin, name="Platform", **extra):
    response = client.post(
        f"{API}/teams", json={"name": name, "team_type": "functional", **extra}, headers=admin
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestAgents:
    def test_create_get_list_delete(self, client, admin, viewer):
        created = create_agent(client, admin, "eng_1", "engineer")
        assert created["persona"] == "data_engineer"
        assert "build_pipeline" in created["supported_task_types"]

        assert (
            client.get(f"{API}/agents/eng_1", headers=viewer).json()["data"]["agent_id"] == "eng_1"
        )
        listing = client.get(f"{API}/agents", headers=viewer).json()
        assert listing["total"] == 1 and listing["data"][0]["agent_id"] == "eng_1"

        assert client.delete(f"{API}/agents/eng_1", headers=admin).status_code == 204
        assert client.get(f"{API}/agents/eng_1", headers=viewer).status_code == 404

    def test_duplicate_is_409(self, client, admin):
        create_agent(client, admin)
        r = client.post(
            f"{API}/agents", json={"agent_id": "eng_1", "persona": "engineer"}, headers=admin
        )
        assert r.status_code == 409

    @pytest.mark.parametrize(
        "body",
        [
            {"agent_id": "a", "persona": "wizard"},
            {"agent_id": "bad id!", "persona": "engineer"},
            {"agent_id": "a", "persona": "engineer", "skills": {"sql": 1.5}},
            {"agent_id": "a", "persona": "engineer", "max_concurrent_tasks": 0},
            {"agent_id": "a", "persona": "engineer", "team_id": "missing-team"},
        ],
    )
    def test_invalid_create_is_422(self, client, admin, body):
        assert client.post(f"{API}/agents", json=body, headers=admin).status_code == 422

    def test_custom_skills_replace_defaults(self, client, admin):
        created = create_agent(client, admin, skills={"sql": 0.5})
        assert created["skills"] == {"sql": 0.5}

    def test_filters_and_pagination(self, client, admin, viewer):
        for i in range(5):
            create_agent(client, admin, f"eng_{i}", "engineer")
        create_agent(client, admin, "ana_1", "analyst")

        by_persona = client.get(f"{API}/agents?persona=analyst", headers=viewer).json()
        assert [a["agent_id"] for a in by_persona["data"]] == ["ana_1"]

        page = client.get(f"{API}/agents?page=2&page_size=4", headers=viewer).json()
        assert page["total"] == 6 and len(page["data"]) == 2
        assert page["has_prev"] is True and page["has_next"] is False

    def test_page_size_is_capped(self, client, viewer):
        assert client.get(f"{API}/agents?page_size=100000", headers=viewer).status_code == 422

    def test_update_moves_team_and_reindexes_skills(self, client, admin, viewer):
        a = make_team(client, admin, "A")["team_id"]
        b = make_team(client, admin, "B")["team_id"]
        create_agent(client, admin, "eng_1", team_id=a)

        r = client.patch(
            f"{API}/agents/eng_1",
            json={"team_id": b, "skills": {"rust": 0.9}, "max_concurrent_tasks": 7},
            headers=admin,
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert (
            data["team_id"] == b
            and data["skills"] == {"rust": 0.9}
            and data["max_concurrent_tasks"] == 7
        )

        assert client.get(f"{API}/teams/{a}/members", headers=viewer).json()["data"] == []
        assert client.get(f"{API}/teams/{b}/members", headers=viewer).json()["data"] == ["eng_1"]
        found = client.get(
            f"{API}/discovery/by-skill?skill=rust&min_proficiency=0.8", headers=viewer
        ).json()
        assert [x["agent_id"] for x in found["data"]] == ["eng_1"]
        assert (
            client.get(f"{API}/discovery/by-skill?skill=sql", headers=viewer).json()["data"] == []
        )

    def test_update_unknown_team_is_422_and_unknown_agent_404(self, client, admin):
        create_agent(client, admin)
        assert (
            client.patch(f"{API}/agents/eng_1", json={"team_id": "nope"}, headers=admin).status_code
            == 422
        )
        assert client.patch(f"{API}/agents/ghost", json={}, headers=admin).status_code == 404

    def test_delete_removes_team_membership(self, client, admin, viewer):
        team = make_team(client, admin)["team_id"]
        create_agent(client, admin, team_id=team)
        assert client.get(f"{API}/teams/{team}/members", headers=viewer).json()["data"] == ["eng_1"]
        client.delete(f"{API}/agents/eng_1", headers=admin)
        assert client.get(f"{API}/teams/{team}/members", headers=viewer).json()["data"] == []

    def test_deleted_agents_stop_listening_to_the_event_bus(self, client, admin):
        runtime = client.app.state.runtime
        create_agent(client, admin)
        before = sum(len(h) for h in runtime.event_bus._handlers.values())
        client.delete(f"{API}/agents/eng_1", headers=admin)
        after = sum(len(h) for h in runtime.event_bus._handlers.values())
        assert after < before


class TestTeams:
    def test_hierarchy(self, client, admin, viewer):
        root = make_team(client, admin, "Root", team_type="division")
        child = make_team(client, admin, "Child", parent_team_id=root["team_id"])
        assert child["parent_team_id"] == root["team_id"]
        got = client.get(f"{API}/teams/{root['team_id']}", headers=viewer).json()["data"]
        assert got["child_team_ids"] == [child["team_id"]]

    def test_invalid_type_and_parent_are_422(self, client, admin):
        assert (
            client.post(
                f"{API}/teams", json={"name": "x", "team_type": "nope"}, headers=admin
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{API}/teams", json={"name": "x", "parent_team_id": "ghost"}, headers=admin
            ).status_code
            == 422
        )

    def test_leader_must_exist(self, client, admin):
        assert (
            client.post(
                f"{API}/teams", json={"name": "x", "leader_id": "ghost"}, headers=admin
            ).status_code
            == 422
        )
        create_agent(client, admin, "lead_1")
        ok = client.post(f"{API}/teams", json={"name": "x", "leader_id": "lead_1"}, headers=admin)
        assert ok.json()["data"]["leader_id"] == "lead_1"

    def test_rename_and_reparent(self, client, admin):
        a = make_team(client, admin, "A")["team_id"]
        b = make_team(client, admin, "B")["team_id"]
        r = client.patch(
            f"{API}/teams/{b}", json={"name": "B2", "parent_team_id": a}, headers=admin
        )
        assert r.json()["data"]["name"] == "B2" and r.json()["data"]["parent_team_id"] == a
        assert client.get(f"{API}/teams/{a}", headers=admin).json()["data"]["child_team_ids"] == [b]

        detach = client.patch(f"{API}/teams/{b}", json={"parent_team_id": None}, headers=admin)
        assert detach.json()["data"]["parent_team_id"] is None
        assert client.get(f"{API}/teams/{a}", headers=admin).json()["data"]["child_team_ids"] == []

    def test_cannot_create_cycles(self, client, admin):
        a = make_team(client, admin, "A")["team_id"]
        b = make_team(client, admin, "B", parent_team_id=a)["team_id"]
        assert (
            client.patch(f"{API}/teams/{a}", json={"parent_team_id": b}, headers=admin).status_code
            == 422
        )
        assert (
            client.patch(f"{API}/teams/{a}", json={"parent_team_id": a}, headers=admin).status_code
            == 422
        )

    def test_delete_rules(self, client, admin):
        parent = make_team(client, admin, "P")["team_id"]
        child = make_team(client, admin, "C", parent_team_id=parent)["team_id"]
        assert client.delete(f"{API}/teams/{parent}", headers=admin).status_code == 409  # has child

        create_agent(client, admin, team_id=child)
        assert client.delete(f"{API}/teams/{child}", headers=admin).status_code == 409  # has member

        client.delete(f"{API}/agents/eng_1", headers=admin)
        assert client.delete(f"{API}/teams/{child}", headers=admin).status_code == 204
        assert client.delete(f"{API}/teams/{parent}", headers=admin).status_code == 204
        assert client.get(f"{API}/teams/{parent}", headers=admin).status_code == 404
