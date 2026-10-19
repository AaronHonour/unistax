"""A stand-in for the `claude` executable that records what it receives.

Behaviour is chosen with CLAUDE_FAKE_MODE and the record goes to CLAUDE_FAKE_LOG (both
start with CLAUDE_ so they survive the backend's environment scrubbing).
"""

import json
import os
import subprocess
import sys
import time

mode = os.environ.get("CLAUDE_FAKE_MODE", "ok")
args = sys.argv[1:]

if "--version" in args:
    print("9.9.9 (Claude Code, fake)")
    sys.exit(0)
if "--help" in args:
    flags = [
        "--output-format",
        "--no-session-persistence",
        "--restricted",
        "--safe-mode",
        "--permission-prompts",
        "--json-schema",
        "--tools",
        "--system-prompt",
        "--model",
    ]
    if mode == "oldhelp":
        flags.remove("--restricted")
    print("Usage: claude [options]\n" + "\n".join(f"  {f} <x>" for f in flags))
    sys.exit(0)

stdin = sys.stdin.read()
record = {
    "argv": args,
    "stdin": stdin,
    "env": sorted(os.environ),
    "env_values": {k: v for k, v in os.environ.items() if k.startswith("CLAUDE_FAKE")},
    "cwd": os.getcwd(),
    "pid": os.getpid(),
}
log = os.environ.get("CLAUDE_FAKE_LOG")


def write_record(**extra):
    if log:
        with open(log, "a") as handle:
            handle.write(json.dumps({**record, **extra}) + "\n")


def result(**overrides):
    base = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "echo:" + stdin[:40],
        "num_turns": 1,
        "duration_ms": 12,
        "total_cost_usd": 0.0123,
        "session_id": "fake-session",
        "api_error_status": None,
        "usage": {
            "input_tokens": 11,
            "output_tokens": 7,
            "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 50,
        },
        "modelUsage": {"claude-small": {"outputTokens": 1}, "claude-main": {"outputTokens": 7}},
    }
    if "--json-schema" in args:
        base["structured_output"] = {"echo": True, "stdin_chars": len(stdin)}
    base.update(overrides)
    return json.dumps(base)


if mode == "hang":
    child = subprocess.Popen(["sleep", "120"])
    write_record(child_pid=child.pid)
    time.sleep(120)
    sys.exit(0)

write_record()
if mode == "ok":
    print(result())
elif mode == "noisy":
    print("Warning: something printed a banner first")
    print(result())
    print("trailing line")
elif mode == "usage_status":
    print(
        result(
            is_error=True, subtype="success", api_error_status=429, result="Request rejected (429)"
        )
    )
    sys.exit(1)
elif mode == "usage_text":
    print(result(is_error=True, result="5-hour limit reached ∙ resets 3pm"))
    sys.exit(1)
elif mode == "auth_status":
    print(result(is_error=True, api_error_status=401, result="Invalid API key"))
    sys.exit(1)
elif mode == "auth_text":
    print("Not logged in · Please run /login", file=sys.stderr)
    sys.exit(1)
elif mode == "overloaded":
    print(result(is_error=True, api_error_status=529, result="Overloaded"))
    sys.exit(1)
elif mode == "max_turns":
    print(result(is_error=True, subtype="error_max_turns", result="secret model text"))
    sys.exit(1)
elif mode == "garbage":
    print("this is not json")
elif mode == "empty_fail":
    sys.exit(3)
elif mode == "no_structured":
    print(result(structured_output=None, result="plain text, no structure"))
elif mode == "big":
    print(
        json.dumps(
            {"type": "result", "subtype": "success", "is_error": False, "result": "x" * 5000}
        )
    )
else:
    print(f"unknown fake mode {mode}", file=sys.stderr)
    sys.exit(9)
