"""Fail unless a command speaks MCP over stdio with NOTHING else on stdout.

    python packaging/check-mcp-stdio.py ./dist/perfboard-studio/perfboard-studio-cli.exe --mcp
    python packaging/check-mcp-stdio.py python launcher.py --mcp

On stdio, stdout IS the protocol (docs/MCP.md): one stray line from an import, a banner
or a warning and the client reports something baffling and unrelated. That is checked
statically inside `perfboard_studio.mcp`, and it cannot be checked statically for the
road IN -- the launcher, the window's `main` and whatever they import first -- nor for a
frozen build, whose bootloader and runtime hooks run before any of our code. So this
starts the real command, has a whole session with it, and requires that every byte it
wrote to stdout is a JSON-RPC message, the first of them the answer to `initialize`.

THE SESSION PLACES A BOARD, WITH WORKERS. `optimize_placement` runs the placer's
restarts in worker processes, and a worker is a whole interpreter with the server's
stdout handed down to it -- which is why each one sends its streams to the null device
before it runs anything. So the session asks for two of them
(PERFBOARD_STUDIO_PLANNER_WORKERS), places the NE555 example, and fails unless the
answer says two worker processes did it: a bundle whose workers fell back to one
process would otherwise pass this check without ever having started one.

Used by `tests/test_mcp_stdio.py` on the source and by release.yml on every built
bundle, so the check that passed is the check the artefact gets. Standard library only:
release.yml runs it with whichever Python the runner has, outside the bundle.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

#: Long enough for a cold frozen start on a slow runner; the server answers in about a
#: second once it is up.
TIMEOUT_S = 180

#: Fewer would not be the server this repository ships (docs/MCP.md counts them).
MIN_TOOLS = 40

#: The board the session places: small, so two workers answer in seconds.
BOARD = Path(__file__).resolve().parents[1] / "examples" / "ne555-astable.perf"
#: How many workers the session asks for, and what the answer must then say.
WORKERS = 2


def _request(ident: int | None, method: str, params: dict[str, Any] | None = None) -> bytes:
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if ident is not None:
        message["id"] = ident
    if params is not None:
        message["params"] = params
    return (json.dumps(message) + "\n").encode("utf-8")


def check(command: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> str:
    """Run one session; return a one-line summary, or raise AssertionError saying why not."""
    # Unbuffered, so a stray write lands where it was made. Buffered, a print made before
    # the server starts sits in sys.stdout's buffer while the server writes underneath it
    # to sys.stdout.buffer, and comes out later or never -- until the day enough of it
    # piles up to be flushed into the middle of a message. A frozen build ignores PYTHON*
    # variables, so there this tightens nothing and costs nothing.
    env = {
        **(os.environ if env is None else env),
        "PYTHONUNBUFFERED": "1",
        "PERFBOARD_STUDIO_PLANNER_WORKERS": str(WORKERS),
    }
    assert BOARD.is_file(), f"the session's board is missing: {BOARD}"
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    assert process.stdin is not None and process.stdout is not None
    stderr_chunks: list[bytes] = []
    reader = threading.Thread(
        target=lambda: stderr_chunks.append(process.stderr.read() if process.stderr else b""),
        daemon=True,
    )
    reader.start()
    timer = threading.Timer(TIMEOUT_S, process.kill)
    timer.start()
    lines: list[bytes] = []
    try:
        process.stdin.write(_request(1, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "check-mcp-stdio", "version": "1"},
        }))
        process.stdin.flush()
        lines.append(process.stdout.readline())
        first = _parse(lines[0], stderr_chunks, process)
        assert first.get("id") == 1 and "result" in first, f"first message is not the answer to initialize: {first}"
        server = first["result"].get("serverInfo", {})

        process.stdin.write(_request(None, "notifications/initialized"))
        process.stdin.write(_request(2, "tools/list"))
        process.stdin.flush()
        while True:
            line = process.stdout.readline()
            lines.append(line)
            message = _parse(line, stderr_chunks, process)
            if message.get("id") == 2:
                break
        tools = message.get("result", {}).get("tools", [])
        assert len(tools) >= MIN_TOOLS, f"tools/list answered {len(tools)} tools"

        opened = _call(process, lines, stderr_chunks, 3, "open_document", {"path": str(BOARD)})
        assert opened.get("ok"), f"open_document: {opened}"
        placed = _call(
            process, lines, stderr_chunks, 4, "optimize_placement", {"seed": 0, "apply": False}
        )
        planner = str(placed.get("planner"))
        assert placed.get("ok") and planner == f"{WORKERS} worker processes", (
            f"optimize_placement did not place with {WORKERS} workers: {placed}"
        )

        process.stdin.close()
        rest = process.stdout.read()
        process.wait(timeout=30)
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
    for line in rest.splitlines():
        if line.strip():
            _parse(line + b"\n", stderr_chunks, process)
    return (
        f"{server.get('name')} {server.get('version')}: {len(tools)} tools, placed with "
        f"{planner}, stdout clean"
    )


def _call(
    process: subprocess.Popen[bytes],
    lines: list[bytes],
    stderr_chunks: list[bytes],
    ident: int,
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Call one tool and return what it answered, every line on the way checked."""
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(_request(ident, "tools/call", {"name": tool, "arguments": arguments}))
    process.stdin.flush()
    while True:
        line = process.stdout.readline()
        lines.append(line)
        message = _parse(line, stderr_chunks, process)
        if message.get("id") == ident:
            break
    result = message.get("result", {})
    assert not result.get("isError"), f"{tool} failed: {result}"
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        # FastMCP wraps a tool's dict under "result" when its schema is not an object.
        inner = structured.get("result")
        return inner if isinstance(inner, dict) and len(structured) == 1 else structured
    content = result.get("content") or [{}]
    answer = json.loads(content[0].get("text", "{}"))
    assert isinstance(answer, dict), f"{tool} answered {answer!r}"
    return answer


def _parse(line: bytes, stderr_chunks: list[bytes], process: subprocess.Popen[bytes]) -> dict[str, Any]:
    if not line:
        process.wait(timeout=30)
        raise AssertionError(
            f"stdout closed (exit {process.returncode}); stderr:\n" + _stderr(stderr_chunks)
        )
    try:
        message = json.loads(line)
    except ValueError:
        raise AssertionError(
            f"a line on stdout that is not JSON-RPC: {line[:200]!r}\nstderr:\n" + _stderr(stderr_chunks)
        ) from None
    assert isinstance(message, dict) and message.get("jsonrpc") == "2.0", f"not JSON-RPC: {line[:200]!r}"
    return message


def _stderr(chunks: list[bytes]) -> str:
    return b"".join(chunks).decode("utf-8", "replace")[-4000:]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    try:
        print(check(sys.argv[1:]))
    except AssertionError as problem:
        print(f"::error::{problem}", file=sys.stderr)
        raise SystemExit(1) from None
