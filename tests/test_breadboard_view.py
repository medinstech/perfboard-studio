"""A breadboard in the window: drawn as plastic with holes and print, and chosen by size."""

from __future__ import annotations

import dataclasses
import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from perfboard_studio.breadboard import SIZES, breadboard, missing_holes, pattern_board
from perfboard_studio.commands import DEFAULT_BOARD
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.model import DocumentMeta, PerfDocument

LOOKUP = footprint_lookup()


def _app() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _scene(size: str, side: str = "top"):  # type: ignore[no-untyped-def]
    from perfboard_studio.ui.view2d import BoardScene

    doc = PerfDocument(meta=DocumentMeta(name="t", created="", modified=""), board=breadboard(size))
    return BoardScene(doc, LOOKUP, side=side, show_rulers=True)  # type: ignore[arg-type]


def _paint(scene) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtGui import QImage, QPainter

    image = QImage(800, 300, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    scene.render(painter)
    painter.end()


def test_a_breadboard_is_drawn_as_plastic_with_every_hole_and_no_copper() -> None:
    """No pads, no strips, no legend: its own item, which draws exactly the holes the board
    is sold with -- the pattern, not the grid."""
    _app()
    from perfboard_studio.ui.view2d import BoardLegendItem, HoleRulerItem, StripGridItem

    for size in SIZES:
        scene = _scene(size)
        assert scene.pad_grid is None and scene.breadboard_item is not None
        assert not any(isinstance(i, (BoardLegendItem, HoleRulerItem, StripGridItem)) for i in scene.items())
        _paint(scene)
        board = breadboard(size)
        assert scene.breadboard_item.drawn == board.cols * board.rows - len(missing_holes(board)) == int(size)


def test_the_board_names_its_own_holes_so_no_ruler_is_drawn_over_them() -> None:
    """It prints e12 on its face; a grid ruler of A, B, C beside that would name the holes
    a second way. From underneath there is no print, and the ruler is wanted again."""
    _app()
    assert _scene("830").legend_is_readable()
    assert not _scene("830", side="bottom").legend_is_readable()


def test_board_setup_asks_a_breadboard_only_its_size() -> None:
    _app()
    from perfboard_studio.ui.main import BoardSetupDialog

    dialog = BoardSetupDialog(DEFAULT_BOARD)
    dialog.board_type.setCurrentIndex(dialog.board_type.findData("breadboard"))
    dialog.breadboard_size.setCurrentIndex(dialog.breadboard_size.findData("400"))
    assert dialog.board() == breadboard("400")
    # A different product: the perfboard's fingers and bores go with it.
    assert dialog.preset_features() == ((), ())
    form = dialog._chosen
    assert form.isRowVisible(dialog.breadboard_size)
    assert not form.isRowVisible(dialog.preset)
    assert not dialog.advanced_toggle.isVisibleTo(dialog)

    dialog.board_type.setCurrentIndex(dialog.board_type.findData("pad-per-hole"))
    assert not form.isRowVisible(dialog.breadboard_size)
    assert form.isRowVisible(dialog.preset)


def test_board_setup_opens_on_the_breadboard_it_was_given() -> None:
    _app()
    from perfboard_studio.ui.main import BoardSetupDialog

    dialog = BoardSetupDialog(breadboard("170"))
    assert dialog.board_type.currentData() == "breadboard"
    assert dialog.breadboard_size.currentData() == "170"
    assert dialog.board() == breadboard("170")
    # Another size of the same board is only a size.
    dialog.breadboard_size.setCurrentIndex(dialog.breadboard_size.findData("830"))
    assert dialog.preset_features() is None


def test_a_new_document_can_be_made_a_breadboard_in_board_setup(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The starter board comes with corner bores and finger strips, which neither kind of
    breadboard takes -- so choosing one was refused with "remove them first", about
    features nobody had added. They go with the board they belonged to, in one undo step."""
    _app()
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialog

    from perfboard_studio.breadboard import solderable_breadboard
    from perfboard_studio.commands import create_starter_document
    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    for kind, expected in (
        ("breadboard", breadboard("400")),
        ("solderable-breadboard", solderable_breadboard("400")),
    ):
        starter = create_starter_document(DocumentMeta(name="t", created="", modified=""))
        assert starter.mounting_holes and starter.edge_connectors
        window = main_module.MainWindow(starter)

        def choose(dialog, _kind=kind) -> QDialog.DialogCode:  # type: ignore[no-untyped-def]
            dialog.board_type.setCurrentIndex(dialog.board_type.findData(_kind))
            dialog.breadboard_size.setCurrentIndex(dialog.breadboard_size.findData("400"))
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(main_module.BoardSetupDialog, "exec", choose)
        try:
            assert window.on_board_setup()
            document = window.bus.document
            assert document.board == expected
            assert document.mounting_holes == () and document.edge_connectors == ()
            assert "400-point" in window.bus.history()[-1]
            window.on_undo()
            assert window.bus.document.board == starter.board
            assert window.bus.document.mounting_holes == starter.mounting_holes
        finally:
            window._saved_document = window.bus.document
            window.close()



@pytest.fixture
def window(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """A window on an empty breadboard, its settings kept out of the real store."""
    _app()
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    doc = PerfDocument(meta=DocumentMeta(name="t", created="", modified=""), board=breadboard("830"))
    made = main_module.MainWindow(doc)
    yield made
    made._saved_document = made.bus.document
    made.close()


def test_a_breadboard_offers_only_the_copper_it_can_take(window) -> None:  # type: ignore[no-untyped-def]
    """Solder, and bare wire on the solder side, are greyed out on a breadboard -- and come
    back the moment the board is changed to one that can take them."""
    from perfboard_studio.commands import SetBoardPayload

    enabled = {kind: action.isEnabled() for kind, action in window.act_draw.items()}
    assert enabled == {
        "solder-trace": False,
        "solder-trace-wired": False,
        "bare-wire": False,
        "insulated-wire": True,
        "top-jumper": True,
    }
    assert window.bus.dispatch("board.set", SetBoardPayload(board=DEFAULT_BOARD)).ok
    assert all(action.isEnabled() for action in window.act_draw.values())


def test_the_window_rewires_a_breadboard_with_jumpers_and_greys_the_perfboard_settings(
    tmp_path, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    """Re-route Everything went to the perfboard router -- solder traces and bare wire on a
    breadboard -- and the router's style and crossing settings said "applies to the next
    route" on a board whose planner reads neither. The grid setting stays: it shapes a
    breadboard's jumpers, and only a stripboard's links ignore it."""
    _app()
    from PySide6.QtCore import QSettings

    from perfboard_studio.breadroute import plan_joined_board
    from perfboard_studio.commands import (
        DeleteConductorsPayload,
        MoveComponentPayload,
        SetBoardPayload,
    )
    from perfboard_studio.drc import run_drc
    from perfboard_studio.ui import main as main_module

    from .test_breadroute import TIMER, _apply

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    monkeypatch.setattr(main_module.MainWindow, "_confirm", lambda self, *a: True)
    wired = _apply(TIMER, plan_joined_board(TIMER, LOOKUP).payload())
    window = main_module.MainWindow(wired)
    try:
        assert not window.style_menu.menuAction().isEnabled()
        assert not window.crossing_menu.menuAction().isEnabled()
        assert window.act_grid_wires.isEnabled()
        moved =next(c for c in window.bus.document.components if c.ref == "R2")
        anchor = dataclasses.replace(moved.anchor, col=30)
        assert window.bus.dispatch(
            "component.move", MoveComponentPayload(id=moved.id, anchor=anchor)
        ).ok
        before = {c.id for c in window.bus.document.conductors}
        window.on_reroute(None)
        after = window.bus.document.conductors
        assert {c.kind for c in after} == {"top-jumper"}
        assert not before & {c.id for c in after}
        assert not [
            v for v in run_drc(window.bus.document, LOOKUP) if v.severity == "error"
        ]

        # A grid jumper turns its corners where it is drawn, in no hole.
        assert any(len(c.path) > 2 for c in after) == window._grid_wires

        # On a stripboard the grid setting goes too: its links run across the strips.
        window.bus.dispatch("conductor.deleteMany", DeleteConductorsPayload(
            ids=tuple(c.id for c in after)
        ))
        strips = dataclasses.replace(DEFAULT_BOARD, type="stripboard", strip_axis="horizontal")
        assert window.bus.dispatch("board.set", SetBoardPayload(board=strips)).ok
        assert not window.act_grid_wires.isEnabled()
        after = window.bus.document.conductors

        # Back on a perfboard the settings are the router's again.
        window.bus.dispatch("conductor.deleteMany", DeleteConductorsPayload(
            ids=tuple(c.id for c in after)
        ))
        assert window.bus.dispatch("board.set", SetBoardPayload(board=DEFAULT_BOARD)).ok
        assert window.style_menu.menuAction().isEnabled() and window.act_grid_wires.isEnabled()
    finally:
        window._saved_document = window.bus.document
        window.close()


def test_a_breadboards_1_to_1_pdf_is_its_top_alone(window, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Under a solderless breadboard is its adhesive backing: there is no solder side to
    print, and the export wrote a second sheet of one anyway."""
    from perfboard_studio.ui import main as main_module

    target = tmp_path / "bb_component_side.pdf"
    monkeypatch.setattr(main_module.MainWindow, "_ask_where_to_export", lambda self, *a: target)
    opened: list[list[pathlib.Path]] = []
    monkeypatch.setattr(main_module.MainWindow, "_offer_to_open", lambda self, written, **k: opened.append(written))
    window.on_export_pdf()
    assert [p.name for p in opened[0]] == ["bb_component_side.pdf"]
    assert sorted(p.name for p in tmp_path.glob("*.pdf")) == ["bb_component_side.pdf"]


@pytest.mark.parametrize(
    ("board", "sheets"),
    [
        (breadboard("830"), ["board_component_side.pdf"]),
        (pattern_board("solderable-breadboard", 63, 20), ["board_component_side.pdf", "board_solder_side.pdf"]),
    ],
    ids=["solderless", "solderable"],
)
def test_an_agents_1_to_1_pdf_has_a_solder_side_only_where_there_is_one(board, sheets, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """MCP's export_pdf decides as the window does: a solderless breadboard is its top
    alone, and a solderable one, which IS soldered, keeps both sheets."""
    _app()
    from perfboard_studio.mcp.session import BoardSession

    doc = PerfDocument(meta=DocumentMeta(name="t", created="", modified=""), board=board)
    result = BoardSession(document=doc).export_pdf(str(tmp_path))
    assert result["ok"], result
    assert [pathlib.Path(p).name for p in result["written"]] == sheets
    assert sorted(p.name for p in tmp_path.glob("*.pdf")) == sheets


def test_no_stock_perfboard_is_offered_for_a_breadboard() -> None:
    """A perfboard's size applied to a breadboard is a board board.set refuses, so the
    window's Board step goes to Board Setup -- the breadboard's sizes -- instead."""
    from perfboard_studio.placer import suggest_boards

    assert suggest_boards(breadboard("830"), (), (), LOOKUP) == ()
    assert suggest_boards(DEFAULT_BOARD, (), (), LOOKUP) != ()


def test_a_jumper_drawn_on_a_breadboard_goes_in_from_above(window) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.breadboard import parse_hole_name
    from perfboard_studio.drc import run_drc

    scene = window.scene
    scene.arm_drawing("top-jumper")
    a, b = (parse_hole_name(window.bus.document.board, name) for name in ("a5", "a9"))
    assert a is not None and b is not None
    scene.draw_click(a)
    result = scene.draw_click(b)  # a wire is two clicks, and the second commits it
    assert result is not None and result.ok, result
    conductor = window.bus.document.conductors[0]
    assert conductor.side == "top"
    assert not [v for v in run_drc(window.bus.document, LOOKUP) if v.rule == "not-on-breadboard"]


# ---------------------------------------------------------------------------
# In 3D
# ---------------------------------------------------------------------------


def _timer_on_breadboard() -> PerfDocument:
    from perfboard_studio.model import ComponentInstance, HoleCoord

    u1 = ComponentInstance(
        id="u1", ref="U1", value="NE555", footprint_id="dip-8", anchor=HoleCoord(10, 11),
        rotation=270, mirrored=False, locked=False,
    )
    return PerfDocument(
        meta=DocumentMeta(name="t", created="", modified=""), board=breadboard("830"), components=(u1,)
    )


def test_in_3d_a_breadboard_has_an_opening_at_every_hole_and_nowhere_else() -> None:
    """Real openings, one per hole of the pattern, and a solid tile at every grid position
    the pattern has none -- the channel, the strips beside the rails."""
    from perfboard_studio.ui import view3d

    board = breadboard("830")
    doc = PerfDocument(meta=DocumentMeta(name="t", created="", modified=""), board=board)
    glyphed = [
        actor.GetMapper().GetInput().GetNumberOfPoints()
        for actor in view3d.build_breadboard(doc)
        if actor.GetMapper().IsA("vtkGlyph3DMapper")
    ]
    holes = board.cols * board.rows - len(missing_holes(board))
    # The holed tiles and the wells behind them share the holes; the solid tiles take the rest.
    assert sorted(glyphed) == sorted([holes, holes, len(missing_holes(board))])


def test_in_3d_a_breadboard_carries_no_copper_and_no_solder(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """No substrate, pads, bores, legend or fillets: what a perfboard's 3D board is made of,
    built on a breadboard, is what the first render showed -- green FR-4 with a hole at
    every grid position and solder under it. None of those builders is asked."""
    import vtk

    from perfboard_studio.ui import view3d

    def refused(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("a copper board's builder was asked to draw a breadboard")

    for name in ("build_substrate", "build_strips", "build_pads", "build_drills", "build_legend", "build_joints"):
        monkeypatch.setattr(view3d, name, refused)
    renderer = vtk.vtkRenderer()
    view3d.populate_renderer(renderer, _timer_on_breadboard(), LOOKUP)
    assert renderer.GetActors().GetNumberOfItems() > 0


def test_in_3d_a_lead_stops_in_its_clip() -> None:
    """Pushed into the plastic and held there, not through it: nothing comes out of the
    underside of a breadboard to be trimmed."""
    from perfboard_studio.ui import view3d

    doc = _timer_on_breadboard()
    body = view3d._world_body(LOOKUP, doc.components[0], doc.board)
    assert body is not None
    assert -doc.board.thickness < body.lead_bottom_z < 0
    perfboard = view3d._world_body(LOOKUP, doc.components[0], DEFAULT_BOARD)
    assert perfboard is not None and perfboard.lead_bottom_z < -DEFAULT_BOARD.thickness
