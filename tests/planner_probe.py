"""Work for tests/test_planner_pool.py to hand a worker process.

Its own module, importing nothing but the standard library: a worker imports whatever a
job's function lives in, and the point of one probe is to see what ELSE a worker loaded.
Each takes ``(job, should_stop)``, the shape ``placer.Mapper`` hands its work.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable


class DieOnce:
    """``work``, except that the first worker to run it dies on the spot, the way a worker
    killed from outside does -- once, marked by a file, so the rerun in the calling process
    (and every worker after the first) does the real work."""

    def __init__(self, marker: str, work: Callable[[object, Callable[[], bool] | None], object]):
        self.marker = marker
        self.work = work

    def __call__(self, job: object, should_stop: Callable[[], bool] | None) -> object:
        if not os.path.exists(self.marker):
            with open(self.marker, "w"):
                pass
            os._exit(1)
        return self.work(job, should_stop)


def take_a_while_and_say_who(job: object, should_stop: Callable[[], bool] | None) -> int:
    """Half a second's work, answered with the worker's pid: four of them over two live
    workers come back with both pids, and over one that is serving with one."""
    time.sleep(0.5)
    return os.getpid()


def what_the_worker_loaded(job: object, should_stop: Callable[[], bool] | None) -> tuple[bool, bool]:
    """(Qt is loaded, the window is loaded) in this worker."""
    return "PySide6" in sys.modules, "perfboard_studio.ui.main" in sys.modules


def print_and_answer(job: object, should_stop: Callable[[], bool] | None) -> object:
    """Write to both streams, the way a stray print would, then answer."""
    print("a stray print from a worker")
    print("and one to stderr", file=sys.stderr)
    return job


def start_loudly(stop: object) -> None:
    """A worker initializer that leaves the worker's streams where they were and says so on
    stdout: what a worker that slipped its silencing would do to an MCP server's protocol."""
    print("a stray print from a worker starting")


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
