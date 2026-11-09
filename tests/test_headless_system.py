"""The headless run on a document of several boards, and on one of a single board.

What is pinned: several boards are listed with their cables, the system's ERC, LVS and
schematic are said once and called the system's, and every board then gets the board's run
-- its own 1:1 PDF, STEP, guide and DRC -- the first in ``headless_out/`` and the others in
``headless_out/<board id>/``, each guide ending with the system's harness; and a document of
one board prints the sections it always printed, in the same order, with nothing added.

3D is switched off here (``offscreen_gl_available``): the run guards itself and skips it on
a machine with no GL, and what is pinned is which outputs go where, not the pictures.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from perfboard_studio import persist
from perfboard_studio.model import ExtraBoard, LeadBendConductor, PerfDocument
from perfboard_studio.ui import headless as headless_module
from perfboard_studio.ui import view3d

REPO = Path(__file__).resolve().parents[1]

#: The first word of every line the run printed for examples/ne555-astable.perf before it
#: knew about boards (0.24.0.dev0, c3591b4), the 3D section's skipped. A section added,
#: dropped or moved for a single board shows here.
ONE_BOARD_SECTIONS = [
    "Perfboard", "document", "board", "substrate", "parts", "2D", "pads", "1:1", "PDF", "PDF",
    "schematic", "schematic.svg,", "STEP", "ERC", "DRC", "LVS", "ratsnest", "autoroute", "0",
    "would", "style", "balanced", "*", "solder", "wire", "lead-bend", "auto-place",
    "Placement", "HPWL", "build", "8", "step", "!", "3D", "outputs",
]


def _example(name: str) -> PerfDocument:
    return persist.parse_document_or_throw((REPO / "examples" / f"{name}.perf").read_text(encoding="utf-8"))


def _two_boards() -> PerfDocument:
    """ne555-astable with nano-relay as a second board, its ids prefixed, and no cable yet."""
    first, second = _example("ne555-astable"), _example("nano-relay")

    def conductor(c):  # type: ignore[no-untyped-def]
        changed = dataclasses.replace(c, id=f"b2-{c.id}")
        if isinstance(c, LeadBendConductor):
            changed = dataclasses.replace(changed, component_id=f"b2-{c.component_id}")
        return changed

    extra = ExtraBoard(
        id="b2",
        name="Controller",
        board=second.board,
        components=tuple(
            dataclasses.replace(c, id=f"b2-{c.id}", ref=f"B{c.ref}") for c in second.components
        ),
        conductors=tuple(conductor(c) for c in second.conductors),
    )
    return dataclasses.replace(first, boards=(extra,))


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, doc: PerfDocument) -> tuple[int, Path]:
    """The headless run on ``doc`` from ``tmp_path``: its exit code and its output folder."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(view3d, "offscreen_gl_available", lambda: False)
    path = tmp_path / "board.perf"
    path.write_text(persist.serialize_document(doc), encoding="utf-8")
    return headless_module.headless([str(path)]), tmp_path / "headless_out"


def test_one_board_prints_what_it_always_printed(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    code, out = _run(tmp_path, monkeypatch, _example("ne555-astable"))
    printed = capsys.readouterr().out
    assert code == 0
    sections = [line.split()[0] for line in printed.splitlines() if line.strip()]
    assert sections == ONE_BOARD_SECTIONS
    assert "boards " not in printed and "===" not in printed and "the system's" not in printed
    assert not [p for p in out.iterdir() if p.is_dir()], "a single board writes no board folder"


def test_several_boards_are_listed_checked_once_and_run_one_at_a_time(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    code, out = _run(tmp_path, monkeypatch, _two_boards())
    printed = capsys.readouterr().out
    assert code == 0
    lines = printed.splitlines()
    assert any(line.startswith("boards       2   cables 0") for line in lines)
    assert any("Controller (b2): " in line and str(out / "b2") in line for line in lines)

    # The circuit's checks once, before any board, and called the system's.
    system_at = next(i for i, line in enumerate(lines) if line.startswith("the system's"))
    first_board_at = next(i for i, line in enumerate(lines) if line.startswith("=== "))
    assert system_at < first_board_at
    for label in ("schematic", "ERC", "LVS"):
        found = [i for i, line in enumerate(lines) if line.startswith(f"{label} ")]
        assert len(found) == 1 and system_at < found[0] < first_board_at, label

    # Then each board, the board's run in its own folder.
    headings = [line for line in lines if line.startswith("=== ")]
    assert len(headings) == 2 and "(main)" in headings[0] and "Controller (b2)" in headings[1]
    assert sum(line.startswith("DRC ") for line in lines) == 2
    for folder in (out, out / "b2"):
        for name in ("board_1to1_component_side.pdf", "board.step", "guide.html", "guide.json", "out_2d.png"):
            assert (folder / name).is_file(), folder / name
    assert (out / "schematic.svg").is_file() and not (out / "b2" / "schematic.svg").exists()
    # Each board's bill of materials is its own parts.
    controller = {f"B{c.ref}" for c in _example("nano-relay").components}
    first = (out / "bom.csv").read_text(encoding="utf-8")
    second = (out / "b2" / "bom.csv").read_text(encoding="utf-8")
    assert all(ref in second for ref in controller)
    assert not any(ref in first for ref in controller)


def persist_json(path: Path) -> dict[str, object]:
    import json

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_each_boards_guide_ends_with_the_systems_harness(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.model import Cable, CableEnd, CableWire

    doc = _two_boards()
    j1 = next(c for c in doc.components if c.ref == "J1")
    other = doc.boards[0].components[0]
    cable = Cable(
        id="cable-1", ref="W1", a=CableEnd("main", j1.id), b=CableEnd("b2", other.id),
        wires=(CableWire("1", "1"),),
    )
    code, out = _run(tmp_path, monkeypatch, dataclasses.replace(doc, cables=(cable,)))
    printed = capsys.readouterr().out
    assert code == 0
    assert f"cable        W1: Board 1 J1 -> Controller {other.ref}, 1 wire(s), cut to fit" in printed
    for folder in (out, out / "b2"):
        assert persist_json(folder / "guide.json").get("harness"), folder
