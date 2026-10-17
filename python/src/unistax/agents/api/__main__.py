"""Run the agent API: ``python -m unistax.agents.api``.

The service keeps agents, scheduling and the event stream in process memory, so it
must run as a single process (one worker, one replica). Persistent state lives in the
database; see ``unistax.agents.api.settings`` for configuration.
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    """Parse arguments and serve the API with uvicorn."""
    parser = argparse.ArgumentParser(description="Run the agent framework API")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))  # noqa: S104
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "info"))
    args = parser.parse_args()

    uvicorn.run(
        "unistax.agents.api.app:create_agent_api",
        factory=True,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()
