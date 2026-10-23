"""Settings for the whole suite, before any test module is imported."""

from __future__ import annotations

import os

# The placer runs serially unless a test asks for workers itself (tests/test_planner_pool.py
# does, through monkeypatch). Every window a UI test builds would otherwise start up to
# four worker processes of its own on its first placement, and the suite already runs
# under a lock because parallel runs ran the machine out of memory. Set, not defaulted
# from the environment the suite inherits: a shell where somebody turned workers on to
# try the window must not change what the suite measures.
os.environ["PERFBOARD_STUDIO_PLANNER_WORKERS"] = "0"
