"""The placer's worker processes (``ui/planner_pool.py``), held to five promises.

A pooled placement is the serial placement, to the byte; a worker loads neither Qt nor the
window and prints nothing; a Cancel brings back the best found so far; a worker that does
not answer a Cancel is ended within the grace period and the next placement still works;
and closing leaves no worker behind. These start real worker processes, so they ask for
workers themselves -- the rest of the suite runs serial (``tests/conftest.py``).
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from perfboard_studio import persist
from perfboard_studio.boardfit import BoardTrialOptions, try_board
from perfboard_studio.command import CommandContext
from perfboard_studio.commands import (
    UnplaceComponentPayload,
    create_document_id_generator,
    unplace_component,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import PerfDocument
from perfboard_studio.placer import PlacementOptions, plan_placement, suggest_boards
from perfboard_studio.ui import planner_pool

from . import planner_probe

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "ne555-astable.perf"
LOOKUP = footprint_lookup()
#: Short anneals: what is being tested is how the work is run, not how good it is.
QUICK = PlacementOptions(seed=0, iterations=400)


@pytest.fixture(autouse=True)
def two_workers(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv(planner_pool.WORKERS_VARIABLE, "2")
    yield
    planner_pool.shutdown()


def _board() -> PerfDocument:
    return persist.parse_document_or_throw(EXAMPLE.read_text(encoding="utf-8"))


def _design() -> PerfDocument:
    """The example with every part back in the design, as a board is chosen for it."""
    doc = dataclasses.replace(_board(), conductors=(), cuts=())
    for component in doc.components:
        doc = unplace_component.apply(
            doc,
            UnplaceComponentPayload(id=component.id),
            CommandContext(next_id=create_document_id_generator(doc)),
        )
    return doc


def _never() -> bool:
    return False


def _after(seconds: float):  # type: ignore[no-untyped-def]
    started = time.monotonic()
    return lambda: time.monotonic() - started > seconds


def _workers() -> list:  # type: ignore[type-arg]
    pool = planner_pool._pool
    return [] if pool is None else list(pool._pool)  # type: ignore[attr-defined]


# -- how many ------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "count"), [("0", 0), ("1", 0), ("2", 2), ("3", 3), ("x", 0)])
def test_the_variable_sets_the_number_of_workers(monkeypatch, value, count) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(planner_pool.WORKERS_VARIABLE, value)
    assert planner_pool.worker_count() == count


@pytest.mark.parametrize(("cpus", "count"), [(None, 0), (1, 0), (2, 0), (3, 2), (5, 4), (32, 4)])
def test_one_processor_is_left_for_the_window_and_one_worker_is_none(monkeypatch, cpus, count) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(planner_pool.WORKERS_VARIABLE)
    monkeypatch.setattr(planner_pool.os, "cpu_count", lambda: cpus)
    assert planner_pool.worker_count() == count
    assert (planner_pool.mapper_for(_never) is None) == (count == 0)


# -- the same answer -----------------------------------------------------------------


def test_a_pooled_placement_is_the_serial_placement() -> None:
    doc = _board()
    serial = plan_placement(doc, LOOKUP, QUICK)
    pooled = plan_placement(doc, LOOKUP, QUICK, mapper=planner_pool.mapper_for(_never))
    assert pooled == serial
    assert pooled.routed is not None, "the routes that judged it ran in the pool too"


def test_a_pooled_board_trial_is_the_serial_one() -> None:
    design = _design()
    suggestion = suggest_boards(design.board, [], design.nets, LOOKUP)[0]
    options = BoardTrialOptions(placement=QUICK)
    serial = try_board(design, suggestion, LOOKUP, options)
    pooled = try_board(design, suggestion, LOOKUP, options, mapper=planner_pool.mapper_for(_never))
    assert serial is not None and pooled == serial


# -- what a worker is ----------------------------------------------------------------


def test_a_worker_loads_neither_qt_nor_the_window(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """From source, ``__main__`` is the window, and spawn re-imports ``__main__`` in every
    worker. Here a stand-in ``__main__`` that imports Qt plays the window, and a worker must
    not load it -- and does, once the swap that prevents it is taken away, which is what
    makes this a test of the swap rather than of the stand-in."""
    (tmp_path / "pretend_window.py").write_text("import PySide6.QtCore\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    import pretend_window  # type: ignore[import-not-found]

    monkeypatch.setitem(sys.modules, "__main__", pretend_window)
    planner_pool.shutdown()
    run = planner_pool.mapper_for(_never)
    assert run is not None
    assert list(run(planner_probe.what_the_worker_loaded, [0, 1])) == [(False, False)] * 2
    assert sys.modules["__main__"] is pretend_window, "the swap was not undone"

    planner_pool.shutdown()
    monkeypatch.setattr(planner_pool, "_workers_start_here", contextlib.nullcontext)
    loaded = list(run(planner_probe.what_the_worker_loaded, [0, 1]))
    assert all(qt for qt, _ in loaded), "the stand-in did not reach the workers; this test proves nothing"


def test_a_worker_prints_nothing(capfd) -> None:  # type: ignore[no-untyped-def]
    """The MCP server's stdout is its protocol, and a worker inherits it. ``capfd`` sees what
    a spawned child writes to the inherited streams, so a print that got through shows."""
    run = planner_pool.mapper_for(_never)
    assert run is not None
    assert list(run(planner_probe.print_and_answer, ["a", "b"])) == ["a", "b"]
    out, err = capfd.readouterr()
    assert "stray print" not in out and "stderr" not in err


# -- stopping ------------------------------------------------------------------------


def test_a_cancel_brings_back_the_best_found_so_far_and_the_next_run_works() -> None:
    """Anneals that would run for minutes, cancelled after one second: every worker hands
    back where it had got to, and the placement is a whole board, not nothing."""
    doc = _board()
    stop = _after(1.0)
    started = time.monotonic()
    plan = plan_placement(
        doc,
        LOOKUP,
        PlacementOptions(seed=0, iterations=50_000_000),
        should_stop=stop,
        mapper=planner_pool.mapper_for(stop),
    )
    took = time.monotonic() - started
    assert took < 1.0 + planner_pool.STOP_GRACE_S, f"the stop took {took:.1f} s to land"
    assert {c.id for c in plan.document.components} == {c.id for c in doc.components}
    assert plan.iterations == 50_000_000 and plan.accepted < 50_000_000

    again = plan_placement(doc, LOOKUP, QUICK, mapper=planner_pool.mapper_for(_never))
    assert again == plan_placement(doc, LOOKUP, QUICK)


def test_a_worker_that_ignores_the_cancel_is_ended_and_the_next_run_works(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(planner_pool, "STOP_GRACE_S", 1.0)
    stop = _after(0.2)
    run = planner_pool.mapper_for(stop)
    assert run is not None
    started = time.monotonic()
    with pytest.raises(planner_pool.PlannerStopped):
        list(run(planner_probe.ignore_the_stop, [0, 1]))
    assert time.monotonic() - started < 0.2 + 1.0 + 2.0
    assert planner_pool._pool is None

    after = planner_pool.mapper_for(_after(0.1))
    assert after is not None
    assert list(after(planner_probe.wait_for_the_stop, [0, 1])) == [True, True]


def test_closing_leaves_no_worker_behind() -> None:
    run = planner_pool.mapper_for(_never)
    assert run is not None
    list(run(planner_probe.print_and_answer, [0]))
    workers = _workers()
    assert workers and all(worker.is_alive() for worker in workers)
    planner_pool.shutdown()
    assert all(worker.exitcode is not None for worker in workers)
    assert planner_pool._pool is None


# -- workers that will not start ----------------------------------------------------


def _refuse(context, count, stop):  # type: ignore[no-untyped-def]
    raise OSError("no processes here")


def test_a_pool_that_cannot_be_made_leaves_the_placement_in_this_process(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(planner_pool, "_new_pool", _refuse)
    doc = _board()
    pooled = plan_placement(doc, LOOKUP, QUICK, mapper=planner_pool.mapper_for(_never))
    assert pooled == plan_placement(doc, LOOKUP, QUICK)
    assert planner_pool.describe() == (
        "in this process: the workers would not start (OSError: no processes here)"
    )
    assert planner_pool.mapper_for(_never) is None, "the rest of the session stays in one process"
    planner_pool.shutdown()
    assert planner_pool.describe() == "2 worker processes", "and the next session tries again"


def test_workers_that_never_answer_are_given_up_on(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A bundle whose workers cannot start leaves them running nothing useful: they are
    given :data:`START_TIMEOUT_S` to answer an empty job, then ended, and the placement is
    made in this process instead -- the same placement."""
    monkeypatch.setattr(planner_pool, "START_TIMEOUT_S", 1.0)
    monkeypatch.setattr(planner_pool, "START_PROBE", planner_probe.ignore_the_stop)
    doc = _board()
    pooled = plan_placement(doc, LOOKUP, QUICK, mapper=planner_pool.mapper_for(_never))
    assert pooled == plan_placement(doc, LOOKUP, QUICK)
    assert planner_pool.describe() == "in this process: the workers would not start (no answer within 1 s)"
    assert planner_pool._pool is None, "the workers that did not answer were ended"


# -- the window ----------------------------------------------------------------------


@pytest.fixture
def window(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui import main as main_module

    QApplication.instance() or QApplication([])
    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    made = main_module.MainWindow(_board())
    yield made
    made._saved_document = made.bus.document
    made.close()


def test_the_window_reads_ended_workers_as_a_cancel_and_stays_usable(window) -> None:  # type: ignore[no-untyped-def]
    def ended(should_stop):  # type: ignore[no-untyped-def]
        raise planner_pool.PlannerStopped("ended")

    assert window._run_planner("Placing", ended) is None
    assert window.isEnabled() and not window._planner_running
    assert window.statusBar().currentMessage() == (
        "Cancelled before an arrangement was finished; the board is as it was."
    )
    assert window._run_planner("Choosing", ended, stopped="Nothing changed.") is None
    assert window.statusBar().currentMessage() == "Nothing changed."


def test_the_window_still_places_when_its_workers_will_not_start(window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui import main as main_module

    monkeypatch.setattr(planner_pool, "_new_pool", _refuse)
    plans: list[object] = []
    real = main_module.plan_placement

    def recorded(*args, **kwargs):  # type: ignore[no-untyped-def]
        plans.append(real(*args, **kwargs))
        return plans[-1]

    monkeypatch.setattr(main_module, "plan_placement", recorded)
    monkeypatch.setattr(window, "_confirm_placement", lambda plan: False)
    window.on_autoplace()
    assert len(plans) == 1 and plans[0] is not None
    assert planner_pool.describe().startswith("in this process: the workers would not start")
    assert window.isEnabled() and not window._planner_running
