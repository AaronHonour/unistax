"""Demo script showing agent collaboration between Data Engineer and Data Analyst.

This example demonstrates:
- Creating an agent registry with shared infrastructure
- Registering multiple agent personas
- Creating hierarchical teams
- Assigning tasks to agents
- Inter-agent communication via EventBus
"""

import asyncio
import logging
import sys

from unistax.agents import (
    AgentRegistry,
    DataAnalystAgent,
    DataEngineerAgent,
    Skill,
    Task,
    TeamType,
)

# Configure basic logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(name)s - %(message)s',
    stream=sys.stdout
)

# Initialize unistax logging context (required for unistax.logging to work)
from unistax.logging.context import log_context
log_context.set({})

logger = logging.getLogger(__name__)


async def main():
    """Run agent collaboration demo."""
    logger.info("=" * 60)
    logger.info("Agent Collaboration Demo")
    logger.info("=" * 60)

    # 1. Create registry with shared infrastructure
    logger.info("\n1. Creating agent registry...")
    registry = AgentRegistry()
    logger.info(f"✓ Registry created: {registry}")

    # 2. Create Data Platform team
    logger.info("\n2. Creating Data Platform team...")
    data_team = registry.create_team(
        name="Data Platform",
        team_type=TeamType.DIVISION,
    )
    logger.info(f"✓ Team created: {data_team.name} (id={data_team.id})")

    # 3. Create Data Engineer agent
    logger.info("\n3. Creating Data Engineer agent...")
    engineer = DataEngineerAgent(
        agent_id="eng_001",
        event_bus=registry.event_bus,
        metrics_manager=registry.metrics_manager,
        team_id=data_team.id,
    )
    registry.register(engineer)
    logger.info(f"✓ Data Engineer registered: {engineer.agent_id}")
    logger.info(f"  Skills: {', '.join(engineer.skills.keys())}")

    # 4. Create Data Analyst agent
    logger.info("\n4. Creating Data Analyst agent...")
    analyst = DataAnalystAgent(
        agent_id="analyst_001",
        event_bus=registry.event_bus,
        metrics_manager=registry.metrics_manager,
        team_id=data_team.id,
    )
    registry.register(analyst)
    logger.info(f"✓ Data Analyst registered: {analyst.agent_id}")
    logger.info(f"  Skills: {', '.join(analyst.skills.keys())}")

    # 5. Display registry stats
    logger.info("\n5. Registry statistics:")
    stats = registry.get_registry_stats()
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")

    # 6. Create and assign tasks to engineer
    logger.info("\n6. Assigning tasks to Data Engineer...")

    pipeline_task = Task(
        type="build_pipeline",
        description="Build customer analytics pipeline",
        priority=8,
        required_skills={"sql": 0.7, "etl": 0.8},
        context={
            "name": "customer_analytics_pipeline",
            "source": {"type": "postgres", "table": "raw_customers"},
            "target": {"type": "snowflake", "table": "dim_customers"},
        },
    )

    # Check if engineer can do the task
    can_do, confidence = engineer.can_do(pipeline_task)
    logger.info(f"  Engineer can do task: {can_do} (confidence: {confidence:.2%})")

    if can_do:
        await engineer.accept_task(pipeline_task)
        logger.info(f"  ✓ Task assigned: {pipeline_task.id}")

        # Execute the task
        result = await engineer.execute_task(pipeline_task)
        logger.info(f"  ✓ Task completed: {result['status']}")
        logger.info(f"    Message: {result['message']}")

    # 7. Create and assign tasks to analyst
    logger.info("\n7. Assigning tasks to Data Analyst...")

    analysis_task = Task(
        type="analyze_data",
        description="Analyze customer behavior patterns",
        priority=7,
        required_skills={"sql": 0.7, "data_analysis": 0.8},
        context={
            "dataset": "customer_analytics",
            "analysis_type": "behavioral",
        },
    )

    can_do, confidence = analyst.can_do(analysis_task)
    logger.info(f"  Analyst can do task: {can_do} (confidence: {confidence:.2%})")

    if can_do:
        await analyst.accept_task(analysis_task)
        logger.info(f"  ✓ Task assigned: {analysis_task.id}")

        # Execute the task
        result = await analyst.execute_task(analysis_task)
        logger.info(f"  ✓ Task completed: {result['status']}")
        logger.info(f"    Key findings:")
        for finding in result['key_findings']:
            logger.info(f"      - {finding}")

    # 8. Test agent discovery
    logger.info("\n8. Testing agent discovery...")

    # Find all agents with SQL skill
    sql_agents = registry.find_by_skill("sql", min_proficiency=0.8)
    logger.info(f"  Agents with SQL (>= 0.8): {[a.agent_id for a in sql_agents]}")

    # Find all data engineers
    engineers = registry.find_by_persona("data_engineer")
    logger.info(f"  Data Engineers: {[a.agent_id for a in engineers]}")

    # Find all analysts
    analysts = registry.find_by_persona("data_analyst")
    logger.info(f"  Data Analysts: {[a.agent_id for a in analysts]}")

    # Find agents in team
    team_agents = registry.find_by_team(data_team.id)
    logger.info(f"  Agents in {data_team.name}: {[a.agent_id for a in team_agents]}")

    # 9. Display agent metrics
    logger.info("\n9. Agent performance metrics:")

    engineer_stats = engineer.get_engineer_stats()
    logger.info(f"\n  Data Engineer ({engineer.agent_id}):")
    logger.info(f"    State: {engineer_stats['state']}")
    logger.info(f"    Tasks completed: {engineer_stats['tasks_completed']}")
    logger.info(f"    Tasks failed: {engineer_stats['tasks_failed']}")
    logger.info(f"    Success rate: {engineer_stats['success_rate']:.1%}")
    logger.info(f"    Pipelines maintained: {engineer_stats['pipelines_maintained']}")

    analyst_stats = analyst.get_analyst_stats()
    logger.info(f"\n  Data Analyst ({analyst.agent_id}):")
    logger.info(f"    State: {analyst_stats['state']}")
    logger.info(f"    Tasks completed: {analyst_stats['tasks_completed']}")
    logger.info(f"    Tasks failed: {analyst_stats['tasks_failed']}")
    logger.info(f"    Success rate: {analyst_stats['success_rate']:.1%}")
    logger.info(f"    Queries executed: {analyst_stats['queries_executed']}")

    # 10. Test collaboration scenario
    logger.info("\n10. Testing collaboration scenario...")
    logger.info("  Scenario: Analyst needs data quality checked by Engineer")

    # Analyst sends message to engineer
    await analyst.send_message(
        to_agent=engineer.agent_id,
        msg_type="request",
        content={
            "action": "quality_check",
            "table": "customer_analytics",
            "urgency": "high",
        },
        requires_response=True,
    )
    logger.info(f"  ✓ Analyst sent quality check request to Engineer")

    # Check engineer's inbox
    logger.info(f"  Engineer inbox size: {engineer.inbox.qsize()}")

    logger.info("\n" + "=" * 60)
    logger.info("Demo completed successfully!")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
