"""Tests for the step bar (src/perfboard_studio/ui/workflow.py).

The steps are measured off the document, so the interesting half is a pure function of
counts -- ``workflow_steps`` -- and is tested here by handing it counts. The window half --
that the bar follows the document and each step goes where it is done -- is in
``test_ui.py``, beside the fixtures that keep a test window out of the user's settings.
"""

from __future__ import annotations

import dataclasses

from perfboard_studio.ui.workflow import (
    STEP_ORDER,
    WorkflowFacts,
    next_step,
    workflow_steps,
)

EMPTY = WorkflowFacts(
    parts_off_board=0,
    parts_on_board=0,
    nets=0,
    board_label="5 x 7 cm · 18 × 24",
    board_chosen=False,
    unrouted=0,
    drc_errors=0,
    drc_warnings=0,
    lvs_problems=0,
)


def statuses(facts: WorkflowFacts) -> dict[str, str]:
    return {step.key: step.status for step in workflow_steps(facts)}


def test_a_new_document_starts_at_the_circuit_and_nothing_is_done() -> None:
    steps = statuses(EMPTY)
    assert steps["circuit"] == "current"
    assert all(status == "todo" for key, status in steps.items() if key != "circuit")
    assert next_step(workflow_steps(EMPTY)) == "circuit"


def test_the_steps_are_in_the_order_a_board_is_built() -> None:
    assert STEP_ORDER == ("circuit", "board", "place", "route", "check", "build")
    assert [step.key for step in workflow_steps(EMPTY)] == list(STEP_ORDER)


def test_parts_without_a_single_join_are_not_a_circuit_yet() -> None:
    """Eight parts and no nets is a parts list: routing it would do nothing. And the next
    thing to do is to join them, not to add a ninth."""
    facts = dataclasses.replace(EMPTY, parts_off_board=8)
    assert statuses(facts)["circuit"] == "current"
    circuit = workflow_steps(facts)[0]
    assert circuit.action == "Connect the Pins"
    assert workflow_steps(EMPTY)[0].action == "Add a Part…"


def test_a_drawn_circuit_moves_on_to_choosing_its_board() -> None:
    facts = dataclasses.replace(EMPTY, parts_off_board=8, nets=7)
    steps = statuses(facts)
    assert steps["circuit"] == "done"
    assert steps["board"] == "current"
    assert next_step(workflow_steps(facts)) == "board"


def test_a_chosen_board_moves_on_to_placing() -> None:
    facts = dataclasses.replace(EMPTY, parts_off_board=8, nets=7, board_chosen=True)
    assert statuses(facts)["board"] == "done"
    assert next_step(workflow_steps(facts)) == "place"


def test_a_board_with_parts_on_it_has_been_chosen() -> None:
    """Nobody has to press Choose a Board on a document opened with a layout in it."""
    facts = dataclasses.replace(EMPTY, parts_on_board=3, parts_off_board=5, nets=4)
    steps = statuses(facts)
    assert steps["board"] == "done"
    assert steps["place"] == "current"


def test_a_placed_board_with_connections_left_is_waiting_for_its_wiring() -> None:
    facts = dataclasses.replace(EMPTY, parts_on_board=8, nets=7, unrouted=14)
    steps = statuses(facts)
    assert steps["place"] == "done"
    assert steps["route"] == "current"
    route = next(step for step in workflow_steps(facts) if step.key == "route")
    assert "14" in route.summary


def test_a_clean_routed_board_is_ready_to_build() -> None:
    facts = dataclasses.replace(EMPTY, parts_on_board=8, nets=7, drc_warnings=2)
    steps = statuses(facts)
    assert steps["route"] == "done"
    assert steps["check"] == "done", "warnings are for reading, not for stopping"
    assert steps["build"] == "current"
    assert next_step(workflow_steps(facts)) == "build"


def test_an_error_is_a_problem_and_the_next_button_goes_to_it_first() -> None:
    """A DRC error or an open net is where the button goes, whatever else is left: the
    board as drawn cannot be built, and the rest of the steps are built on it."""
    facts = dataclasses.replace(EMPTY, parts_on_board=8, nets=7, unrouted=3, drc_errors=1)
    steps = statuses(facts)
    assert steps["check"] == "problem"
    assert steps["route"] == "current"
    assert next_step(workflow_steps(facts)) == "check"

    open_net = dataclasses.replace(EMPTY, parts_on_board=8, nets=7, lvs_problems=1)
    assert statuses(open_net)["check"] == "problem"


def test_a_net_left_open_by_wiring_not_yet_done_is_the_wiring_steps_news() -> None:
    """Right after Place on the Board every net is open. That turned Check red with an
    error per net and sent Next to the findings rather than to Autoroute -- on a board the
    application had just laid out itself. A short is wrong whatever is left to wire."""
    placed = dataclasses.replace(
        EMPTY, parts_on_board=8, nets=7, unrouted=14, lvs_problems=7, drc_warnings=21
    )
    steps = statuses(placed)
    assert steps["check"] == "todo"
    assert next_step(workflow_steps(placed)) == "route"
    check = next(step for step in workflow_steps(placed) if step.key == "check")
    assert check.summary == "0 error(s) · 21 warning(s)"

    shorted = dataclasses.replace(placed, lvs_problems=8, lvs_shorts=1)
    assert statuses(shorted)["check"] == "problem"
    assert next_step(workflow_steps(shorted)) == "check"


def test_a_stripboards_shorts_wait_for_its_cuts() -> None:
    """Its strips join every net along them until the wiring cuts them, so before then a
    short is what Autoroute is for -- not a red Verify and a Next that goes to findings."""
    uncut = dataclasses.replace(
        EMPTY, parts_on_board=8, nets=7, unrouted=6, lvs_problems=11, lvs_shorts=5,
        shorts_wait_for_wiring=True,
    )
    assert statuses(uncut)["check"] == "todo"
    assert next_step(workflow_steps(uncut)) == "route"
    cut = dataclasses.replace(uncut, unrouted=0, lvs_problems=1, lvs_shorts=1)
    assert statuses(cut)["check"] == "problem"


def test_nothing_on_the_board_is_nothing_to_check() -> None:
    """LVS reports every net as unplaced before anything is placed. That is the placement
    step's news, and reporting it again as a check failure would put the warning colour on
    a board nobody has started."""
    facts = dataclasses.replace(EMPTY, parts_off_board=8, nets=7, lvs_problems=7)
    assert statuses(facts)["check"] == "todo"


def test_a_circuit_with_an_error_in_it_is_not_drawn_yet() -> None:
    """ERC's errors are the circuit's own: a chip with no supply is wrong before a board is
    chosen, and choosing one would only build the mistake. So the circuit is a problem, the
    board is not the next step yet, and Next reads the findings."""
    facts = dataclasses.replace(EMPTY, parts_off_board=8, nets=7, erc_errors=2, erc_warnings=1)
    steps = statuses(facts)
    assert steps["circuit"] == "problem"
    assert steps["board"] == "todo"
    assert next_step(workflow_steps(facts)) == "circuit"
    circuit = workflow_steps(facts)[0]
    assert circuit.action == "See the Findings"
    assert circuit.summary == "8 part(s) · 2 error(s)"


def test_a_circuit_error_comes_before_a_board_error() -> None:
    facts = dataclasses.replace(EMPTY, parts_on_board=8, nets=7, drc_errors=1, erc_errors=1)
    assert statuses(facts)["check"] == "problem"
    assert next_step(workflow_steps(facts)) == "circuit"


def test_circuit_warnings_do_not_hold_anything_back() -> None:
    """A part joined to nothing or a net reaching one pin is worth reading and not worth
    stopping for -- the same line DRC's warnings draw."""
    facts = dataclasses.replace(EMPTY, parts_off_board=8, nets=7, erc_warnings=3)
    assert statuses(facts)["circuit"] == "done"
    assert next_step(workflow_steps(facts)) == "board"


def test_after_the_guide_the_button_saves_the_board_then_moves_it_on() -> None:
    """"Open the Build Guide" was the next step for ever, and pressed with the guide open it
    raised the guide it was looking at. Once the guide is in front there is one more thing
    to do: save a board that has no file, take a checked breadboard on to perfboard, or take
    the guide to the bench."""
    from perfboard_studio.ui.workflow import build_action

    ready = dataclasses.replace(EMPTY, parts_on_board=8, nets=7)
    assert build_action(ready) == "open-guide"
    showing = dataclasses.replace(ready, guide_showing=True)
    assert build_action(dataclasses.replace(showing, untitled=True)) == "save"
    assert build_action(dataclasses.replace(showing, untitled=True, solderless_breadboard=True)) == "save"
    assert build_action(dataclasses.replace(showing, solderless_breadboard=True)) == "to-perfboard"
    assert build_action(showing) == "export-guide"

    def label(facts: WorkflowFacts) -> str:
        return next(step.action for step in workflow_steps(facts) if step.key == "build")

    assert label(ready) == "Open the Build Guide"
    assert label(dataclasses.replace(showing, untitled=True)) == "Save the Board…"
    assert label(dataclasses.replace(showing, solderless_breadboard=True)) == "Take It to Perfboard…"
    assert label(showing) == "Export the Guide…"



def test_pins_nothing_is_wired_to_yet_are_the_wirings_news() -> None:
    """A board just placed has every pin of every net touching nothing, and DRC says so pin
    by pin: seventeen warnings under Verify on a six-part board before any wiring existed.
    Until the wiring is done they are its news; after it, a pin still touching nothing is a
    warning like any other."""
    placed = dataclasses.replace(
        EMPTY, parts_on_board=6, nets=6, unrouted=11, drc_warnings=17, drc_unwired=17
    )
    check = next(step for step in workflow_steps(placed) if step.key == "check")
    assert check.summary == "0 error(s) · 0 warning(s)"
    assert check.status == "todo"

    routed = dataclasses.replace(placed, unrouted=0, drc_warnings=3, drc_unwired=2)
    check = next(step for step in workflow_steps(routed) if step.key == "check")
    assert check.summary == "0 error(s) · 3 warning(s)"
