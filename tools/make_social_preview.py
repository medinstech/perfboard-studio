"""Draw the card GitHub shows wherever the repository is linked.

    python tools/make_social_preview.py

Writes `docs/images/social-preview.png` at 1280x640, which is the size GitHub asks for
and the 2:1 ratio Slack, Discord, X and every other unfurl crop towards.

WHY THIS IS A SCRIPT. The same argument `tools/make_assets.py` makes for the application
icon. A card drawn once by hand starts becoming a picture of an older version of the
product the first time anything on it changes.

GITHUB WILL NOT TAKE IT FROM A COMMIT. The social preview is repository metadata, not a
file in the tree: there is no REST API for it, so the image is committed here and set by
hand at Settings -> General -> Social preview. The file being in the repository is what
makes "which image is up there?" answerable at all.

IT IS THE README'S BANNER, STANDING STILL. `tools/make_banner.py` draws both: the Medinstech
wordmark, the name and its rule, the tagline, and the NE555 board the engine placed and
routed -- here at `make_banner.CARD`'s size, finished and lit, with where to get it at the
bottom. A link and the page it opens are the same picture. The card used to be drawn here
with Pillow beside a crop of the editor screenshot, which made it a second design of the
same thing, cut at fixed pixel coordinates out of a screenshot whose size depended on the
monitor it had been taken on.

THE SVG IS TURNED INTO PIXELS BY QT WEBENGINE: the Chromium that PySide6 already brings, so
nothing new to install, and the engine most readers' browsers draw the banner with. It is
shown off screen with Qt's scaling pinned to 1, so the PNG is 1280 x 640 whatever the
monitor.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Before Qt is imported, which is when it reads them: one CSS pixel is one pixel of the PNG.
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"

import make_banner  # noqa: E402

OUT = REPO_ROOT / "docs" / "images" / "social-preview.png"


def rasterize(svg: str, width: int, height: int, out: Path) -> None:
    """Draw ``svg`` with Qt WebEngine and write what it drew as a PNG."""
    from PIL import Image
    from PySide6.QtCore import Qt
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    view = QWebEngineView()
    view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    view.resize(width, height)
    loaded: list[bool] = []
    view.loadFinished.connect(loaded.append)
    view.setHtml(f"<!doctype html><html><body style='margin:0;overflow:hidden'>{svg}</body></html>")
    view.show()

    # Loaded is not drawn: the page is painted on later turns of the loop, so the loop is run
    # for a moment after it says it has finished.
    deadline = time.monotonic() + 30
    while not loaded and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if loaded != [True]:
        raise SystemExit("Qt WebEngine did not load the card")
    settled = time.monotonic() + 1.0
    while time.monotonic() < settled:
        app.processEvents()
        time.sleep(0.01)

    # And painted is not a second either, on a machine with other work on it: one run under
    # load grabbed the page before it was drawn and wrote a card of plain white, 3 KB where
    # the real one is 370, which nothing would have noticed until it was the repository's
    # face. So the grab is taken again until it holds more than one colour.
    image = view.grab().toImage()
    deadline = time.monotonic() + 20
    while _one_colour(image):
        if time.monotonic() > deadline:
            raise SystemExit("Qt WebEngine loaded the card and drew nothing in 20 s")
        app.processEvents()
        time.sleep(0.1)
        image = view.grab().toImage()
    if (image.width(), image.height()) != (width, height):
        raise SystemExit(f"drew {image.width()} x {image.height()}, not {width} x {height}")
    raw = out.with_suffix(".raw.png")
    image.save(str(raw))
    # Through Pillow once more, for its optimiser and to drop the alpha channel the card
    # does not have.
    with Image.open(raw) as drawn:
        drawn.convert("RGB").save(out, optimize=True)
    raw.unlink()


def _one_colour(image: object) -> bool:
    """Whether a grabbed QImage is a single colour all over, which is what an unpainted page is."""
    from PySide6.QtGui import QImage

    assert isinstance(image, QImage)
    first = image.pixel(0, 0)
    step = max(1, min(image.width(), image.height()) // 64)
    return all(
        image.pixel(x, y) == first
        for y in range(0, image.height(), step)
        for x in range(0, image.width(), step)
    )


def main() -> int:
    document = make_banner.build_board()
    layout = make_banner.CARD
    svg = make_banner.render(document, make_banner.WORDS["en"], layout)
    rasterize(svg, layout.width, layout.height, OUT)
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({layout.width}x{layout.height}, {OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
