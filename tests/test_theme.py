"""The chrome's tokens, the one stylesheet made from them, and how a theme is chosen.

Two themes, chosen once per process (``ui/theme.py``): the dark one by default and the
light one from View > Theme, at the next start. These hold what that rests on -- the choice
and its precedence, the application-wide styling, colours that read where they are drawn,
one colour per net class on the board and the sheet -- and the window's side of it.
"""

from __future__ import annotations

import dataclasses
import io
import os
import re
import tokenize
import warnings
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QMouseEvent, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QStyle

from perfboard_studio import persist
from perfboard_studio.ui import icons, theme, view2d, viewsch
from perfboard_studio.ui.theme import DARK, LIGHT, NET_COLOURS, THEME_VARIABLE, Tokens

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "ne555-astable.perf"


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def _contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio between two colours."""

    def luminance(colour: str) -> float:
        rgb = QColor(colour)
        channels = []
        for value in (rgb.redF(), rgb.greenF(), rgb.blueF()):
            channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _colours(tokens: Tokens) -> dict[str, str]:
    return {
        field.name: getattr(tokens, field.name)
        for field in dataclasses.fields(tokens)
        if isinstance(getattr(tokens, field.name), str) and field.name != "name"
    }


# -- choosing -------------------------------------------------------------------------


def test_the_suite_runs_in_the_dark_theme() -> None:
    """conftest.py names it, so a developer's own choice in the View menu never reaches
    what the tests measure."""
    assert theme.ACTIVE is DARK


def test_the_variable_beats_the_stored_choice_which_beats_the_default() -> None:
    assert theme.chosen_theme({THEME_VARIABLE: "light"}, "dark") is LIGHT
    assert theme.chosen_theme({THEME_VARIABLE: "dark"}, "light") is DARK
    assert theme.chosen_theme({}, "light") is LIGHT
    assert theme.chosen_theme({}, None) is DARK
    # Anything unknown is passed over rather than trusted: a hand-edited registry, a typo.
    assert theme.chosen_theme({THEME_VARIABLE: "blue"}, "light") is LIGHT
    assert theme.chosen_theme({}, "blue") is DARK
    assert theme.chosen_theme({}, 7) is DARK


def test_the_stored_choice_is_read_from_the_windows_own_store(monkeypatch) -> None:
    """``theme`` cannot import ``main``, so it builds the QSettings itself -- and must build
    the same one, or the View menu would write where the next start never looks."""
    from perfboard_studio.ui import main as main_module

    built: list[tuple[str, str]] = []

    class Recording:
        def __init__(self, organisation: str, application: str) -> None:
            built.append((organisation, application))

        def value(self, key: str) -> object:
            assert key == theme.THEME_KEY
            return "light"

    import PySide6.QtCore

    # The window's REAL store, not the temp one tests/conftest.py gives every test: what is
    # pinned is which store the theme reads, and that is the name the real one is built with.
    monkeypatch.undo()
    window_store = main_module.app_settings()
    monkeypatch.setattr(PySide6.QtCore, "QSettings", Recording)

    assert theme._stored_choice() == "light"
    assert built == [(window_store.organizationName(), window_store.applicationName())]


# -- the tokens -----------------------------------------------------------------------


@pytest.mark.parametrize("tokens", [DARK, LIGHT], ids=lambda k: k.name)
def test_every_token_is_a_colour(tokens: Tokens) -> None:
    for name, value in _colours(tokens).items():
        assert re.fullmatch(r"#[0-9a-f]{6}", value), f"{tokens.name}.{name} = {value!r}"


@pytest.mark.parametrize("tokens", [DARK, LIGHT], ids=lambda k: k.name)
def test_text_reads_on_every_panel_surface(tokens: Tokens) -> None:
    """4.5:1, the WCAG figure for body text, for everything that is read as words -- the
    light candidate as rendered put a warning in the status bar at 3.4:1."""
    surfaces = ("bg_app", "bg_surface", "bg_input", "bg_subtle")
    for role in ("text", "text_secondary", "accent_text", "danger", "warning", "success"):
        for surface in surfaces:
            ratio = _contrast(getattr(tokens, role), getattr(tokens, surface))
            assert ratio >= 4.5, f"{tokens.name}: {role} on {surface} is {ratio:.2f}:1"
    # Placeholders, column headers, what is disabled: quieter, still legible.
    for surface in surfaces:
        assert _contrast(tokens.text_tertiary, getattr(tokens, surface)) >= 3.0
    # A badge and the Next button with a problem: text on a status fill.
    for fill in (tokens.danger, tokens.warning):
        assert _contrast(tokens.text_on_status, fill) >= 4.5, fill
    assert _contrast(tokens.sheet_ink, tokens.sheet_paper) >= 4.5
    assert _contrast(tokens.sheet_ink_dim, tokens.sheet_paper) >= 3.0
    assert _contrast(tokens.canvas_ruler_major, tokens.canvas) >= 4.5


def test_the_stylesheet_says_nothing_the_tokens_do_not() -> None:
    """Every colour in the one stylesheet is a token of its theme. A literal here is
    exactly the drift the tokens exist to end."""
    for tokens in (DARK, LIGHT):
        sheet = theme.stylesheet(tokens)
        allowed = set(_colours(tokens).values())
        used = set(re.findall(r"#[0-9a-fA-F]{6}\b", sheet))
        assert used <= allowed, f"{tokens.name}: {sorted(used - allowed)}"
        assert sheet.count("{") == sheet.count("}")


def test_every_destructive_answer_is_drawn_as_one() -> None:
    """A message box's Delete, Don't Save or Discard It is outlined in the danger colour by
    ``theme.mark_destructive``, called once by the box. Asking each new box to remember is
    how "Delete" came to look like the lesser choice beside a blue Cancel, so the sources
    are read: a function that offers a destructive button marks it."""
    import ast

    ui = Path(__file__).resolve().parents[1] / "src" / "perfboard_studio" / "ui"
    offering = 0
    for source in sorted(ui.glob("*.py")):
        text = source.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.FunctionDef):
                continue
            body = ast.get_source_segment(text, node) or ""
            if "ButtonRole.DestructiveRole" in body or "StandardButton.Discard" in body:
                offering += 1
                assert "mark_destructive(" in body, f"{source.name}: {node.name}"
    assert offering >= 3, "the scan found fewer boxes than _confirm, unsaved and recovery"


def test_a_destructive_answer_is_outlined_and_the_default_keeps_the_accent() -> None:
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox()
    delete = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    theme.mark_destructive(box)
    assert delete.property("variant") == "danger"
    assert not cancel.property("variant")
    sheet = theme.stylesheet(DARK)
    rule = re.search(r'QPushButton\[variant="danger"\] \{([^}]*)\}', sheet)
    assert rule is not None and DARK.danger in rule.group(1)
    box.deleteLater()


def test_a_default_button_is_not_drawn_wider_than_it_was_measured() -> None:
    """Qt measures a button with its font as no pseudo-state has it. A ``:default`` drawn
    semibold was measured regular, and the dialogs' default buttons lost a letter at each
    end: "pen the Guide", "heck for Update", "ecide Later". Weight belongs on a property
    (``[variant="primary"]``), which is applied before the button is measured."""
    for tokens in (DARK, LIGHT):
        sheet = re.sub(r"/\*.*?\*/", "", theme.stylesheet(tokens), flags=re.DOTALL)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
            if ":default" in selector:
                assert "font" not in body, f"{tokens.name}: {selector.strip()}"


# -- the canvases and the nets -----------------------------------------------------------


def test_a_net_is_one_colour_on_the_board_and_on_the_sheet() -> None:
    """Power was orange on the board and amber on the sheet, and the sheet's amber was the
    warning colour as well."""
    for net_class, colour in NET_COLOURS.items():
        assert view2d.RATSNEST[net_class].name() == colour
    assert NET_COLOURS["signal"] == viewsch.SIGNAL
    assert NET_COLOURS["power"] == viewsch.POWER
    assert NET_COLOURS["ground"] == viewsch.GROUND
    for tokens in (DARK, LIGHT):
        assert NET_COLOURS["power"] != tokens.warning


def test_the_dark_theme_has_one_canvas_and_it_is_the_render_goldens() -> None:
    """The board's background and the sheet's were two near-blacks side by side. The one
    kept is the board's, which tests/test_render_golden.py draws its goldens on."""
    assert DARK.canvas == DARK.sheet_paper == "#12131a"
    assert view2d.BACKGROUND.name() == DARK.canvas
    assert DARK.sheet_paper == viewsch.SHEET


def test_marks_on_the_board_do_not_follow_the_theme() -> None:
    """Selection and the placement ghost are drawn on FR4 green in either theme. The light
    theme's accent all but vanishes there, which is why they are the board's own."""
    fr4 = view2d.SUBSTRATE["FR4"].name()
    assert _contrast(theme.CANVAS_SELECTED, fr4) > 2.0
    assert _contrast(LIGHT.accent, fr4) < 1.5
    assert view2d.SELECTED.name() == theme.CANVAS_SELECTED
    assert view2d.ERROR_OUTLINE.name() == theme.CANVAS_ERROR


# -- applied to the application ---------------------------------------------------------


@pytest.fixture
def window(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import autosave as autosave_module
    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    monkeypatch.setattr(autosave_module, "default_directory", lambda: tmp_path / "recovery")
    document = persist.parse_document_or_throw(EXAMPLE.read_text(encoding="utf-8"))
    made = main_module.MainWindow(document)
    yield made
    made._saved_document = made.bus.document
    made.close()


def test_the_window_styles_the_whole_application(window) -> None:  # type: ignore[no-untyped-def]
    """On the application, over Fusion: a dialog with no parent is themed as well. It was a
    stylesheet on the main window over the platform's style, and on Windows everything it
    did not name -- dock tabs, search fields, check boxes -- drew as a light native widget."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    assert window.styleSheet() == ""
    # The application's style() is Qt's stylesheet wrapper; ours is the one under it.
    assert theme._applied is not None
    assert theme._applied[0].baseStyle().name().lower() == "fusion"
    assert "QToolBar" in app.styleSheet()
    orphan = QDialog()
    assert orphan.palette().color(QPalette.ColorRole.Window).name() == DARK.bg_surface
    # Every image the sheet names was written, and written in this theme's colours.
    images = re.findall(r"url\(([^)]+)\)", app.styleSheet())
    assert images
    for image in images:
        assert Path(image).is_file(), image


def test_a_second_window_does_not_restyle_the_application(window) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui import main as main_module

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    style, sheet = app.style(), app.styleSheet()
    other = main_module.MainWindow(window.bus.document)
    try:
        assert app.style() is style
        assert app.styleSheet() == sheet
    finally:
        other._saved_document = other.bus.document
        other.close()


def test_choosing_the_theme_waits_for_the_next_start(window, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from perfboard_studio.ui import main as main_module

    told: list[str] = []
    monkeypatch.setattr(
        main_module.QMessageBox, "information", lambda *args, **kwargs: told.append(args[1])
    )
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    sheet = app.styleSheet()
    assert window.act_theme["dark"].isChecked()

    window.on_theme("light")

    assert main_module.app_settings().value(theme.THEME_KEY) == "light"
    assert window.act_theme["light"].isChecked()
    assert not window.act_theme["dark"].isChecked()
    assert told, "a change that only happens next time has to say so"
    assert theme.ACTIVE is DARK
    assert app.styleSheet() == sheet


def test_a_tone_colours_a_label_through_the_one_sheet(window) -> None:  # type: ignore[no-untyped-def]
    label = QLabel("3 errors")
    theme.tone(label, "danger")
    assert label.palette().color(QPalette.ColorRole.WindowText).name() == DARK.danger
    theme.tone(label, None)
    assert label.palette().color(QPalette.ColorRole.WindowText).name() == DARK.text
    assert DARK.warning in theme.ink("1 warning", "warning")


def test_access_keys_are_underlined_only_after_alt(window) -> None:  # type: ignore[no-untyped-def]
    """Fusion underlines every access key all the time; Windows only once Alt is pressed,
    and that is the look the window was chosen in."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    hint = QStyle.StyleHint.SH_UnderlineShortcut
    style = app.style()
    click = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(QPoint(5, 5)),
        QPointF(QPoint(5, 5)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    # A click first: the cues are the process's, and an earlier test that pressed Alt (the
    # header's own) leaves them on, exactly as it would in the window.
    QApplication.sendEvent(window, click)
    assert style.styleHint(hint) == 0

    alt = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier)
    QApplication.sendEvent(window, alt)
    assert style.styleHint(hint) == 1

    QApplication.sendEvent(window, click)
    assert style.styleHint(hint) == 0


# -- icons ------------------------------------------------------------------------------


def test_a_checked_tool_has_its_own_picture() -> None:
    """One picture in one colour made a checked tool's icon the same grey as every other."""
    made = icons.icon("autoroute")
    size = QSize(icons.SIZE, icons.SIZE)

    def picture(mode: QIcon.Mode, state: QIcon.State) -> bytes:
        image = made.pixmap(size, mode, state).toImage()
        return bytes(image.constBits())  # type: ignore[call-overload]

    resting = picture(QIcon.Mode.Normal, QIcon.State.Off)
    checked = picture(QIcon.Mode.Normal, QIcon.State.On)
    disabled = picture(QIcon.Mode.Disabled, QIcon.State.Off)
    assert len({resting, checked, disabled}) == 3

    image = made.pixmap(size, QIcon.Mode.Normal, QIcon.State.On).toImage()
    inks = {
        image.pixelColor(x, y).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() == 255
    }
    assert DARK.accent_text in inks


# -- nothing styles the chrome but theme.py ---------------------------------------------------
#
# The tokens end colour drift only if nothing goes round them. Four things went round them
# before: a stylesheet set on one widget, a hex colour in a string, a rich-text span with its
# own colour, and the old names (TEXT_DIM, ACCENT, ...) imported straight from theme. Each is
# looked for in every module of ui/ except theme.py, as tokens, so a comment that mentions
# one is not a finding.

UI = Path(__file__).resolve().parent.parent / "src" / "perfboard_studio" / "ui"

#: Files whose colour literals are the physical object, the 3D scene or the printed page --
#: what does NOT follow the theme. Their hex is allowed; their chrome is not.
PHYSICAL: dict[str, str] = {
    "view2d.py": "the board as on the bench: substrate, copper, solder, leads, insulation",
    "view3d.py": "the 3D scene's materials and lights",
    "boardcolors.py": "the solder-mask schemes the View menu offers",
    "bodies.py": "part bodies, one table for the 2D view, the 3D view and the guide",
    "moduleart.py": "module boards, drawn by what they are called",
    "icons.py": "the part pictures, in the bodies' colours",
    "export_pdf.py": "the 1:1 print, black ink on white paper whatever the theme",
    "export_schematic.py": "the exported sheet's paper, white whatever the theme",
}

#: Files still styled the old way, each waiting on the member who owns it. Printed on every
#: run, and a test fails the moment one is clean and still listed, so this can only shrink.
PENDING: dict[str, str] = {}

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
_INLINE_COLOUR = re.compile(r"style\s*=\s*['\"][^'\"]*color", re.IGNORECASE)
_LEGACY = {
    "WINDOW", "PANEL", "PANEL_ALT", "BORDER", "TEXT", "TEXT_DIM", "ACCENT", "ACCENT_DIM",
    "ERROR", "WARNING", "OK",
}


def _string_kinds() -> set[int]:
    kinds = {tokenize.STRING}
    for name in ("FSTRING_MIDDLE", "TSTRING_MIDDLE"):
        if hasattr(tokenize, name):
            kinds.add(getattr(tokenize, name))
    return kinds


def _chrome_findings(path: Path) -> list[str]:
    """Every way ``path`` styles the chrome without the tokens, one line each."""
    text = path.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    strings = _string_kinds()
    found: list[str] = []
    for index, token in enumerate(tokens):
        where = f"{path.name}:{token.start[0]}"
        if token.type in strings:
            if path.name not in PHYSICAL:
                found += [f"{where}: colour {colour}" for colour in _HEX.findall(token.string)]
            if _INLINE_COLOUR.search(token.string):
                found.append(f"{where}: a rich-text colour (theme.ink)")
        elif token.type == tokenize.NAME and token.string == "setStyleSheet":
            found.append(f"{where}: setStyleSheet (theme.tone / theme.variant / an objectName)")
        elif token.type == tokenize.NAME and token.string in _LEGACY:
            before = [t.string for t in tokens[max(0, index - 2) : index]]
            if before == ["theme", "."]:
                found.append(f"{where}: theme.{token.string} (a role or a token)")
        if token.string == "from" and [t.string for t in tokens[index + 1 : index + 4]] == [
            ".", "theme", "import",
        ]:
            names = []
            for later in tokens[index + 4 :]:
                if later.type == tokenize.NEWLINE:
                    break
                if later.type == tokenize.NAME and later.string in _LEGACY:
                    names.append(later.string)
            if names:
                found.append(f"{path.name}:{token.start[0]}: imports {', '.join(sorted(names))} from theme")
    return found


def _modules() -> list[Path]:
    return sorted(path for path in UI.rglob("*.py") if path.name != "theme.py")


def test_nothing_styles_the_chrome_but_theme() -> None:
    """A colour, a stylesheet or an old name outside theme.py is the drift this ended."""
    findings: list[str] = []
    for path in _modules():
        if path.name not in PENDING:
            findings += _chrome_findings(path)
    for name, why in PENDING.items():
        warnings.warn(f"styled the old way, pending: {name} -- {why}", stacklevel=1)
    assert not findings, "\n".join(findings)


def test_the_pending_list_only_shrinks() -> None:
    """A file moved onto the tokens leaves the list in the same commit, so the list says
    what is left and nothing else."""
    for name in PENDING:
        path = UI / name
        assert path.is_file(), f"{name} is listed as pending and does not exist"
        assert _chrome_findings(path), f"{name} is clean now: take it off PENDING"


def test_every_physical_file_still_has_its_colours() -> None:
    """The same for the files allowed a hex colour: one that no longer has any no longer
    needs the exception."""
    for name, why in PHYSICAL.items():
        path = UI / name
        assert path.is_file(), f"{name} ({why}) does not exist"
        text = path.read_text(encoding="utf-8")
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        assert any(
            _HEX.search(token.string) for token in tokens if token.type in _string_kinds()
        ), f"{name} has no colour literal left: take it off PHYSICAL"


def test_the_guard_finds_each_way_round_the_tokens(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The scanner itself, on a module that does all four -- and on the same words in
    comments, which are not findings."""
    module = tmp_path / "sample.py"
    module.write_text(
        "from .theme import TEXT_DIM\n"
        "from . import theme\n"
        "# setStyleSheet and #ff0000 in a comment are fine\n"
        "def f(label):\n"
        "    label.setStyleSheet('color: #ff0000;')\n"
        "    label.setText(f\"<span style='color:{theme.ACCENT}'>x</span>\")\n",
        encoding="utf-8",
    )
    found = "\n".join(_chrome_findings(module))
    assert "sample.py:5: setStyleSheet" in found
    assert "sample.py:5: colour #ff0000" in found
    assert "sample.py:6: a rich-text colour" in found
    assert "sample.py:6: theme.ACCENT" in found
    assert "sample.py:1: imports TEXT_DIM from theme" in found
    assert "sample.py:3" not in found
