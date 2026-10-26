"""The placer's worker processes: one pool per window process, made the first time it is
needed, and the only place this application runs Python in more than one process.

A placement is four independent, seeded anneals and a handful of independent routes to
judge them (``placer.plan_placement``); run side by side they take the time of the slowest
instead of the sum. The engine knows none of this: it takes a ``placer.Mapper`` and calls
it, and :func:`mapper_for` is the one the window hands it. Being seeded, the answer is the
same however the work is run -- ``tests/test_planner_pool.py`` holds a pooled placement to
the serial one -- so the pool decides how long a placement takes and nothing else.

Six things carry it:

- **Spawn, on every system.** A forked child of a process that has started Qt inherits its
  locks in whatever state they were in, and can hang on the first one held -- Python calls
  fork unsafe in a threaded process, and Windows and macOS spawn by default. Spawn starts
  every worker clean. (The documented reason; it was not measured here.)
- **The workers import the engine and not the window.** Spawn re-imports the parent's
  ``__main__`` in every child, and from source that is ``ui/main.py``: Qt and the whole
  window, 0.4 s and 40 MB a worker, for nothing. So while the workers start, ``__main__``
  is this module (:func:`_workers_start_here`). A frozen build gets the same from
  ``multiprocessing.freeze_support()``, the first line of ``launcher.py``.
- **A stop keeps the best so far.** The window's Cancel sets one Event every worker shares,
  and each anneal sees it as its ``should_stop`` and ends on its next check with the best it
  has, as it would in the window's own thread. Only a worker that has not answered
  :data:`STOP_GRACE_S` after the stop is ended -- the pool with it -- and then nothing comes
  back (:class:`PlannerStopped`).
- **A worker says nothing.** Its stdout and stderr go to the null device, file descriptors
  and all, because the MCP server's stdout is its protocol and a worker inherits it.
- **The suite runs serial.** ``tests/conftest.py`` sets :data:`WORKERS_VARIABLE` to 0: a
  suite that built four processes per window would run the machine out of memory.
- **Workers that cannot start cost one wait, once.** A new pool's workers must answer an
  empty job within :data:`START_TIMEOUT_S`; if the pool cannot be made, or they do not
  answer -- a bundle whose workers cannot start would otherwise leave Place on the Board
  waiting on nothing -- the pool is ended, the placement runs in the calling thread as it
  does with no workers, and so does every other for the rest of the session.
  :func:`describe` says which happened, and release.yml's bundle checks read it.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocessing.pool import Pool
    from multiprocessing.synchronize import Event

    from perfboard_studio.placer import Mapper

#: The number of workers, when set: ``0`` or ``1`` means none, the work runs in the
#: calling thread as it always did. Unset, it is :func:`worker_count`'s own answer.
WORKERS_VARIABLE = "PERFBOARD_STUDIO_PLANNER_WORKERS"

#: A placement has four restarts by default; a fifth worker would wait for nothing.
MAX_WORKERS = 4

#: How long the workers have, after a stop, to hand back their best before they are ended.
#: An anneal looks at the stop every 512 moves, which on the largest example is well under
#: a tenth of a second; this is for a worker that has stopped answering altogether.
STOP_GRACE_S = 5.0

#: How often a waiting map looks at the window's Cancel.
POLL_S = 0.05

#: How long a new pool's workers have to answer their first, empty job. A frozen worker
#: answers in about a second on the machine this was written on; this is for one that
#: never will.
START_TIMEOUT_S = 20.0


class PlannerStopped(Exception):
    """The workers did not answer a stop within :data:`STOP_GRACE_S` and were ended, so the
    run has no result: the window treats it as a cancel with nothing to keep."""


def worker_count() -> int:
    """How many workers a placement gets: :data:`WORKERS_VARIABLE` when it is set, and
    otherwise one less than the processors, at most :data:`MAX_WORKERS` -- one is left for
    the window. Anything below two is none at all: one worker is one restart at a time,
    which is the calling thread's job without the cost of a process."""
    configured = os.environ.get(WORKERS_VARIABLE)
    if configured is not None:
        try:
            count = int(configured)
        except ValueError:
            count = 0
    else:
        count = min(MAX_WORKERS, (os.cpu_count() or 1) - 1)
    return count if count >= 2 else 0


_lock = threading.Lock()
_pool: Pool | None = None
_stop: Event | None = None
#: Why this session's workers could not be used, once they could not. Until
#: :func:`shutdown`, every placement then runs in the calling thread.
_broken: str | None = None
#: How many workers the running pool has; 0 with none running.
_running = 0


class _WouldNotStart(Exception):
    """The pool could not be made, or its workers did not answer in time."""


def mapper_for(should_stop: Callable[[], bool]) -> Mapper | None:
    """A ``placer.Mapper`` that runs on the shared pool and hands every worker the shared
    stop, set when ``should_stop`` turns true -- or None when this machine gets no workers,
    which leaves the placer in the calling thread exactly as before -- as it does once
    this session's workers have failed to start."""
    if worker_count() == 0 or _broken is not None:
        return None

    def run(
        work: Callable[[Any, Callable[[], bool] | None], Any], jobs: Sequence[Any]
    ) -> list[Any]:
        try:
            pool, stop = _shared()
        except _WouldNotStart:
            # Nothing has run yet, so the work is done here instead: the same jobs and
            # the same answers, in order, with the caller's own stop.
            return [work(job, should_stop) for job in jobs]
        stop.clear()
        pending = pool.map_async(_call, [(work, job) for job in jobs])
        asked: float | None = None
        while not pending.ready():
            pending.wait(POLL_S)
            if asked is None:
                if should_stop():
                    stop.set()
                    asked = time.monotonic()
            elif not pending.ready() and time.monotonic() - asked > STOP_GRACE_S:
                shutdown()
                raise PlannerStopped(
                    f"the planner's workers did not stop within {STOP_GRACE_S:.0f} s"
                )
        return pending.get()

    return run


def shutdown() -> None:
    """End the workers, at once. The next :func:`mapper_for` starts new ones, and tries
    again if the last ones would not start."""
    global _pool, _stop, _broken, _running
    with _lock:
        pool, _pool, _stop, _broken, _running = _pool, None, None, None, 0
    if pool is not None:
        pool.terminate()
        pool.join()


def describe() -> str:
    """How this session's placements have run, in the words ``--headless`` prints.

    WHAT HAS HAPPENED, NOT WHAT WOULD: "2 worker processes" only while two are running,
    which only a placement handed :func:`mapper_for` starts. It used to read the setting,
    so a host that placed without the mapper was still described as pooled -- and the
    release check and the MCP stdio check, which grep this line to know their placement
    used workers, would have passed a build that never started one.
    """
    if _broken is not None:
        return f"in this process: the workers would not start ({_broken})"
    return f"{_running} worker processes" if _pool is not None else "in this process"


def _shared() -> tuple[Pool, Event]:
    global _pool, _stop, _broken, _running
    with _lock:
        if _broken is not None:
            raise _WouldNotStart(_broken)
        if _pool is None or _stop is None:
            # Imported here, at the first placement that wants workers, and not with the
            # window: the window imports this module at start, and multiprocessing is a
            # dozen modules a start does not need (tests/test_startup.py lists what a
            # start may import).
            import multiprocessing

            context = multiprocessing.get_context("spawn")
            stop = context.Event()
            pool: Pool | None = None
            try:
                count = worker_count()
                with _workers_start_here(), _workers_read_nothing():
                    pool = _new_pool(context, count, stop)
                pool.apply_async(_call, ((START_PROBE, None),)).get(timeout=START_TIMEOUT_S)
            except Exception as failure:
                if pool is not None:
                    pool.terminate()
                    pool.join()
                _broken = (
                    f"no answer within {START_TIMEOUT_S:.0f} s"
                    if isinstance(failure, multiprocessing.TimeoutError)
                    else f"{type(failure).__name__}: {failure}"
                )
                raise _WouldNotStart(_broken) from failure
            _pool, _stop, _running = pool, stop, count
        return _pool, _stop


def _new_pool(context: Any, count: int, stop: Event) -> Pool:
    pool: Pool = context.Pool(count, initializer=_start_worker, initargs=(stop,))
    return pool


@contextlib.contextmanager
def _workers_start_here() -> Iterator[None]:
    """While the workers spawn, make this module the ``__main__`` they re-import.

    ``multiprocessing.spawn`` tells a child to import whatever ``sys.modules["__main__"]``
    is in the parent, by name when it has one. From source that is ``ui/main.py`` -- Qt and
    the whole window, measured at 0.4 s and 40 MB more a worker than the engine alone --
    and this module imports the standard library and nothing else. Every worker is started
    inside :func:`_shared`, which is the whole extent of the swap; a frozen build is left
    alone, because ``freeze_support`` in ``launcher.py`` already stops a worker there before
    it imports anything.
    """
    if getattr(sys, "frozen", False):
        yield
        return
    real = sys.modules["__main__"]
    sys.modules["__main__"] = sys.modules[__name__]
    try:
        yield
    finally:
        sys.modules["__main__"] = real


#: ``STD_INPUT_HANDLE``, the DWORD -10.
_STD_INPUT_HANDLE = 0xFFFFFFF6


@contextlib.contextmanager
def _workers_read_nothing() -> Iterator[None]:
    """While the workers spawn, point this process's standard input at the null device.

    WINDOWS HANDS A NEW PROCESS ITS PARENT'S STANDARD HANDLES, and the MCP server always
    has a read pending on its stdin: that is how it waits for the next request. A pipe
    opened for synchronous I/O does one thing at a time, so a worker whose Python asks
    about that handle as it starts waits behind the read -- until the client says
    something, which it will not, being busy waiting for the answer the worker was started
    to give. Every placement through the server fell back to one process after
    :data:`START_TIMEOUT_S`. Measured on its own: no answer in 15 s with a read pending,
    0.3 s with stdin on NUL. Only the handle a CHILD is given changes; the server goes on
    reading its own. Nothing to do elsewhere: a forked-and-exec'd child shares the pipe
    without queueing behind anybody's read.
    """
    if sys.platform != "win32":
        yield
        return
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    kernel32.GetStdHandle.argtypes = (ctypes.c_uint32,)
    kernel32.SetStdHandle.restype = ctypes.c_int
    kernel32.SetStdHandle.argtypes = (ctypes.c_uint32, ctypes.c_void_p)
    real = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
    with open(os.devnull, "rb") as nul:
        kernel32.SetStdHandle(_STD_INPUT_HANDLE, msvcrt.get_osfhandle(nul.fileno()))
        try:
            yield
        finally:
            kernel32.SetStdHandle(_STD_INPUT_HANDLE, real)


# -- in the worker ------------------------------------------------------------------

_worker_stop: Event | None = None


def _start_worker(stop: Event) -> None:
    """Keep the shared stop, and send everything the worker would print to nowhere."""
    global _worker_stop
    _worker_stop = stop
    quiet = open(os.devnull, "w")  # noqa: SIM115 -- held for the worker's whole life
    with contextlib.suppress(OSError):
        os.dup2(quiet.fileno(), 1)
        os.dup2(quiet.fileno(), 2)
    sys.stdout = quiet
    sys.stderr = quiet


def _answer(job: object, should_stop: Callable[[], bool] | None) -> bool:
    """The empty job a new pool must answer before any placement is handed to it."""
    return True


#: What a new pool is asked first. A name, so a test can ask something that never answers.
START_PROBE: Callable[[Any, Callable[[], bool] | None], Any] = _answer


def _call(item: tuple[Callable[[Any, Callable[[], bool] | None], Any], Any]) -> Any:
    work, job = item
    stop = _worker_stop
    return work(job, stop.is_set if stop is not None else None)
