"""Fixtures: a fake `claude` executable and helpers to read what it recorded."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from unistax.agents.llm.claude_cli import ClaudeCLIConfig, ClaudeCodeBackend

FAKE = Path(__file__).with_name("fake_claude.py")


@pytest.fixture
def fake_cli(tmp_path, monkeypatch) -> Path:
    """An executable that behaves like `claude` and logs its inputs."""
    exe = tmp_path / "claude"
    exe.write_text(f"#!{sys.executable}\n" + FAKE.read_text())
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CLAUDE_FAKE_LOG", str(tmp_path / "calls.jsonl"))
    return exe


@pytest.fixture
def set_mode(monkeypatch):
    def apply(mode: str) -> None:
        monkeypatch.setenv("CLAUDE_FAKE_MODE", mode)

    apply("ok")
    return apply


@pytest.fixture
async def backend(fake_cli, set_mode):
    b = ClaudeCodeBackend(ClaudeCLIConfig(executable=str(fake_cli)))
    yield b
    await b.close()


def recorded_calls(fake_cli: Path) -> list[dict]:
    log = fake_cli.parent / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie still "exists" but is dead for our purposes
    try:
        return "Z" not in Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
