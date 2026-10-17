"""Data Scientist and Data Steward personas (task handlers, state, decisions)."""

from __future__ import annotations

import pytest

from unistax.agents import (
    AgentState,
    DataScientistAgent,
    DataStewardAgent,
    Task,
    TaskStatus,
)

pytestmark = pytest.mark.agents


def run(agent, task_type, **context):
    task = Task(type=task_type, context=context)
    return agent.execute_task(task)


@pytest.fixture
def scientist() -> DataScientistAgent:
    return DataScientistAgent("ds_1")


@pytest.fixture
def steward() -> DataStewardAgent:
    return DataStewardAgent("st_1")


ALL_TASKS = [
    *[(DataScientistAgent, t) for t in sorted(DataScientistAgent.TASK_TYPES)],
    *[(DataStewardAgent, t) for t in sorted(DataStewardAgent.TASK_TYPES)],
]


class TestSharedBehaviour:
    @pytest.mark.parametrize(("cls", "task_type"), ALL_TASKS)
    async def test_every_task_type_returns_a_successful_result(self, cls, task_type):
        result = await run(cls("a"), task_type)
        assert result["status"] in {"success", "compliant"}

    @pytest.mark.parametrize("cls", [DataScientistAgent, DataStewardAgent])
    async def test_unknown_task_type_is_rejected(self, cls):
        with pytest.raises(ValueError, match="Unknown task type"):
            await run(cls("a"), "make_coffee")

    @pytest.mark.parametrize("cls", [DataScientistAgent, DataStewardAgent])
    async def test_declared_task_types_match_the_dispatcher(self, cls):
        """Every declared type is handled; nothing undeclared is silently accepted."""
        for task_type in cls.TASK_TYPES:
            await run(cls("a"), task_type)  # would raise if the dispatcher lacked it

    @pytest.mark.parametrize("cls", [DataScientistAgent, DataStewardAgent])
    def test_skills_are_valid_proficiencies(self, cls):
        agent = cls("a")
        assert agent.skills
        assert all(0.0 < s.proficiency <= 1.0 for s in agent.skills.values())

    @pytest.mark.parametrize("cls", [DataScientistAgent, DataStewardAgent])
    def test_custom_skills_replace_defaults(self, cls):
        from unistax.agents import Skill

        agent = cls("a", skills=[Skill("only_this", 0.5, "x")])
        assert list(agent.skills) == ["only_this"]

    @pytest.mark.parametrize(
        ("cls", "persona"),
        [(DataScientistAgent, "data_scientist"), (DataStewardAgent, "data_steward")],
    )
    def test_persona_names(self, cls, persona):
        assert cls("a").persona == persona

    @pytest.mark.parametrize("cls", [DataScientistAgent, DataStewardAgent])
    async def test_run_task_completes_through_the_full_lifecycle(self, cls):
        agent = cls("a")
        task_type = sorted(cls.TASK_TYPES)[0]
        task = Task(type=task_type, context={})
        await agent.accept_task(task)
        await agent.run_task(task)

        assert task.status == TaskStatus.COMPLETED and task.result
        assert agent.state == AgentState.IDLE and agent.metrics["tasks_completed"] == 1

    @pytest.mark.parametrize("cls", [DataScientistAgent, DataStewardAgent])
    async def test_decide_executes_highest_priority_task_first(self, cls):
        agent = cls("a")
        task_type = sorted(cls.TASK_TYPES)[0]
        low = Task(type=task_type, priority=2)
        high = Task(type=task_type, priority=9)
        await agent.accept_task(low)
        await agent.accept_task(high)

        assert await agent.decide() == f"execute_task:{high.id}"

    @pytest.mark.parametrize("cls", [DataScientistAgent, DataStewardAgent])
    async def test_decide_is_idle_when_there_is_nothing_to_do(self, cls):
        assert await cls("a").decide() is None

    @pytest.mark.parametrize("cls", [DataScientistAgent, DataStewardAgent])
    async def test_proactive_monitor_runs_without_error(self, cls):
        await cls("a")._proactive_monitor()


class TestDataScientist:
    async def test_train_model_tracks_the_model(self, scientist):
        result = await run(
            scientist, "train_model", name="churn", type="regression", features=["a", "b"]
        )

        assert result["model_name"] == "churn" and result["model_type"] == "regression"
        assert result["features_used"] == 2 and result["model_path"] == "/models/churn/v1"
        assert set(result["metrics"]) >= {"accuracy"}
        assert scientist.get_scientist_stats()["models_trained"] == 1

    async def test_training_the_same_model_twice_counts_once(self, scientist):
        await run(scientist, "train_model", name="churn")
        await run(scientist, "train_model", name="churn")
        assert scientist.get_scientist_stats()["models_trained"] == 1

    async def test_counters(self, scientist):
        await run(scientist, "engineer_features", dataset="d")
        await run(scientist, "engineer_features", dataset="d")
        await run(scientist, "run_experiment", name="e")
        await run(scientist, "deploy_model", model="m")

        stats = scientist.get_scientist_stats()
        assert (
            stats["features_engineered"],
            stats["experiments_run"],
            stats["models_deployed"],
        ) == (2, 1, 1)

    async def test_context_is_reflected_in_results(self, scientist):
        assert (await run(scientist, "evaluate_model", model="m1", test_dataset="holdout"))[
            "test_dataset"
        ] == "holdout"
        assert (await run(scientist, "deploy_model", model="m1", environment="staging"))[
            "environment"
        ] == "staging"
        assert (await run(scientist, "run_experiment", name="exp", variants=["X", "Y"]))[
            "experiment_name"
        ] == "exp"
        assert (await run(scientist, "tune_hyperparameters", model="m1", method="bayesian"))[
            "method"
        ] == "bayesian"
        assert (await run(scientist, "analyze_model", model="m1", type="shap"))[
            "analysis_type"
        ] == "shap"
        assert (await run(scientist, "engineer_features", dataset="orders"))["dataset"] == "orders"

    async def test_add_model_enables_proactive_monitoring(self, scientist):
        assert await scientist.decide() is None
        scientist.add_model("fraud")
        assert await scientist.decide() == "proactive_monitor"

    async def test_busy_scientist_does_not_monitor(self, scientist):
        scientist.add_model("fraud")
        scientist.state = AgentState.WORKING
        assert await scientist.decide() is None

    async def test_stats_extend_the_base_metrics(self, scientist):
        stats = scientist.get_scientist_stats()
        assert {"success_rate", "uptime_seconds"} <= set(stats)
        assert {
            "models_trained",
            "experiments_run",
            "models_deployed",
            "features_engineered",
        } <= set(stats)


class TestDataSteward:
    async def test_catalog_dataset_registers_it(self, steward):
        result = await run(steward, "catalog_dataset", name="customers", source="postgres")

        assert result["dataset_name"] == "customers" and result["source"] == "postgres"
        assert result["catalog_url"].endswith("customers")
        assert steward.get_steward_stats()["datasets_cataloged"] == 1

    async def test_cataloging_twice_counts_once(self, steward):
        await run(steward, "catalog_dataset", name="customers")
        await run(steward, "catalog_dataset", name="customers")
        assert steward.get_steward_stats()["datasets_cataloged"] == 1

    async def test_counters(self, steward):
        await run(steward, "track_lineage", dataset="d")
        await run(steward, "check_compliance", dataset="d")
        await run(steward, "check_compliance", dataset="d")
        await run(steward, "enforce_policy", policy="p")

        stats = steward.get_steward_stats()
        assert (
            stats["lineage_documented"],
            stats["compliance_checks"],
            stats["policies_enforced"],
        ) == (1, 2, 1)

    async def test_compliance_defaults_to_gdpr_and_honours_requests(self, steward):
        assert (await run(steward, "check_compliance", dataset="d"))["regulations"] == ["GDPR"]
        custom = await run(steward, "check_compliance", dataset="d", regulations=["HIPAA", "SOX"])
        assert custom["regulations"] == ["HIPAA", "SOX"]
        assert custom["status"] == "compliant" and custom["risk_score"] >= 0

    async def test_context_is_reflected_in_results(self, steward):
        assert (await run(steward, "track_lineage", dataset="orders", sources=["raw"]))[
            "dataset"
        ] == "orders"
        assert (await run(steward, "enforce_policy", policy="pii", scope="finance"))[
            "scope"
        ] == "finance"
        assert (await run(steward, "audit_access", dataset="orders", period="7d"))["period"] == "7d"
        assert (await run(steward, "classify_data", dataset="orders"))["dataset"] == "orders"
        assert (await run(steward, "document_schema", table="orders"))["table"] == "orders"

    async def test_add_dataset_enables_proactive_monitoring(self, steward):
        assert await steward.decide() is None
        steward.add_dataset("customers")
        assert await steward.decide() == "proactive_monitor"

    async def test_stats_extend_the_base_metrics(self, steward):
        stats = steward.get_steward_stats()
        assert {"success_rate", "uptime_seconds"} <= set(stats)
        assert {
            "datasets_cataloged",
            "policies_enforced",
            "compliance_checks",
            "lineage_documented",
        } <= set(stats)
