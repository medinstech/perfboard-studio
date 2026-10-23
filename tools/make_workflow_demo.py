"""Render the animated tour the README opens with: the step bar taking a drawn circuit to
its build guide.

    python tools/make_workflow_demo.py               # -> docs/images/workflow.gif
    python tools/make_workflow_demo.py --lang tr     # -> docs/images/workflow.tr.gif

Needs Pillow, which is not a dependency of the application -- only of this script, which
is run by hand when the window changes enough for the tour to be out of date.

WHY THIS ONE IS THE WINDOW, when ``make_demo.py`` deliberately is not. ``assembly.gif``
shows what the build guide is FOR -- its order -- and the menus would only be in the way.
This one shows what the application is like to USE: one button at the end of the step
bar that names the next thing to do and does it, from a circuit on the sheet to the guide.
That is a picture of the window or it is nothing.

It is the real window running the real commands: the welcome screen's first example --
the circuit that is drawn and not yet built -- then the step bar's button, pressed until
the build guide is in front. Every dialog on the way is pictured over the window and
answered as somebody new would answer it, with what it already has selected. A dialog the
tour does not expect stops the script rather than being clicked through, because a tour
that quietly answered a question differently from a user is a tour of something else.

Offscreen, so nothing opens on the desktop of whoever runs it; on Windows Qt's offscreen
plugin needs pointing at the system fonts or every label is a row of boxes.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

#: The window, in pixels: big enough that the board, the sheet and the step bar are all
#: there, small enough that a README column shows it without shrinking the text to dust.
WINDOW_SIZE = (1280, 800)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"

#: How long each kind of frame is held, in milliseconds. A frame with a ring on the button
#: about to be pressed is held long enough to read the button; what it did, a little less.
POINT_MS = 1700
RESULT_MS = 1300
#: The guide, at the end, is held: a loop that snaps back the moment it arrives never
#: shows anybody what the button was walking towards.
HOLD_MS = 3500
#: The ring drawn round whatever is about to be pressed. Amber, because the button it most
#: often surrounds is the interface's own blue.
RING = "#ffb000"
#: The board the tour picks in the board dialog, rather than the one it suggests. The
#: suggestion for this example is the 2 x 8 cm strip -- real, and it builds as well -- but
#: the trimmer covers half of it and the labels crowd the rest, which makes a poor first
#: picture. Picking another is an ordinary thing to do in that dialog, and showing it done
#: is the only way the tour can say the choice is there at all.
CHOSEN_BOARD = "5 x 7 cm"


def main(argv: list[str]) -> int:
    try:
        from PIL import Image
    except ImportError:
        print("this script needs Pillow:  pip install pillow", file=sys.stderr)
        return 1

    language = argv[argv.index("--lang") + 1] if "--lang" in argv else "en"
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else (
        REPO_ROOT / "docs" / "images" / ("workflow.gif" if language == "en" else f"workflow.{language}.gif")
    )

    from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, QSettings, Qt, QTimer
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import (
        QAbstractButton,
        QApplication,
        QDialog,
        QListWidgetItem,
        QMessageBox,
        QProgressDialog,
        QWidget,
    )

    app = QApplication.instance() or QApplication([])
    if sys.platform == "win32":
        # What Windows hands a Qt application on a real display. The offscreen plugin has no
        # system font to ask for, so without this it takes the first face in the folder and
        # the tour is set in a font the application is never seen in.
        from PySide6.QtGui import QFont

        app.setFont(QFont("Segoe UI", 9))

    from perfboard_studio.ui import autosave as autosave_module
    from perfboard_studio.ui import i18n
    from perfboard_studio.ui import main as main_module

    scratch = Path(tempfile.mkdtemp(prefix="workflow-demo-"))
    store = QSettings(str(scratch / "settings.ini"), QSettings.Format.IniFormat)
    main_module.app_settings = lambda: store  # type: ignore[assignment]
    autosave_module.default_directory = lambda: scratch / "autosave"  # type: ignore[assignment]
    i18n.set_language(language)
    # Qt's own words -- OK, Cancel -- in that language too, as main() does; held, because a
    # translator Python collects takes its strings with it.
    qt_words = main_module._install_qt_translations(app)  # noqa: F841

    from perfboard_studio.ui.main import BoardSizeDialog, MainWindow, WelcomeDialog, example_boards

    def settle(rounds: int = 20) -> None:
        for _ in range(rounds):
            app.processEvents()
            app.sendPostedEvents(None, 0)  # the deleteLater()s, see screenshots.py
        loop_until = QTimer()
        loop_until.setSingleShot(True)
        loop_until.start(120)
        while loop_until.isActive():
            app.processEvents()

    frames: list[tuple[Image.Image, int]] = []

    def to_pil(pixmap: QPixmap) -> Image.Image:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        from io import BytesIO

        return Image.open(BytesIO(bytes(buffer.data()))).convert("RGB")

    def shoot(ms: int, dialog: QWidget | None = None, ring: QWidget | QRect | None = None,
              ring_in: QWidget | None = None) -> None:
        """The window as it is, a dialog over it if one is up, and a ring round ``ring``."""
        picture = window.grab()
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        offset = QPoint(0, 0)
        if dialog is not None:
            pane = dialog.grab()
            offset = QPoint(
                (picture.width() - pane.width()) // 2, (picture.height() - pane.height()) // 2
            )
            painter.fillRect(picture.rect(), QColor(0, 0, 0, 90))
            painter.drawPixmap(offset, pane)
        if ring is not None:
            if isinstance(ring, QWidget):
                origin = ring.mapTo(dialog if dialog is not None else window, QPoint(0, 0))
                rect = QRect(origin, ring.size())
            else:
                assert ring_in is not None
                rect = QRect(ring_in.mapTo(dialog if dialog is not None else window, ring.topLeft()), ring.size())
            rect.translate(offset)
            pen = QPen(QColor(RING))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-5, -4, 5, 4), 8, 8)
        painter.end()
        frames.append((to_pil(picture), ms))

    # -- Dialogs on the way are pictured and answered with what they already have selected.
    unexpected: list[str] = []
    original_exec = QDialog.exec

    def pictured_exec(self: QDialog) -> int:
        if isinstance(self, QProgressDialog):
            return original_exec(self)
        self.show()
        settle()
        if isinstance(self, BoardSizeDialog):
            board = _item_for_board(self, CHOSEN_BOARD)
            if board is None:
                unexpected.append(f"the board dialog offers no {CHOSEN_BOARD} to pick")
                self.reject()
                return int(QDialog.DialogCode.Rejected)
            self.choices.scrollToItem(board)
            settle()
            shoot(POINT_MS + 600, dialog=self, ring=self.choices.visualItemRect(board),
                  ring_in=self.choices.viewport())
            self.choices.setCurrentItem(board)
            settle()
            shoot(POINT_MS, dialog=self, ring=_default_button(self))
            self.accept()
            return int(QDialog.DialogCode.Accepted)
        unexpected.append(f"{type(self).__name__}: {self.windowTitle()}")
        shoot(RESULT_MS, dialog=self)
        self.reject()
        return int(QDialog.DialogCode.Rejected)

    def _item_for_board(dialog: BoardSizeDialog, name: str) -> QListWidgetItem | None:
        """The first enabled entry for the stock board called ``name``, if it is offered."""
        for row in range(dialog.choices.count()):
            item = dialog.choices.item(row)
            index = int(item.data(Qt.ItemDataRole.UserRole))
            if (
                index >= 0
                and dialog._suggestions[index].preset.name == name
                and item.flags() & Qt.ItemFlag.ItemIsEnabled
            ):
                return item
        return None

    def _default_button(dialog: QDialog) -> QWidget | None:
        for button in dialog.findChildren(QAbstractButton):
            if getattr(button, "isDefault", lambda: False)() and button.isVisible():
                return button
        return None

    QDialog.exec = pictured_exec  # type: ignore[method-assign]
    QMessageBox.exec = pictured_exec  # type: ignore[method-assign]

    # A blank start, exactly as main() makes one when no file is named.
    stamp = main_module._now_iso()
    window = MainWindow(
        main_module.create_starter_document(
            main_module.DocumentMeta(name=main_module.UNTITLED_NAME, created=stamp, modified=stamp)
        ),
        None,
    )
    window.resize(*WINDOW_SIZE)
    window.show()
    settle(40)

    # -- The welcome screen, and its first example: the circuit drawn and not yet built.
    examples = example_boards()
    if not examples:
        print("no examples found -- run from a checkout", file=sys.stderr)
        return 1
    first = examples[0][0]
    welcome = WelcomeDialog([], window, examples=examples)
    welcome.show()
    settle()
    welcome.examples.setCurrentRow(0)
    settle()
    item_rect = welcome.examples.visualItemRect(welcome.examples.item(0))
    shoot(POINT_MS + 600, dialog=welcome, ring=item_rect, ring_in=welcome.examples.viewport())
    welcome.close()
    window.on_open_example(first)
    settle(40)
    if window.bus.document.components:
        print(f"{first.name} is already built; the tour needs the drawn one", file=sys.stderr)
        return 1
    shoot(RESULT_MS)

    # -- Then the one button, until the guide is in front.
    bar = window.workflow_bar
    for _press in range(8):
        step = bar._next
        shoot(POINT_MS, ring=bar.next_button)
        bar.next_button.click()
        settle(40)
        if unexpected:
            print("a dialog the tour does not expect came up: " + "; ".join(unexpected),
                  file=sys.stderr)
            return 1
        if step == "build":
            break
        shoot(RESULT_MS)
    else:
        print("eight presses and the guide never came up", file=sys.stderr)
        return 1
    shoot(HOLD_MS)

    _write_gif(frames, out)
    print(f"{out}  {len(frames)} frames  {out.stat().st_size // 1024} KB")
    window.close()
    os._exit(0)


def _write_gif(frames: list, out: Path) -> None:
    """One palette for every frame, no dithering: see make_demo.py for why each."""
    from PIL import Image

    images = [image for image, _ms in frames]
    strip = Image.new("RGB", (images[0].width, images[0].height * len(images)))
    for index, image in enumerate(images):
        strip.paste(image, (0, index * images[0].height))
    palette = strip.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    mapped = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    out.parent.mkdir(parents=True, exist_ok=True)
    mapped[0].save(
        out,
        save_all=True,
        append_images=mapped[1:],
        duration=[ms for _image, ms in frames],
        loop=0,
        disposal=1,
        optimize=False,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
