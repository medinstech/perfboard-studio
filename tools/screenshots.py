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

The 3D shots go through ``view3d.render_offscreen`` instead of grabbing the 3D dock.
Grabbing the dock does not work and quietly produces a black rectangle: VTK draws into a
native window of its own, which ``QWidget.grab`` cannot see. Offscreen is also the path
the build guide's step images take, so this picture is a real product of the shipping
code rather than a special case. The one shot of the 3D panel IN the window
(``guide-and-3d.png``) grabs the window and then pastes in what the panel's own render
window holds, read back from VTK -- see ``_grab_with_3d``.

**Nothing is shown on screen.** The window runs on Qt's offscreen platform, pointed at the
system's fonts with ``QT_QPA_FONTDIR`` -- the offscreen plugin has no font database of its
own on Windows (see ``_default_headless_platform`` in ui/main.py), and without one every
label came back as a missing-glyph box, which is why this used to need a real display and a
desktop moment to take. ``QT_QPA_PLATFORM=windows`` puts the window on screen again.

The one thing offscreen cannot do is the 3D PANEL's own widget: QVTK asks the platform for a
native window with a GL pixel format, gets none, and the process ends. So the panel is given
``_OffscreenPanel`` instead -- the renderer the panel would hold, in VTK's own offscreen
render window -- and ``_grab_with_3d`` paints its frame where the panel is. It is the same
frame the readback of the on-screen panel pasted in; only where it is drawn changes.

**The scale is pinned, not taken from the monitor.** Every editor shot is the window at
``WINDOW_SIZE`` drawn at ``SCALE``, so 2000 x 1250 pixels on any machine. Taken from the
monitor, the same script made 2000-pixel pictures on a 125 % laptop and 1600-pixel ones
on a 100 % desktop, and ``tools/make_social_preview.py`` crops this set at fixed pixel
coordinates. And the size is FIXED rather than resized to: Windows clips a window to the
height of the screen it opens on, and at 125 % a 1080-line screen is 864 lines tall.
"""

from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

#: The window's size in the units the interface is laid out in, and how many pixels each
#: of those is drawn with. Set before Qt is imported, which is when it reads them: the
#: platform's own scaling is switched off so the monitor cannot multiply into ``SCALE``.
WINDOW_SIZE = (1600, 1000)
SCALE = "1.25"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = SCALE
# Offscreen unless asked otherwise -- see this module's docstring.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault(
        "QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
    )
OFFSCREEN = os.environ["QT_QPA_PLATFORM"] == "offscreen"

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

from perfboard_studio import persist  # noqa: E402
from perfboard_studio.breadboard import breadboard  # noqa: E402
from perfboard_studio.breadroute import plan_breadboard  # noqa: E402
from perfboard_studio.commands import design_on_a_new_board  # noqa: E402
from perfboard_studio.footprints import footprint_lookup  # noqa: E402
from perfboard_studio.placer import place_design  # noqa: E402
from perfboard_studio.ui import view3d  # noqa: E402
from perfboard_studio.ui.main import MainWindow  # noqa: E402

#: The NE555 astable example, opened as a reader opens it: placed, wired and saved on the
#: board it is built on. A recognisable circuit beats a denser but meaningless one: a
#: reader who knows the 555 can check the picture against what they expect, which is the
#: whole point of a screenshot on a landing page. It was the diffcheck fixture, placed and
#: routed by this script on a 32 x 22 board it filled a quarter of -- and the front page
#: said "diffcheck · Not saved" across the top.
FIXTURE = REPO_ROOT / "examples" / "ne555-astable.perf"

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


def _open(window: QMainWindow, app: QApplication) -> None:
    """Show the window at exactly ``WINDOW_SIZE`` -- fixed, see this module's docstring."""
    window.setFixedSize(*WINDOW_SIZE)
    window.show()
    _settle(app)


def _grab(window: QMainWindow, app: QApplication) -> QPixmap:
    """The window as a picture, with no text field holding the keyboard.

    The window opens with the Library's filter focused, and a focused field's caret blinks:
    of one run's three editor shots two had the caret and one had not, by where in the blink
    each grab landed, and all three had the field's focus ring. A field let go of looks the
    same in every grab, as it does to somebody working on the board.
    """
    from PySide6.QtWidgets import QLineEdit

    focused = app.focusWidget()
    if isinstance(focused, QLineEdit):
        focused.clearFocus()
        _settle(app, 3)
    return window.grab()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    _fresh_settings()
    if OFFSCREEN:
        MainWindow._create_3d_widget = _create_offscreen_3d  # type: ignore[method-assign]

    result = persist.deserialize_document(FIXTURE.read_text(encoding="utf-8"))
    if not result.ok:
        print(f"LOAD FAILED [{result.code}] {result.message}")
        return 1

    window = MainWindow(result.document, FIXTURE)
    _open(window, app)

    # Nothing is placed or wired here: the example is the board the shipped placer and
    # router left (tools/build_examples.py builds it), and nothing dispatched means the
    # title is the file's and nothing is unsaved.

    # Ratsnest off. It is on by default in the app and should be, but every net here is
    # routed, and leaving the unrouted-connection overlay switched on in a picture of a
    # finished board buries the copper -- which is the one thing these images exist to
    # show -- under the guides that were there to help lay it.
    window.act_ratsnest.setChecked(False)
    _settle(app)
    window.view.fit_board()
    _settle(app)

    shots: list[tuple[str, str]] = []

    _grab(window, app).save(str(OUT_DIR / "editor-component-side.png"))
    shots.append(("editor-component-side.png", "2D editor, component side, routed"))

    # The solder side, where the copper actually is -- and where the far-side hatching
    # earns its place, since the parts are now the things on the other face.
    window.on_flip_board()
    _settle(app)
    window.view.fit_board()
    _settle(app)
    _grab(window, app).save(str(OUT_DIR / "editor-solder-side.png"))
    shots.append(("editor-solder-side.png", "2D editor, solder side"))

    # The same circuit as a sheet, in the panel that draws one: a 555 is a sheet a reader
    # can check by eye, which is the point of it being the example. The sheet opens BESIDE
    # the board, so the board is turned back to the face the parts are on and fitted again
    # into the half it has left -- otherwise it keeps the zoom it had across the whole
    # window and goes off the edge of its panel.
    window.on_flip_board()
    window.show_schematic()
    _settle(app)
    window.view.fit_board()
    window.schematic_view.fit()
    _settle(app)
    _grab(window, app).save(str(OUT_DIR / "schematic.png"))
    shots.append(("schematic.png", "the schematic panel"))
    # The board back in front: the next window restores this one's layout from the same
    # settings. Not the sheet closed, as it was when the views stood side by side -- they
    # are tabs now, and closing one brings the next tab forward, which is the 3D view.
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

    if not _breadboard_shot(shots):
        return 1
    if not _nano_relay_shots(app, shots):
        return 1
    # Last, because it opens the 3D view and the guide, and every window after it would
    # restore them from the settings it leaves behind.
    if not _guide_and_3d_shot(app, shots):
        return 1

    for name, what in shots:
        size = (OUT_DIR / name).stat().st_size
        print(f"{name:32} {size // 1024:5} KB   {what}")
    return 0


#: The 555 again, tried on a half-size breadboard before it goes on to perfboard.
BREADBOARD_EXAMPLE = REPO_ROOT / "examples" / "ne555-astable.perf"


def _breadboard_shot(shots: list[tuple[str, str]]) -> bool:
    """The 555 on a solderless breadboard, in 3D.

    Taken to the breadboard the way the window takes a design to a new board
    (``design_on_a_new_board``), then placed and wired by the very calls Place on the Board
    and Autoroute make -- seeded, so the picture comes out the same every time -- and
    rendered offscreen, like ``board-3d.png``.
    """
    result = persist.deserialize_document(BREADBOARD_EXAMPLE.read_text(encoding="utf-8"))
    if not result.ok:
        print(f"LOAD FAILED [{result.code}] {result.message}")
        return False
    lookup = footprint_lookup()
    design = design_on_a_new_board(result.document, result.document.meta)
    on_breadboard = dataclasses.replace(
        design, board=breadboard("400"), edge_connectors=(), mounting_holes=()
    )
    placed = place_design(on_breadboard, lookup)
    if placed.unplaced:
        print(f"BREADBOARD PLACEMENT LEFT {placed.unplaced} IN THE DESIGN")
        return False
    plan = plan_breadboard(placed.document, lookup)
    if plan.problems:
        print(f"BREADBOARD WIRING: {[problem.code for problem in plan.problems]}")
        return False
    view3d.render_offscreen(
        plan.document, lookup, str(OUT_DIR / "breadboard-3d.png"), width=1400, height=950
    )
    shots.append(("breadboard-3d.png", "the 555 on a solderless breadboard, in 3D"))
    return True


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
    _open(window, app)
    window.act_ratsnest.setChecked(False)
    _settle(app)

    # Framed on the parts rather than the whole board, which is mostly holes even now: the
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
    # A board label the frame cuts into is taken in whole: "LOAD" came out as "OAD". Cut by
    # what the view SHOWS, which the aspect ratio makes wider than the parts' box, and so
    # measured after the first fit. A label's extent is its centre and a width estimated
    # from its cap height.
    from perfboard_studio.geometry import hole_to_mm

    shown = window.view.mapToScene(window.view.viewport().rect()).boundingRect()
    widened = False
    for note in document.board_notes:
        centre = hole_to_mm(note.at, board)
        cx, cy = centre.x + note.offset_x_mm, centre.y + note.offset_y_mm
        half_w, half_h = 0.5 * note.size_mm * len(note.text), 0.8 * note.size_mm
        if note.rotation in (90, 270):
            half_w, half_h = half_h, half_w
        inside = QRectF(cx - half_w, cy - half_h, 2 * half_w, 2 * half_h)
        if not shown.intersects(inside) or shown.contains(inside):
            continue
        left, right = min(left, inside.left() - 1.0), max(right, inside.right() + 1.0)
        top, bottom = min(top, inside.top() - 1.0), max(bottom, inside.bottom() + 1.0)
        widened = True
    if widened:
        window.view.fitInView(
            QRectF(left, top, right - left, bottom - top), Qt.AspectRatioMode.KeepAspectRatio
        )
        _settle(app)
    _grab(window, app).save(str(OUT_DIR / "catalog-and-pin-names.png"))
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


#: How many of nano-relay's steps are done in the guide shot: every part in the first three
#: phases, so the bench card is on the regulator, which stands out in 3D.
STEPS_DONE = 8

#: How far the 3D panel's camera is brought in from where it opens, as a scroll of the
#: wheel would: the opening frame fits the whole board with room to turn it, which in a
#: third of the window leaves the parts small. 1.1 is as far as the board's far corner stays
#: in the picture: it was 1.3 while the panel had no playback row, in a frame cut wider.
CAMERA_ZOOM = 1.1


def _guide_and_3d_shot(app: QApplication, shots: list[tuple[str, str]]) -> bool:
    """The board, the 3D view and the build guide side by side, part-way through a build:
    some steps ticked off, and Next Step to Do showing the next one in all three."""
    from PySide6.QtCore import Qt

    result = persist.deserialize_document(NANO_RELAY.read_text(encoding="utf-8"))
    if not result.ok:
        print(f"LOAD FAILED [{result.code}] {result.message}")
        return False

    window = MainWindow(result.document, NANO_RELAY)
    _open(window, app)
    window.act_ratsnest.setChecked(False)
    # The sidebar closed, as somebody at the bench would: what this picture is about needs
    # the width, and the editor shots show the library and the nets already.
    for dock in (window.dock_library, window.dock_part_list, window.dock_nets):
        dock.close()
    # SIDE BY SIDE, which the views are not by default: they are tabs over one canvas. The
    # sheet, the 3D view and the guide leave the group, and the last two are split off
    # Properties, the one panel in the middle row that is in no tab group: split off the
    # board, which still is in one, they went back into it as tabs -- ``splitDockWidget``
    # handed a dock in a group adds to the group (MainWindow's default layout says so too).
    # Properties then goes to the end of the row: board, 3D, guide, Properties.
    for dock in (window.dock_schematic, window.dock_3d, window.dock_guide):
        window.removeDockWidget(dock)
    _settle(app, 5)
    window.splitDockWidget(window.dock_properties, window.dock_3d, Qt.Orientation.Horizontal)
    window.dock_3d.show()
    window.splitDockWidget(window.dock_3d, window.dock_guide, Qt.Orientation.Horizontal)
    window.dock_guide.show()
    window.splitDockWidget(window.dock_guide, window.dock_properties, Qt.Orientation.Horizontal)
    _settle(app, 30)
    window.act_show_3d.trigger()
    _settle(app, 30)
    if window.vtk_widget is None:
        # Offscreen, the panel never hears it came in front: Qt sends visibilityChanged
        # only for a window on screen (see MainWindow._raise_view), so it is asked here.
        window._create_3d_widget()
    window.act_show_guide.trigger()
    _settle(app, 30)

    # Through the bench card's own "Done, next", as somebody at the bench goes. Ticking the
    # overview's leaves no longer moves the card, and the picture said "Step 1" beside a
    # board showing step 9.
    from PySide6.QtWidgets import QPushButton

    from perfboard_studio.ui.i18n import t

    done_next = next(
        button
        for button in window.dock_guide.widget().findChildren(QPushButton)
        if button.text() == t("Done, next  ▶")
    )
    for _ in range(STEPS_DONE):
        done_next.click()
        _settle(app, 5)
    _settle(app, 30)
    window.view.fit_board()
    _settle(app, 30)

    renderer = window._vtk_renderer
    if renderer is None:
        print("THE 3D VIEW DID NOT OPEN")
        return False
    _frame_offscreen_panel(window)
    renderer.GetActiveCamera().Zoom(CAMERA_ZOOM)
    renderer.ResetCameraClippingRange()
    # The bar over the selection, hidden just before the grab -- it puts itself back on any
    # turn of the event loop: in a picture of a step it covers the part the step is about,
    # and what it offers is not what this picture is of.
    window.selection_bar.hide()
    _grab_with_3d(window).save(str(OUT_DIR / "guide-and-3d.png"))
    shots.append(("guide-and-3d.png", "board, 3D and the guide, part-way through a build"))

    window._mark_saved()
    window.close()
    _settle(app)
    return True


def _grab_with_3d(window: MainWindow) -> QPixmap:
    """The window as ``grab`` sees it, with the 3D panel's picture put back in.

    ``grab`` paints every widget into a pixmap and the 3D panel is not a widget it can
    paint: VTK draws into a native window of its own, so the panel comes back empty. What
    VTK last drew is still in its render window, and ``vtkWindowToImageFilter`` reads it
    back -- drawn again first, so it is the frame with the camera as it is now.
    """
    import tempfile

    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QImage, QPainter

    pixmap = window.grab()
    widget = window.vtk_widget
    render_window = widget.GetRenderWindow()
    # Offscreen the panel holds its placeholder label, and the frame goes where that is.
    target = window._3d_placeholder if isinstance(widget, _OffscreenPanel) else widget
    render_window.Render()
    readback = view3d.vtk.vtkWindowToImageFilter()
    readback.SetInput(render_window)
    readback.ReadFrontBufferOff()
    readback.Update()
    frame = Path(tempfile.mkdtemp()) / "3d.png"
    writer = view3d.vtk.vtkPNGWriter()
    writer.SetFileName(str(frame))
    writer.SetInputConnection(readback.GetOutputPort())
    writer.Write()

    # The pixmap is painted in the window's units and the frame is in pixels, so the frame
    # is drawn into the panel's rectangle in units and lands one pixel for one.
    painter = QPainter(pixmap)
    painter.drawImage(QRect(target.mapTo(window, QPoint(0, 0)), target.size()), QImage(str(frame)))
    painter.end()
    return pixmap


class _OffscreenPanel:
    """The 3D panel's widget where there is no display: VTK's offscreen render window,
    holding the renderer the panel would. The window asks its 3D widget for exactly one
    thing, ``GetRenderWindow()``, and gets this one."""

    def __init__(self, render_window: object) -> None:
        self._render_window = render_window

    def GetRenderWindow(self) -> object:  # VTK's name, which the window calls
        return self._render_window


def _create_offscreen_3d(self: MainWindow) -> None:
    """``MainWindow._create_3d_widget`` for a window on the offscreen platform: the same
    renderer, with the same pin names, labels and owners, in an offscreen render window
    rather than a QVTK widget that cannot get a pixel format. The placeholder label stays
    in the panel, for ``_grab_with_3d`` to paint the frame over."""
    ren, _stats = view3d.build_renderer(
        self.bus.document,
        self.lookup,
        flipped=(self.side == "bottom"),
        pin_names=self._pin_names_shown(),
        board_notes=self._board_labels_shown(),
        owners=self._3d_owners,
    )
    render_window = view3d.vtk.vtkRenderWindow()
    render_window.SetOffScreenRendering(1)
    render_window.AddRenderer(ren)
    self._vtk_renderer = ren
    self.vtk_widget = _OffscreenPanel(render_window)
    # The playback row under it, as the panel builds: the slider is what a guide step moves
    # (``_show_build_step``), so without it the guide shot's 3D view showed the finished
    # board beside a card at step 9 -- the README says the board as it stands at that step --
    # and the row with Play and its arrows was missing from the picture.
    # The placeholder takes the height, as the QVTK widget it stands for does: a label is
    # not asked to grow, and the row took half the panel with the frame over the other half.
    self._3d_layout.addWidget(self._build_assembly_bar())
    self._3d_layout.setStretchFactor(self._3d_placeholder, 1)
    self._3d_stale = False
    self._show_selection_in_3d()


def _frame_offscreen_panel(window: MainWindow) -> None:
    """Size the stand-in to the panel, in pixels, and frame it as the panel frames itself
    on its first size (``_FrameOnFirstSize``). Nothing to do for a panel on screen."""
    widget = window.vtk_widget
    if not isinstance(widget, _OffscreenPanel):
        return
    label = window._3d_placeholder
    ratio = label.devicePixelRatioF()
    widget.GetRenderWindow().SetSize(  # type: ignore[attr-defined]
        round(label.width() * ratio), round(label.height() * ratio)
    )
    view3d.apply_default_camera(window._vtk_renderer, flipped=(window.side == "bottom"))


if __name__ == "__main__":
    raise SystemExit(main())
