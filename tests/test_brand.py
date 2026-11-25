"""The Medinstech lockup in Home's corner and in About (``ui/brand.py``)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from perfboard_studio.ui import brand, theme
from perfboard_studio.ui.brand import SIZES, BrandLink, asset_paths

from .test_ui import _close, _load_dense, _window_on


@pytest.fixture(scope="module", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication(["perfboard-studio-tests"])


@pytest.fixture()
def opened(monkeypatch) -> list[QUrl]:
    """Every URL the application asked the desktop to open, instead of opening it."""
    urls: list[QUrl] = []

    class _Desktop:
        @staticmethod
        def openUrl(url: QUrl) -> bool:
            urls.append(url)
            return True

    monkeypatch.setattr(brand, "QDesktopServices", _Desktop)
    return urls


def _opaque_colours(image: QImage) -> list[QColor]:
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    return [
        image.pixelColor(x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 200
    ]


@pytest.mark.parametrize("place", ["home", "about"])
@pytest.mark.parametrize("dark", [False, True])
def test_every_lockup_is_on_disk_at_its_size_and_twice_it(place, dark) -> None:
    one, two = asset_paths(place, dark)
    small, large = QImage(str(one)), QImage(str(two))
    assert not small.isNull() and not large.isNull()
    assert small.size() == SIZES[place]
    assert large.width() == 2 * small.width() and large.height() == 2 * small.height()


def test_the_light_lockup_is_the_brand_blue_and_the_dark_one_is_white() -> None:
    """The pick, pinned: the blue lockup as printed on light, and on dark a white mark and a
    white name -- not the blue one put on a dark panel."""
    light = _opaque_colours(QImage(str(asset_paths("about", False)[1])))
    dark = _opaque_colours(QImage(str(asset_paths("about", True)[1])))
    assert light and dark
    blue = [c for c in light if c.blue() > 200 and c.red() < 60 and c.green() < 60]
    assert len(blue) > len(light) // 3
    assert all(c.red() > 240 and c.green() > 240 and c.blue() > 240 for c in dark)


def test_the_dark_mark_has_its_figure_cut_out() -> None:
    """Where the printed mark has its pale figure, the dark one has nothing: the panel shows
    through. A figure let through at 28% white read as a grey blob, and was replaced."""
    light = QImage(str(asset_paths("about", False)[1])).convertToFormat(QImage.Format.Format_ARGB32)
    dark = QImage(str(asset_paths("about", True)[1])).convertToFormat(QImage.Format.Format_ARGB32)
    side = light.height()  # the mark is the square at the left
    figure, piece = [], []
    for y in range(side):
        for x in range(side):
            colour = light.pixelColor(x, y)
            if colour.alpha() <= 200:
                continue
            seen = dark.pixelColor(x, y).alpha()
            if colour.green() > 200:
                figure.append(seen)
            elif colour.green() < 60 and colour.blue() > 200:
                piece.append(seen)
    assert len(figure) > len(piece)  # the figure is most of the mark
    assert sum(alpha < 40 for alpha in figure) > 0.95 * len(figure)
    assert sum(alpha > 200 for alpha in piece) > 0.9 * len(piece)


def test_the_mark_is_large_enough_to_be_seen() -> None:
    """At 18-22 px no version of the mark was recognisable; 32 in Home and 40 in About."""
    assert SIZES["home"].height() == 32
    assert SIZES["about"].height() == 40


def test_the_picture_is_read_after_the_button_shows_and_follows_the_palette(opened) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    before = app.palette()
    link = BrandLink("home")
    try:
        app.setPalette(theme.palette(theme.LIGHT))
        assert not link.loaded
        link.show()
        assert not link.loaded  # the first turn of the loop after it shows
        QApplication.processEvents()
        assert link.loaded and link.shows_dark is False
        assert not link.icon().isNull()
        app.setPalette(theme.palette(theme.DARK))
        QApplication.processEvents()
        assert link.shows_dark is True
        app.setPalette(theme.palette(theme.LIGHT))
        QApplication.processEvents()
        assert link.shows_dark is False
        assert link.size().width() == SIZES["home"].width() + 6
    finally:
        app.setPalette(before)
        link.close()


def test_a_click_on_the_lockup_opens_the_site(opened) -> None:
    link = BrandLink("about")
    try:
        assert link.cursor().shape() == Qt.CursorShape.PointingHandCursor
        assert "medinstech.com" in link.toolTip()
        link.click()
        assert [url.toString() for url in opened] == ["https://www.medinstech.com"]
    finally:
        link.close()


def test_home_and_about_carry_the_lockup_and_about_still_says_the_version(opened) -> None:
    from perfboard_studio.version import describe as describe_version

    window = _window_on(_load_dense())
    try:
        window.on_home()
        home = window._home_page
        assert home is not None
        assert isinstance(home.brand, BrandLink)

        dialog = window.about_dialog()
        try:
            assert isinstance(window.about_brand, BrandLink)
            assert describe_version() in window.about_text.text()
            # Selectable, so the version can be pasted into a bug report.
            flags = window.about_text.textInteractionFlags()
            assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
            site = next(
                label
                for label in dialog.findChildren(type(window.about_text))
                if "www.medinstech.com" in label.text()
            )
            site.linkActivated.emit("https://www.medinstech.com")
            assert [url.toString() for url in opened] == ["https://www.medinstech.com"]
        finally:
            dialog.close()
    finally:
        _close(window)
