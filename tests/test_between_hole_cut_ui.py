import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from perfboard_studio.command import CommandBus, CommandContext
from perfboard_studio.commands import create_document_id_generator, create_standard_registry
from perfboard_studio.model import Board, DocumentMeta, HoleCoord, PerfDocument
from perfboard_studio.ui.view2d import BoardScene, hole_to_screen


@pytest.mark.parametrize("axis,side", [
    ("horizontal", "top"), ("horizontal", "bottom"),
    ("vertical", "top"), ("vertical", "bottom"),
])
def test_click_between_holes_toggles_a_cut(axis, side):
    app = QApplication.instance() or QApplication([])
    board = Board(type="stripboard", cols=5, rows=5, pitch=2.54, thickness=1.6,
                  material="FR2", pad_diameter=1.9, drill_diameter=1.0, strip_axis=axis)
    doc = PerfDocument(meta=DocumentMeta(name="test", created="2026-01-01T00:00:00Z",
                                         modified="2026-01-01T00:00:00Z"), board=board)
    bus = CommandBus(doc, create_standard_registry(),
                     CommandContext(next_id=create_document_id_generator(doc)))
    scene = BoardScene(doc, lambda _name: None, side=side, bus=bus)
    scene.arm_cutting(True)
    first = HoleCoord(1, 2)
    second = HoleCoord(2, 2) if axis == "horizontal" else HoleCoord(1, 3)
    point = (hole_to_screen(first, board, side) + hole_to_screen(second, board, side)) / 2

    class Event:
        def scenePos(self):
            return point

        def button(self):
            return Qt.MouseButton.LeftButton

        def accept(self):
            pass

    scene.mousePressEvent(Event())
    assert len(bus.document.cuts) == 1
    assert {bus.document.cuts[0].at, bus.document.cuts[0].to} == {first, second}
    scene.set_document(bus.document)
    scene.mousePressEvent(Event())
    assert not bus.document.cuts
    assert app is not None


def test_spotlight_accepts_a_hole():
    app = QApplication.instance() or QApplication([])
    board = Board(type="stripboard", cols=5, rows=5, pitch=2.54, thickness=1.6,
                  material="FR2", pad_diameter=1.9, drill_diameter=1.0, strip_axis="horizontal")
    doc = PerfDocument(meta=DocumentMeta(name="test", created="2026-01-01T00:00:00Z",
                                         modified="2026-01-01T00:00:00Z"), board=board)
    scene = BoardScene(doc, lambda _name: None)
    scene.set_problem_focus((HoleCoord(1, 1),), (), ())
    assert scene._focus_item is not None
    scene.set_problem_focus((), (), ())
    assert scene._focus_item is None
    assert app is not None
