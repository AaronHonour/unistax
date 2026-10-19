"""The Claude Code CLI backend, tested against a fake `claude` executable."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from unistax.agents.llm import (
    BackendUnavailable,
    LLMAuthError,
    LLMError,
    LLMOutputError,
    LLMOverloaded,
    LLMRequest,
    LLMTimeout,
    UsageLimitReached,
)
from unistax.agents.llm import claude_cli
from unistax.agents.llm.claude_cli import ClaudeCLIConfig, ClaudeCodeBackend, scrubbed_env

from .conftest import alive, recorded_calls

pytestmark = pytest.mark.agents


class TestCommandLine:
    def test_safety_flags_are_always_present(self, backend):
        argv = backend.build_command(LLMRequest(prompt="x"))
        for flag in ("-p", "--no-session-persistence", "--restricted", "--safe-mode"):
            assert flag in argv
        assert argv[argv.index("--output-format") + 1] == "json"
        assert argv[argv.index("--permission-prompts") + 1] == "none"
        assert argv[argv.index("--tools") + 1] == ""  # no tools unless requested

    def test_tools_are_passed_only_when_requested(self, backend):
        argv = backend.build_command(LLMRequest(prompt="x", tools=("Read", "Grep")))
        assert argv[argv.index("--tools") + 1] == "Read,Grep"

    def test_the_prompt_is_never_on_the_command_line(self, backend):
        secret = "customer-data-123 do-not-leak"
        argv = backend.build_command(LLMRequest(prompt=secret, system_prompt="be brief"))
        assert not any(secret in part for part in argv)
        assert argv[argv.index("--system-prompt") + 1] == "be brief"

    def test_optional_flags(self, fake_cli):
        b = ClaudeCodeBackend(
            ClaudeCLIConfig(executable=str(fake_cli), default_model="haiku", default_effort="low")
        )
        argv = b.build_command(LLMRequest(prompt="x", json_schema={"type": "object"}))
        assert (
            argv[argv.index("--model") + 1] == "haiku" and argv[argv.index("--effort") + 1] == "low"
        )
        assert json.loads(argv[argv.index("--json-schema") + 1]) == {"type": "object"}
        override = b.build_command(LLMRequest(prompt="x", model="opus", effort="high"))
        assert override[override.index("--model") + 1] == "opus"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"model": "--dangerously-skip-permissions"},
            {"model": "-x"},
            {"model": "a b"},
            {"model": "x" * 100},
            {"effort": "extreme"},
            {"tools": ("Bash(rm -rf /)",)},
            {"tools": ("--allow-dangerously-skip-permissions",)},
            {"tools": ("",)},
            {"system_prompt": "x" * 25_000},
            {"json_schema": {"x": "y" * 20_000}},
        ],
    )
    def test_values_that_could_alter_the_command_are_rejected(self, backend, kwargs):
        with pytest.raises(LLMError):
            backend.build_command(LLMRequest(prompt="x", **kwargs))


class TestRunning:
    async def test_a_successful_call(self, backend, fake_cli):
        response = await backend.run(LLMRequest(prompt="hello there", system_prompt="role"))

        assert response.text == "echo:hello there"
        assert response.usage.as_dict() == {
            "calls": 1, "input_tokens": 11, "output_tokens": 7,
            "cache_read_tokens": 100, "cache_creation_tokens": 50,
        }  # fmt: skip
        assert response.nominal_cost_usd == pytest.approx(0.0123)
        assert response.model == "claude-main"  # the model that did the work
        assert response.session_id == "fake-session" and response.num_turns == 1

    async def test_the_prompt_arrives_on_stdin(self, backend, fake_cli):
        await backend.run(LLMRequest(prompt="line one\nline two with ünïcode"))
        (call,) = recorded_calls(fake_cli)
        assert call["stdin"] == "line one\nline two with ünïcode"
        assert not any("line one" in a for a in call["argv"])

    async def test_structured_output(self, backend):
        response = await backend.run(LLMRequest(prompt="data", json_schema={"type": "object"}))
        assert response.structured == {"echo": True, "stdin_chars": 4}

    async def test_the_subprocess_environment_is_scrubbed(self, backend, fake_cli, monkeypatch):
        monkeypatch.setenv("UNISTAX_AGENT_API_JWT_SECRET", "must-not-reach-the-model")
        monkeypatch.setenv("UNISTAX_AGENT_API_DATASOURCE_URL", "postgresql://u:pw@h/db")
        monkeypatch.setenv("DATABASE_URL", "postgresql://leak")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "belongs-to-the-operator")

        await backend.run(LLMRequest(prompt="x"))
        (call,) = recorded_calls(fake_cli)

        assert not [k for k in call["env"] if k.startswith("UNISTAX_")]
        assert "DATABASE_URL" not in call["env"] and "AWS_SECRET_ACCESS_KEY" not in call["env"]
        assert "PATH" in call["env"] and "HOME" in call["env"]
        assert "ANTHROPIC_API_KEY" in call["env"]  # the operator's own credentials are inherited

    async def test_calls_run_in_a_private_empty_directory(self, backend, fake_cli):
        await backend.run(LLMRequest(prompt="x"))
        (call,) = recorded_calls(fake_cli)
        import os

        assert call["cwd"] != os.getcwd() and "unistax-llm-" in call["cwd"]
        assert os.listdir(call["cwd"]) == []
        await backend.close()
        assert not os.path.exists(call["cwd"])  # cleaned up

    async def test_stray_lines_around_the_result_are_tolerated(self, backend, set_mode):
        set_mode("noisy")
        assert (await backend.run(LLMRequest(prompt="hi"))).text == "echo:hi"

    async def test_no_structured_output_leaves_it_empty(self, backend, set_mode):
        set_mode("no_structured")
        response = await backend.run(LLMRequest(prompt="x"))
        assert response.structured is None and response.text == "plain text, no structure"


class TestFailureClassification:
    @pytest.mark.parametrize(
        ("mode", "error"),
        [
            ("usage_status", UsageLimitReached),
            ("usage_text", UsageLimitReached),
            ("auth_status", LLMAuthError),
            ("auth_text", LLMAuthError),
            ("overloaded", LLMOverloaded),
            ("max_turns", LLMOutputError),
            ("garbage", LLMOutputError),
            ("empty_fail", LLMOutputError),
        ],
    )
    async def test_errors_are_classified(self, backend, set_mode, mode, error):
        set_mode(mode)
        with pytest.raises(error):
            await backend.run(LLMRequest(prompt="x"))

    async def test_error_messages_never_echo_model_or_stderr_text(self, backend, set_mode):
        set_mode("max_turns")
        with pytest.raises(LLMOutputError) as exc:
            await backend.run(LLMRequest(prompt="x"))
        assert "secret model text" not in str(exc.value)

    async def test_only_overload_is_marked_retryable(self, backend, set_mode):
        for mode, retryable in [
            ("overloaded", True),
            ("usage_status", False),
            ("auth_status", False),
        ]:
            set_mode(mode)
            with pytest.raises(LLMError) as exc:
                await backend.run(LLMRequest(prompt="x"))
            assert exc.value.retryable is retryable

    async def test_oversized_output_is_rejected(self, backend, set_mode, monkeypatch):
        set_mode("big")
        monkeypatch.setattr(claude_cli, "MAX_OUTPUT_BYTES", 500)
        with pytest.raises(LLMOutputError, match="too much output"):
            await backend.run(LLMRequest(prompt="x"))

    async def test_oversized_prompts_are_rejected_before_starting_anything(
        self, backend, fake_cli, monkeypatch
    ):
        monkeypatch.setattr(claude_cli, "MAX_PROMPT_BYTES", 100)
        with pytest.raises(LLMError, match="too large"):
            await backend.run(LLMRequest(prompt="x" * 200))
        assert recorded_calls(fake_cli) == []

    async def test_a_missing_executable_is_reported_clearly(self, tmp_path):
        b = ClaudeCodeBackend(ClaudeCLIConfig(executable=str(tmp_path / "nope")))
        with pytest.raises(BackendUnavailable, match="not found"):
            await b.run(LLMRequest(prompt="x"))
        with pytest.raises(BackendUnavailable):
            await b.check()
        await b.close()


class TestProcessControl:
    async def test_a_timeout_kills_the_whole_process_tree(self, backend, fake_cli, set_mode):
        set_mode("hang")
        started = time.monotonic()
        with pytest.raises(LLMTimeout, match="stopped"):
            await backend.run(LLMRequest(prompt="x", timeout=1.0))
        assert time.monotonic() - started < 6

        (call,) = recorded_calls(fake_cli)
        await asyncio.sleep(0.3)
        assert not alive(call["pid"]), "the CLI process survived the timeout"
        assert not alive(call["child_pid"]), "a child of the CLI survived the timeout"

    async def test_cancellation_kills_the_process_tree(self, backend, fake_cli, set_mode):
        set_mode("hang")
        task = asyncio.create_task(backend.run(LLMRequest(prompt="x", timeout=60)))
        for _ in range(100):
            if recorded_calls(fake_cli):
                break
            await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        (call,) = recorded_calls(fake_cli)
        await asyncio.sleep(0.3)
        assert not alive(call["pid"]) and not alive(call["child_pid"])

    async def test_the_liveness_helper_can_tell_the_difference(self):
        import os

        assert alive(os.getpid()) and not alive(2**22 + 12345)


class TestCheck:
    async def test_reports_the_version(self, backend):
        report = await backend.check()
        assert "9.9.9" in report.version

    async def test_old_clis_without_the_safety_flags_are_refused(self, backend, set_mode):
        set_mode("oldhelp")
        with pytest.raises(BackendUnavailable, match="--restricted"):
            await backend.check()


class TestEnvironmentScrubbing:
    def test_whitelist(self):
        env = scrubbed_env(
            {
                "PATH": "/bin", "HOME": "/h", "ANTHROPIC_API_KEY": "k", "CLAUDE_CODE_OAUTH_TOKEN": "t",
                "HTTPS_PROXY": "p", "UNISTAX_AGENT_API_JWT_SECRET": "s", "DATABASE_URL": "d",
                "GITHUB_TOKEN": "g", "AWS_ACCESS_KEY_ID": "a",
            }
        )  # fmt: skip
        assert set(env) == {
            "PATH",
            "HOME",
            "ANTHROPIC_API_KEY",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "HTTPS_PROXY",
        }
