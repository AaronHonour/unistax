"""Agent Personas Module.

Provides pre-configured agent personas for common data platform roles:
- DataEngineerAgent: ETL pipelines, data quality, schema management
- DataAnalystAgent: Ad-hoc analysis, reporting, visualization
- DataScientistAgent: ML models, experimentation, feature engineering
- DataStewardAgent: Governance, compliance, metadata management
"""

from unistax.agents.personas.data_analyst import DataAnalystAgent
from unistax.agents.personas.data_engineer import DataEngineerAgent
from unistax.agents.personas.data_scientist import DataScientistAgent
from unistax.agents.personas.data_steward import DataStewardAgent

__all__ = [
    "DataEngineerAgent",
    "DataAnalystAgent",
    "DataScientistAgent",
    "DataStewardAgent",
]
