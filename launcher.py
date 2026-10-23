"""Frozen-build entry point.

PyInstaller runs its entry script as a top-level module, which breaks the relative
imports inside a package. Going through this file keeps ``perfboard-studio`` a real package at
runtime.

It exists only for the packaged builds. Running from source goes through the
``perfboard-studio`` console script that ``pyproject.toml`` declares, which calls the same
``main``.
"""

import io
import multiprocessing
import sys


def _ensure_streams() -> None:
    """Give the windowed build somewhere to write.

    A frozen windowed process has no console, and PyInstaller sets ``sys.stdout`` and
    ``sys.stderr`` to ``None`` rather than to something inert. Anything that prints then
    raises ``AttributeError`` on ``None.write`` -- and ``perfboard-studio --version`` prints,
    so it would not print nothing, it would fall over. The command line has its own
    console build (``perfboard-studio-cli.exe``); this is so that the windowed one cannot be
    taken down by a stray write.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, io.StringIO())


_ensure_streams()

# The placer's worker processes (``ui/planner_pool.py``) are this executable started again
# with multiprocessing's own arguments. Here, before the window's import below, is where
# such a process is recognised, runs its work and exits: it never imports Qt or the window,
# which is 40 MB and 0.4 s a worker. Without this line a frozen worker would run the whole
# application instead. Streams first, so a worker of the windowed build has somewhere to
# write a traceback.
multiprocessing.freeze_support()

from perfboard_studio.ui.main import main  # noqa: E402  - streams first, then imports

if __name__ == "__main__":
    raise SystemExit(main())
