"""Backend that runs the unmodified Claude Code CLI in headless mode (``claude -p``).

It authenticates however the CLI itself does: the signed-in Claude subscription, or an
``ANTHROPIC_API_KEY`` / ``CLAUDE_CODE_OAUTH_TOKEN`` in the environment. **This code never
reads, stores, logs or forwards credentials**; it only starts the binary, which finds its
own. Anthropic permits subscription sign-in for "ordinary, individual usage" of the
unmodified binary; it does not permit routing other people's requests through your plan.
Run this as a single-operator tool, not as a service for other users.

Every call is locked down by default:

* ``--restricted --safe-mode``: no code-running tools, no web fetch, no MCP servers, hooks,
  plugins or project settings, file access confined to a private empty directory
* ``--tools ""``: no built-in tools at all unless the request names some
* ``--permission-prompts none``: anything that would ask for permission is denied
* ``--no-session-persistence``: nothing is written to the transcript history
* the prompt goes through stdin (never the command line, so it is not visible in ``ps``)
* the subprocess gets a minimal environment: this service's own secrets never reach it
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from unistax.agents.llm.types import (
    BackendUnavailable,
    LLMAuthError,
    LLMError,
    LLMOutputError,
    LLMOverloaded,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
    Usage,
    UsageLimitReached,
)

logger = logging.getLogger(__name__)

REQUIRED_FLAGS = (
    "--output-format",
    "--no-session-persistence",
    "--restricted",
    "--safe-mode",
    "--permission-prompts",
    "--json-schema",
    "--tools",
    "--system-prompt",
)
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_SYSTEM_PROMPT_CHARS = 20_000
MAX_SCHEMA_CHARS = 16_000
MAX_PROMPT_BYTES = 4 * 1024 * 1024

_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-\[\]]{0,63}$")
_TOOL = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

# Only what the CLI needs to find its login, reach the network and behave sanely.
_ENV_NAMES = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR",
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    }
)  # fmt: skip
_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_")

_USAGE_TEXT = re.compile(
    r"usage limit|rate.?limit|limit reached|too many requests|quota|out of (extra )?usage|"
    r"credit balance|exceeded your",
    re.I,
)
_AUTH_TEXT = re.compile(
    r"not logged in|please (run )?/?login|invalid (api key|credentials|x-api-key)|"
    r"unauthori[sz]ed|oauth token|authentication (failed|error|required)|token (has )?expired",
    re.I,
)
_OVERLOAD_TEXT = re.compile(r"overloaded|temporarily unavailable|service unavailable", re.I)


def scrubbed_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment the CLI subprocess gets (a whitelist, not a blacklist)."""
    env = os.environ if source is None else source
    return {k: v for k, v in env.items() if k in _ENV_NAMES or k.startswith(_ENV_PREFIXES)}


@dataclass(frozen=True)
class ClaudeCLIConfig:
    """How to run the CLI."""

    executable: str = "claude"
    default_model: str | None = None
    default_effort: str | None = None
    default_timeout: float = 300.0
    workdir: str | None = None


@dataclass(frozen=True)
class BackendReport:
    """Result of :meth:`ClaudeCodeBackend.check`."""

    executable: str
    version: str


class ClaudeCodeBackend:
    """Runs one ``claude -p`` process per request."""

    name = "claude_cli"

    def __init__(self, config: ClaudeCLIConfig | None = None) -> None:
        """Create the backend (nothing is started until the first call)."""
        self.config = config or ClaudeCLIConfig()
        self._workdir: str | None = self.config.workdir
        self._owns_workdir = False

    # -- setup ---------------------------------------------------------------
    async def check(self) -> BackendReport:
        """Confirm the CLI exists and supports the safety flags this backend relies on.

        Raises:
            BackendUnavailable: Missing, not executable, or too old.
        """
        exe = shutil.which(self.config.executable)
        if exe is None:
            raise BackendUnavailable(
                f"the Claude Code CLI '{self.config.executable}' was not found on PATH"
            )
        version = (await self._capture([exe, "--version"])).strip()
        help_text = await self._capture([exe, "--help"])
        missing = [flag for flag in REQUIRED_FLAGS if flag not in help_text]
        if missing:
            raise BackendUnavailable(
                f"this Claude Code CLI ({version}) lacks required options {missing}; "
                "update it with `claude update`"
            )
        return BackendReport(exe, version)

    async def _capture(self, argv: list[str]) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=scrubbed_env(),
            )
            out, _ = await asyncio.wait_for(proc.communicate(), 30)
        except (OSError, asyncio.TimeoutError):
            raise BackendUnavailable("could not run the Claude Code CLI") from None
        return out.decode("utf-8", "replace")

    def _ensure_workdir(self) -> str:
        if self._workdir is None:
            self._workdir = tempfile.mkdtemp(prefix="unistax-llm-")
            self._owns_workdir = True
        return self._workdir

    async def close(self) -> None:
        """Remove the private working directory."""
        if self._owns_workdir and self._workdir:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir, self._owns_workdir = None, False

    # -- command line ----------------------------------------------------------
    def build_command(self, request: LLMRequest) -> list[str]:
        """The exact argv for ``request`` (no data: the prompt goes through stdin)."""
        model = request.model or self.config.default_model
        effort = request.effort or self.config.default_effort
        if model is not None and not _MODEL.match(model):
            raise LLMError("invalid model name")
        if effort is not None and effort not in EFFORTS:
            raise LLMError(f"effort must be one of {sorted(EFFORTS)}")
        for tool in request.tools:
            if not _TOOL.match(tool):
                raise LLMError("invalid tool name")

        argv = [
            self.config.executable,
            "-p",
            "--output-format", "json",
            "--no-session-persistence",
            "--restricted",
            "--safe-mode",
            "--permission-prompts", "none",
            "--tools", ",".join(request.tools),
        ]  # fmt: skip
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        if request.system_prompt:
            if len(request.system_prompt) > MAX_SYSTEM_PROMPT_CHARS:
                raise LLMError("system prompt is too long")
            argv += ["--system-prompt", request.system_prompt]
        if request.json_schema is not None:
            schema = json.dumps(request.json_schema, separators=(",", ":"))
            if len(schema) > MAX_SCHEMA_CHARS:
                raise LLMError("JSON schema is too large")
            argv += ["--json-schema", schema]
        return argv

    # -- running -----------------------------------------------------------------
    async def run(self, request: LLMRequest) -> LLMResponse:
        """Run one headless call and return its parsed result."""
        argv = self.build_command(request)
        payload = request.prompt.encode("utf-8")
        if len(payload) > MAX_PROMPT_BYTES:
            raise LLMError("prompt is too large")
        timeout = request.timeout or self.config.default_timeout

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._ensure_workdir(),
                env=scrubbed_env(),
                start_new_session=True,  # lets us kill the whole process tree
            )
        except FileNotFoundError:
            raise BackendUnavailable(
                f"the Claude Code CLI '{self.config.executable}' was not found"
            ) from None
        except OSError:
            raise BackendUnavailable("could not start the Claude Code CLI") from None

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(payload), timeout)
        except asyncio.TimeoutError:
            await self._kill(proc)
            raise LLMTimeout(f"the model call exceeded {timeout:g}s and was stopped") from None
        except BaseException:
            await self._kill(proc)  # cancellation, shutdown, ...
            raise

        return self.parse(stdout, stderr, proc.returncode or 0)

    @staticmethod
    async def _kill(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    # -- parsing -------------------------------------------------------------------
    def parse(self, stdout: bytes, stderr: bytes, returncode: int) -> LLMResponse:
        """Turn the CLI's output into a response, or raise the matching error."""
        if len(stdout) > MAX_OUTPUT_BYTES:
            raise LLMOutputError("the model returned too much output")
        text = stdout.decode("utf-8", "replace").strip()
        stderr_text = stderr.decode("utf-8", "replace")

        data = _load_result(text)
        if data is None:
            raise _classify(None, None, f"{text}\n{stderr_text}", returncode)

        if data.get("is_error") or data.get("subtype", "success") != "success":
            raise _classify(
                data.get("api_error_status"),
                data.get("subtype"),
                f"{data.get('result') or ''}\n{stderr_text}",
                returncode,
            )

        result_text = data.get("result")
        result_text = result_text if isinstance(result_text, str) else ""
        structured = data.get("structured_output")
        usage = data.get("usage") or {}
        models = data.get("modelUsage") or {}
        main_model = max(
            models, key=lambda m: (models[m] or {}).get("outputTokens", 0), default=None
        )
        return LLMResponse(
            text=result_text,
            structured=structured,
            usage=Usage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                calls=1,
            ),
            nominal_cost_usd=float(data.get("total_cost_usd") or 0.0),
            num_turns=int(data.get("num_turns") or 1),
            duration_ms=int(data.get("duration_ms") or 0),
            model=main_model,
            session_id=data.get("session_id"),
        )


def _load_result(text: str) -> dict[str, Any] | None:
    """The ``result`` object from stdout, tolerating stray lines around it."""
    candidates = [text, *reversed([line for line in text.splitlines() if line.strip()])]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    return None


def _classify(status: Any, subtype: Any, message: str, returncode: int) -> LLMError:
    """Map a failed call to a specific, safe error (never echoes model or stderr text)."""
    code = status if isinstance(status, int) else None
    if code == 429 or (code is None and _USAGE_TEXT.search(message)):
        return UsageLimitReached(
            "the Claude usage limit has been reached; wait for it to reset, or reduce parallelism"
        )
    if code in (401, 403) or (code is None and _AUTH_TEXT.search(message)):
        return LLMAuthError(
            "the Claude Code CLI is not signed in (run `claude` once to log in, "
            "or provide credentials in the service environment)"
        )
    if code in (500, 502, 503, 504, 529) or (code is None and _OVERLOAD_TEXT.search(message)):
        return LLMOverloaded("Claude is temporarily overloaded")
    if subtype and subtype != "success":
        return LLMOutputError(f"the model run ended abnormally ({subtype})")
    if returncode != 0:
        return LLMOutputError(f"the Claude Code CLI failed (exit status {returncode})")
    return LLMOutputError("the Claude Code CLI returned output that could not be understood")
