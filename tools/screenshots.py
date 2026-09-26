"""Regenerate the screenshots the README embeds.

    python tools/screenshots.py

Writes into ``docs/images/``, which is committed -- a README on GitHub cannot reach a
file that is only in ``headless_out/``.

This exists as a script rather than as a folder of hand-grabbed PNGs because the last
set went stale without anybody noticing: they were taken before parts were drawn as
their real bodies, so the project's front page advertised a rendering bug for as long as
they sat there. A screenshot that can be regenerated in one command is a screenshot that
gets regenerated.

The two editor shots drive the real ``MainWindow`` -- the same window a user gets --
rather than re-rendering the scene the way ``--headless`` does. The point of those
particular pictures is the application around the board: the nets panel, the toolbar,
the DRC/LVS dock and the status bar all carry information that a bare board render does
not, and a README's job is to show what the thing looks like to use.

The 3D shot goes through ``view3d.render_offscreen`` instead of grabbing the 3D dock.
Grabbing the dock does not work and quietly produces a black rectangle: the panel builds
its widget from a visibility signal and VTK renders into it on some later trip through
the event loop, so a grab taken from the same script always wins the race. Offscreen is
also the path the build guide's step images take, so this picture is a real product of
the shipping code rather than a special case.

The window is shown briefly on a real display, which is unavoidable: Qt's offscreen
plugin has no font database on Windows (see ``_default_headless_platform`` in
ui/main.py), so an offscreen grab would come back with every label as a missing-glyph
box.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from perfboard_studio import persist  # noqa: E402
from perfboard_studio.footprints import footprint_lookup  # noqa: E402
from perfboard_studio.placer import PlacementOptions, plan_placement  # noqa: E402
from perfboard_studio.ui import view3d  # noqa: E402
from perfboard_studio.ui.main import MainWindow  # noqa: E402

#: The NE555 astable, which is also what ``examples/ne555-astable.net`` imports to. A
#: recognisable circuit beats a denser but meaningless one: a reader who knows the 555
#: can check the picture against what they expect, which is the whole point of a
#: screenshot on a landing page.
FIXTURE = REPO_ROOT / "tools" / "diffcheck" / "golden" / "ne555.perf"

OUT_DIR = REPO_ROOT / "docs" / "images"


def _settle(app: QApplication, rounds: int = 12) -> None:
    """Let Qt finish laying out and painting before grabbing.

    A single ``processEvents`` is not enough: fitting the view and re-rendering the pad
    grid both land on later trips through the loop. And a count of trips is not enough
    either, because some of it is on TIMERS: the window pins its opening dock sizes a turn
    after showing (``_apply_default_sizes``), and until that fires Qt still has a second
    Board/Schematic tab bar from the arranging lying across the left-hand panels -- which a
    grab taken sooner put in the picture. So the loop is also run for long enough for them.

    And the pending deletes are run by hand: Qt drops that stray tab bar with
    ``deleteLater``, which only happens when control returns to a running event loop --
    so in the application it is gone at once, and under ``processEvents`` alone it never
    goes at all.
    """
    import time

    from PySide6.QtCore import QEvent

    deadline = time.monotonic() + 0.6
    count = 0
    while count < rounds or time.monotonic() < deadline:
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.01)
        count += 1


def _fresh_settings() -> None:
    """A settings store of the script's own, as the test suite uses.

    The window restores its layout from the user's settings and writes it back on close, so
    the pictures used to be of whatever this machine's layout happened to be -- docks tabbed,
    panels resized -- and taking them switched the user's ratsnest off. A first run's layout
    in a throwaway file is the one a reader of the README gets.
    """
    import tempfile

    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import main as main_module

    store = QSettings(
        str(Path(tempfile.mkdtemp()) / "screenshots.ini"), QSettings.Format.IniFormat
    )
    main_module.app_settings = lambda: store  # type: ignore[assignment]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    _fresh_settings()

    result = persist.deserialize_document(FIXTURE.read_text(encoding="utf-8"))
    if not result.ok:
        print(f"LOAD FAILED [{result.code}] {result.message}")
        return 1

    window = MainWindow(result.document, FIXTURE)
    window.resize(1600, 1000)
    window.show()
    _settle(app)

    # Auto-place, then route -- the order the README documents, so the picture is of the
    # workflow it describes rather than of a fixture. The golden document's placement is
    # spread over a mostly empty board, which routes into long insulated wires and shows
    # the tool at its least flattering for a reason that has nothing to do with the tool.
    #
    # The planner and the bus are driven directly rather than through on_autoplace(),
    # which asks for confirmation first -- correct for a person, a deadlock for a script.
    # This is the path its accept button takes.
    plan = plan_placement(window.bus.document, window.lookup, PlacementOptions(seed=0))
    if not plan.is_empty:
        moved = window.bus.dispatch("component.moveMany", plan.payload())
        if not moved.ok:
            print(f"PLACEMENT REFUSED [{moved.code}] {moved.message}")
            return 1
    _settle(app)

    # An unrouted board is a picture of a to-do list. This is the same call the toolbar
    # button makes, so the copper in the picture is what the shipped router produces.
    window.on_autoroute_all()
    _settle(app)

    # Ratsnest off. It is on by default in the app and should be, but every net here is
    # routed, and leaving the unrouted-connection overlay switched on in a picture of a
    # finished board buries the copper -- which is the one thing these images exist to
    # show -- under the guides that were there to help lay it.
    window.act_ratsnest.setChecked(False)
    _settle(app)
    window.view.fit_board()
    _settle(app)

    shots: list[tuple[str, str]] = []

    window.grab().save(str(OUT_DIR / "editor-component-side.png"))
    shots.append(("editor-component-side.png", "2D editor, component side, routed"))

    # The solder side, where the copper actually is -- and where the far-side hatching
    # earns its place, since the parts are now the things on the other face.
    window.on_flip_board()
    _settle(app)
    window.view.fit_board()
    _settle(app)
    window.grab().save(str(OUT_DIR / "editor-solder-side.png"))
    shots.append(("editor-solder-side.png", "2D editor, solder side"))

    # The same circuit as a sheet, in the panel that draws one: a 555 is a sheet a reader
    # can check by eye, which is the point of it being the example.
    window.show_schematic()
    _settle(app)
    window.schematic_view.fit()
    _settle(app)
    window.grab().save(str(OUT_DIR / "schematic.png"))
    shots.append(("schematic.png", "the schematic panel"))
    window.show_board()
    _settle(app)

    document = window.bus.document
    # Placed and routed here, saved nowhere: the window is a picture. Without this the close
    # stops on "unsaved changes?" and waits for a click nobody is there to make.
    window._mark_saved()
    window.close()
    _settle(app)

    # 3D offscreen, not a grab of the dock -- see this module's docstring.
    lookup = footprint_lookup()
    view3d.render_offscreen(document, lookup, str(OUT_DIR / "board-3d.png"), width=1400, height=950)
    shots.append(("board-3d.png", "3D view, component side"))

    if not _nano_relay_shots(app, shots):
        return 1

    for name, what in shots:
        size = (OUT_DIR / name).stat().st_size
        print(f"{name:32} {size // 1024:5} KB   {what}")
    return 0


#: The example that is a real part list rather than a textbook circuit: an Arduino Nano on
#: header strips, a BC547 and a 7805 out of the catalog, terminals with their pins named,
#: labels written on the board -- and every one of them read out of a KiCad netlist.
NANO_RELAY = REPO_ROOT / "examples" / "nano-relay.perf"

#: What the close-ups frame: the module and the power stage beside it, which is where the
#: pin names, the catalog's parts and a label all are.
CLOSE_UP_REFS = ("A1", "U1", "Q1", "R1", "C1", "C2", "C3", "J1", "SW1", "D2")


def _nano_relay_shots(app: QApplication, shots: list[tuple[str, str]]) -> bool:
    result = persist.deserialize_document(NANO_RELAY.read_text(encoding="utf-8"))
    if not result.ok:
        print(f"LOAD FAILED [{result.code}] {result.message}")
        return False
    document = result.document
    board = document.board
    lookup = footprint_lookup()

    window = MainWindow(document, NANO_RELAY)
    window.resize(1600, 1000)
    window.show()
    _settle(app)
    window.act_ratsnest.setChecked(False)
    _settle(app)

    # Framed on the parts rather than the whole 9 x 15 cm board, which is mostly holes: the
    # picture is of the names printed beside the pins and the parts the catalog placed.
    from PySide6.QtCore import Qt

    from perfboard_studio.drc import placed_body_box

    boxes = [
        placed_body_box(comp, lookup(comp.footprint_id), board)  # type: ignore[arg-type]
        for comp in document.components
        if comp.ref in CLOSE_UP_REFS and lookup(comp.footprint_id) is not None
    ]
    from PySide6.QtCore import QRectF

    left = min(b[0] for b in boxes) - 6.0
    right = max(b[1] for b in boxes) + 6.0
    top = min(b[2] for b in boxes) - 4.0
    bottom = max(b[3] for b in boxes) + 4.0
    window.view.fitInView(QRectF(left, top, right - left, bottom - top), Qt.AspectRatioMode.KeepAspectRatio)
    _settle(app)
    window.grab().save(str(OUT_DIR / "catalog-and-pin-names.png"))
    shots.append(("catalog-and-pin-names.png", "catalog parts, a module, pin names, labels"))

    window._mark_saved()
    window.close()
    _settle(app)

    # 3D, closer in than the whole-board shot, on the module standing on its headers.
    ren, _stats = view3d.build_renderer(document, lookup)
    cam = ren.GetActiveCamera()
    fx, fy, fz = cam.GetFocalPoint()
    px, py, pz = cam.GetPosition()
    cx = (left + right) / 2
    cy = -(top + bottom) / 2  # rows run down the board, the world's y runs up
    scale = 0.5
    cam.SetFocalPoint(cx, cy, 4.0)
    cam.SetPosition(cx + (px - fx) * scale, cy + (py - fy) * scale, 4.0 + (pz - fz) * scale)
    ren.ResetCameraClippingRange()
    win = view3d.vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(1400, 950)
    win.Render()
    grab = view3d.vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    writer = view3d.vtk.vtkPNGWriter()
    writer.SetFileName(str(OUT_DIR / "module-3d.png"))
    writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()
    shots.append(("module-3d.png", "3D close-up: a module on its headers"))
    return True


if __name__ == "__main__":
    raise SystemExit(main())
