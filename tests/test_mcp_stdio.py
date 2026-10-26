"""The MCP server through the window's own door: ``perfboard-studio --mcp``.

That door exists for an install with no Python to run ``python -m perfboard_studio.mcp``
with -- the Windows installer's ``perfboard-studio-cli.exe --mcp`` -- and it is a longer
road to stdout than the server's own: the frozen build's launcher, then ``ui/main.py``
and every Qt module it imports at the top, and only then the server. On stdio, stdout IS
the protocol, so every one of those must stay silent until the server owns the stream.
``test_mcp.py`` reads the MCP package for a ``print``; nothing reads the road in, so
these run it.

Each test is a whole session in a child process, checked by
``packaging/check-mcp-stdio.py`` -- the same script release.yml runs on every built
bundle, so what passes here is the check the artefact gets.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from perfboard_studio.version import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
CHECKER = REPO_ROOT / "packaging" / "check-mcp-stdio.py"


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_mcp_stdio", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _environment() -> dict[str, str]:
    # No display, as an MCP client gives none; and the source, not whatever is installed.
    return {**os.environ, "PYTHONPATH": str(SRC), "QT_QPA_PLATFORM": "offscreen"}


@pytest.mark.parametrize(
    "door",
    [
        # What the frozen build runs: launcher.py, which also gives a windowed process
        # without streams somewhere to write.
        ["launcher.py", "--mcp"],
        # What the `perfboard-studio` console script runs.
        ["-m", "perfboard_studio.ui.main", "--mcp"],
        # A board named after the flag, as `perfboard-studio-mcp board.perf` takes one.
        ["-m", "perfboard_studio.ui.main", "--mcp", "examples/ne555-astable.perf"],
    ],
    ids=["launcher", "console-script", "with-a-board"],
)
def test_the_window_door_serves_mcp_with_nothing_else_on_stdout(door: list[str]) -> None:
    summary = _checker().check([sys.executable, *door], cwd=str(REPO_ROOT), env=_environment())
    assert "stdout clean" in summary
    # ...with a placement in the session that two worker processes made, each handed the
    # server's stdout and each sending its own streams to the null device first.
    assert "placed with 2 worker processes" in summary, summary
    # The version a client is told is this release's, not the `mcp` library's.
    assert summary.startswith(f"perfboard-studio {__version__}:"), summary


def test_the_server_reports_this_release_as_its_version() -> None:
    """``initialize`` answers serverInfo from these options; FastMCP alone gives the
    ``mcp`` package's version there, which names a Perfboard Studio that does not exist."""
    from perfboard_studio.mcp.server import mcp

    options = mcp._mcp_server.create_initialization_options()
    assert (options.server_name, options.server_version) == ("perfboard-studio", __version__)


def test_the_checker_notices_a_worker_that_prints() -> None:
    """The placement in the session is there to catch a worker that writes to the stdout
    it inherited, so: workers started by an initializer that prints instead of silencing
    them, behind a real server. The print lands among the answers, where the client
    would read it as protocol."""
    loud = (
        "from perfboard_studio.ui import planner_pool\n"
        "from tests import planner_probe\n"
        "planner_pool._start_worker = planner_probe.start_loudly\n"
        "from perfboard_studio.mcp.server import main\n"
        "raise SystemExit(main([]))\n"
    )
    with pytest.raises(AssertionError, match="not JSON-RPC"):
        _checker().check([sys.executable, "-c", loud], cwd=str(REPO_ROOT), env=_environment())


def test_the_checker_notices_a_stray_line_before_the_server() -> None:
    """The check is only worth what it catches: one print, ahead of a real server."""
    stray = (
        "import sys; print('hello'); sys.argv[1:] = ['--mcp'];"
        "from perfboard_studio.ui.main import main; raise SystemExit(main())"
    )
    with pytest.raises(AssertionError, match="not JSON-RPC"):
        _checker().check([sys.executable, "-c", stray], cwd=str(REPO_ROOT), env=_environment())
