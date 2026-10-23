"""Work for tests/test_planner_pool.py to hand a worker process.

Its own module, importing nothing but the standard library: a worker imports whatever a
job's function lives in, and the point of one probe is to see what ELSE a worker loaded.
Each takes ``(job, should_stop)``, the shape ``placer.Mapper`` hands its work.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable


def what_the_worker_loaded(job: object, should_stop: Callable[[], bool] | None) -> tuple[bool, bool]:
    """(Qt is loaded, the window is loaded) in this worker."""
    return "PySide6" in sys.modules, "perfboard_studio.ui.main" in sys.modules


def print_and_answer(job: object, should_stop: Callable[[], bool] | None) -> object:
    """Write to both streams, the way a stray print would, then answer."""
    print("a stray print from a worker")
    print("and one to stderr", file=sys.stderr)
    return job


def ignore_the_stop(job: object, should_stop: Callable[[], bool] | None) -> object:
    """A worker that never looks at the stop: what the grace period is for."""
    time.sleep(60)
    return job


def wait_for_the_stop(job: object, should_stop: Callable[[], bool] | None) -> bool:
    """Run until stopped, and say whether it was the stop that ended it."""
    give_up = time.monotonic() + 60
    while time.monotonic() < give_up:
        if should_stop is not None and should_stop():
            return True
        time.sleep(0.01)
    return False
