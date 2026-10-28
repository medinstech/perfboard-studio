"""Application chrome: the tokens, and the one stylesheet and palette made from them.

Kept apart from ``view2d``'s theme block on purpose, because the two answer different
questions. ``view2d`` colours a PHYSICAL OBJECT -- FR4 green, tinned copper, solder grey --
and those colours are chosen to look like the thing on the bench, and to keep conductor
kinds apart at a glance. This file colours the APPLICATION, and its only job is to stay
out of the way: a board is the brightest, most saturated thing on screen, and every panel
around it is deliberately dimmer so the eye lands on the work rather than on the furniture.

Qt's default light chrome around a dark board is what made the promoted prototype look
unfinished -- a bright grey dock beside a dark viewport reads as two applications stapled
together.

THE TOKENS ARE NAMED BY ROLE, never by shade, so a theme is one instance of ``Tokens`` and
changing a colour renames nothing. Two themes exist, chosen on 2026-10-28 from three
candidates rendered on the real window: the dark one is the default, and the light one is
offered in View > Theme. Every surface the window draws -- menus, docks, trees, inputs,
buttons, tooltips -- is styled by ``stylesheet(tokens)`` and ``palette(tokens)``, set once
on the APPLICATION by ``apply``, over Fusion. It used to be a stylesheet on the main window
over the platform's own style, and everything the stylesheet did not name drew natively:
on Windows the dock tabs, every search field and every check box were light Windows 11
widgets in a dark window, and a dialog with no parent got no theme at all.

THE THEME IS CHOSEN ONCE, when this module is imported, and applies at the next start like
the language: modules all over ``ui/`` read these names as they are imported, and
re-colouring a running window would leave whatever a rebuild missed in the old theme. The
variable beats the View menu's stored choice, which beats the default; the suite sets the
variable in ``tests/conftest.py``, so what a developer chose in their own window never
changes what the tests measure.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QGroupBox,
    QLabel,
    QMenu,
    QMenuBar,
    QProxyStyle,
    QStyle,
    QStyleHintReturn,
    QStyleOption,
    QTabBar,
    QWidget,
)


@dataclass(frozen=True, slots=True)
class Tokens:
    """One theme. Every colour, size and radius the chrome uses, and nothing else."""

    #: "dark" or "light": what the View menu stores and the variable names.
    name: str
    # Surfaces, from the furniture to what floats on it.
    bg_app: str  # the gutter between panels, the status bar
    bg_surface: str  # panels, toolbars, docks, dialogs
    bg_raised: str  # menus, tooltips, popovers
    bg_subtle: str  # quiet fills: alternate rows
    bg_hover: str
    bg_pressed: str
    bg_input: str
    # Lines.
    border: str  # the hairline between regions
    border_strong: str  # the edge of an input, a button, a raised surface
    # Text, in three strengths, and on the accent.
    text: str
    text_secondary: str
    text_tertiary: str  # placeholders, column headers, disabled
    text_on_accent: str
    # The one accent: the primary action, the current step, what is selected.
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_subtle: str  # a selected row, a checked tool
    accent_text: str  # the accent as text or as an icon on a surface
    # Status.
    danger: str
    warning: str
    success: str
    danger_subtle: str
    warning_subtle: str
    success_subtle: str
    # The canvases: what is AROUND the board and UNDER the drawing, never the board itself.
    canvas: str
    canvas_ruler: str
    canvas_ruler_major: str
    sheet_paper: str
    sheet_ink: str
    sheet_ink_dim: str
    sheet_grid: str
    sheet_grid_major: str
    sheet_selected: str
    sheet_note: str
    #: Alternate rows in trees and lists. They help on a dark surface, where the row
    #: boundaries disappear, and are noise on a light one.
    zebra: bool
    #: Text on a warning or danger fill -- a badge, the Next button with a problem. White
    #: on the dark theme's amber reads at under 2:1 and on its red at 3.3:1.
    text_on_status: str
    #: How dark what floats casts its shadow, out of 255 (``elevate``).
    shadow_alpha: int


#: The default. Today's dark blue-grey, cleaned up: one surface step fewer, three strengths
#: of text instead of two, and the accent kept, so the window is recognisably itself.
#: The canvas and the sheet are ONE near-black: the board's background was #12131a and the
#: sheet's #161a21, two blacks side by side with nothing to say for the difference. The
#: board's is the one kept, because the 2D render golden is drawn on it.
DARK = Tokens(
    name="dark",
    bg_app="#14161b",
    bg_surface="#1b1e25",
    bg_raised="#242833",
    bg_subtle="#1f232b",
    bg_hover="#272b36",
    bg_pressed="#2e3340",
    bg_input="#15171c",
    border="#2a2f3a",
    border_strong="#363c4a",
    text="#e4e7ee",
    text_secondary="#a0a8b8",
    text_tertiary="#6b7387",
    text_on_accent="#ffffff",
    accent="#4c9dff",
    accent_hover="#66abff",
    accent_pressed="#3a87e6",
    accent_subtle="#1e3452",
    accent_text="#7db8ff",
    danger="#ef5b5f",
    warning="#e5a840",
    success="#4cc160",
    danger_subtle="#3a1f24",
    warning_subtle="#3a2f1c",
    success_subtle="#1c3323",
    canvas="#12131a",
    canvas_ruler="#8b93a7",
    canvas_ruler_major="#d3d9e8",
    sheet_paper="#12131a",
    sheet_ink="#c8d0de",
    sheet_ink_dim="#7d8698",
    sheet_grid="#1e2531",
    sheet_grid_major="#28313f",
    sheet_selected="#f0f3f8",
    sheet_note="#9aa6ba",
    zebra=True,
    text_on_status="#1b1e25",
    shadow_alpha=120,
)

#: The light theme: white panels on a pale gutter, a light grey canvas round the board and
#: the sheet as paper -- dark ink on near-white, which is what a schematic is. The status
#: colours and the tertiary text are darker than in the rendered candidate, which put a
#: warning in the status bar at 3.4:1. Text, secondary text, the accent and the status
#: colours read at 4.5:1 or better on every panel surface, as in the dark theme
#: (``tests/test_theme.py``).
LIGHT = Tokens(
    name="light",
    bg_app="#ececef",
    bg_surface="#ffffff",
    bg_raised="#ffffff",
    bg_subtle="#f6f6f8",
    bg_hover="#f1f1f4",
    bg_pressed="#e6e6ea",
    bg_input="#ffffff",
    border="#e4e4e8",
    border_strong="#d3d3d9",
    text="#18181b",
    text_secondary="#5a5a66",
    text_tertiary="#80808c",
    text_on_accent="#ffffff",
    accent="#2563eb",
    accent_hover="#1d55d6",
    accent_pressed="#1a47b8",
    accent_subtle="#e7eefd",
    accent_text="#1d4fd0",
    danger="#c42727",
    warning="#9a5a00",
    success="#147a3c",
    danger_subtle="#fdeaea",
    warning_subtle="#fdf3e1",
    success_subtle="#e6f5ec",
    canvas="#e3e5e9",
    canvas_ruler="#7f8492",
    canvas_ruler_major="#3b3f4a",
    sheet_paper="#fdfdfc",
    sheet_ink="#2a2c33",
    sheet_ink_dim="#7b7f8b",
    sheet_grid="#f0f0f2",
    sheet_grid_major="#e2e2e7",
    sheet_selected="#111114",
    sheet_note="#6b7080",
    zebra=False,
    text_on_status="#ffffff",
    shadow_alpha=46,
)

THEMES: dict[str, Tokens] = {DARK.name: DARK, LIGHT.name: LIGHT}
DEFAULT_THEME = DARK.name

#: The View menu's choice, in ``main.app_settings()``'s store, beside the language.
THEME_KEY = "session/theme"
#: Set for one run, so it beats the stored choice -- the language's precedence.
THEME_VARIABLE = "PERFBOARD_STUDIO_THEME"

#: Net classes, ONE colour each, read by the ratsnest on the board and by the sheet alike.
#: They differed -- power was orange on the board and amber on the sheet, signal two
#: different blues -- so one net was two colours a panel apart, and the sheet's power was
#: the warning colour as well. They are the same in every theme, because the ratsnest is
#: drawn on the board, which does not change with the theme; these are the board's, which
#: also read on both sheets.
NET_COLOURS: dict[str, str] = {
    "ground": "#7f8794",
    "power": "#e0723c",
    "signal": "#3fa9d4",
}

#: Marks drawn ON the board -- what is selected, what is under the pointer, where a part
#: being placed would land -- sit on FR4 green, phenolic brown or a breadboard's white in
#: every theme. They are chosen against the board rather than against the window, so they
#: do not follow the theme: the light theme's accent is one FR4 green barely shows.
CANVAS_SELECTED = "#4c9dff"
CANVAS_HOVER = CANVAS_SELECTED
CANVAS_GHOST_VALID = CANVAS_SELECTED
CANVAS_ERROR = "#e5484d"
CANVAS_GHOST_INVALID = CANVAS_ERROR
#: How heavy those marks are: COSMETIC pixels, the same on screen at every zoom. In
#: millimetres a 0.22 mm outline was 0.4 px zoomed out and 6 px zoomed in, and never the
#: same weight twice. Hover is the lighter of the two, so the two never read alike.
CANVAS_HOVER_WIDTH_PX = 1.0
CANVAS_SELECTED_WIDTH_PX = 2.0

# Type: one face, two weights, and these sizes (px). The body is what Windows has always
# drawn at 9 pt; 13 px was tried in the rendered candidates and cost the toolbar five of
# its labels.
FONT_PX = 12
CAPTION_PX = 11
#: A paragraph that leads: the empty window's guidance.
LEAD_PX = 13
TITLE_PX = 18
SEMIBOLD = 600

# Shape.
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 8

#: The spacing scale (px). Every padding and margin in the stylesheet is one of these.
SPACE = {"2xs": 2, "xs": 4, "sm": 6, "md": 8, "lg": 12, "xl": 16, "2xl": 24}


def chosen_theme(environ: Mapping[str, str], stored: object) -> Tokens:
    """The variable, then the stored choice, then the default. Anything unknown is skipped."""
    for name in (environ.get(THEME_VARIABLE), stored):
        if isinstance(name, str) and name in THEMES:
            return THEMES[name]
    return THEMES[DEFAULT_THEME]


def _stored_choice() -> object:
    """The View menu's choice. The same store as ``main.app_settings()``, which this module
    cannot import -- a test holds the two to one organisation and application name."""
    from PySide6.QtCore import QSettings

    return QSettings("Perfboard Studio", "Perfboard Studio").value(THEME_KEY)


def _choose() -> Tokens:
    if os.environ.get(THEME_VARIABLE) in THEMES:
        # Not reading the store at all when the variable answers, so a run that names its
        # theme -- every test run -- never touches the user's settings.
        return chosen_theme(os.environ, None)
    return chosen_theme(os.environ, _stored_choice())


#: The theme this process runs in. Fixed for its life; see the module docstring.
ACTIVE: Tokens = _choose()


Role = Literal["text", "secondary", "tertiary", "accent", "danger", "warning", "success"]


def colour(role: Role, tokens: Tokens = ACTIVE) -> str:
    """The colour a piece of TEXT takes for its role, as a hex string."""
    return {
        "text": tokens.text,
        "secondary": tokens.text_secondary,
        "tertiary": tokens.text_tertiary,
        "accent": tokens.accent_text,
        "danger": tokens.danger,
        "warning": tokens.warning,
        "success": tokens.success,
    }[role]


def ink(text: str, role: Role) -> str:
    """Rich text in a role's colour. A label's own colour is ``tone``; this is for a part
    of one, where only a span can say it."""
    return f'<span style="color:{colour(role)}">{text}</span>'


def restyle(widget: QWidget) -> None:
    """Have the stylesheet look at ``widget`` again after one of its properties changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def tone(widget: QWidget, role: Role | None) -> None:
    """Colour a widget's text by role through the stylesheet (``[tone="..."]``)."""
    widget.setProperty("tone", role or "")
    restyle(widget)


Variant = Literal["primary", "link", "card"]


def elevate(widget: QWidget) -> None:
    """A soft shadow under something that FLOATS over the canvas -- the board's tools, the
    selection bar -- which a stylesheet cannot draw. Only there: a docked panel is level with
    its neighbours and is told apart from them by a hairline."""
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(18.0)
    shadow.setOffset(0.0, 4.0)
    shadow.setColor(QColor(0, 0, 0, ACTIVE.shadow_alpha))
    widget.setGraphicsEffect(shadow)


def variant(widget: QWidget, name: Variant | None) -> None:
    """A button's kind -- the one accent-filled action on a surface, or a link -- or a
    card: a raised surface with a hairline edge, for a frame that groups."""
    widget.setProperty("variant", name or "")
    restyle(widget)


def size(widget: QWidget, px: int) -> None:
    """Set a widget's text to one of the type scale's sizes, keeping its face."""
    face = widget.font()
    face.setPixelSize(px)
    widget.setFont(face)


def heading(text: str) -> str:
    """A title inside rich text, where a whole-label size cannot reach."""
    return f'<span style="font-size:{TITLE_PX}px; font-weight:{SEMIBOLD}">{text}</span>'


def mono_font(base: QFont) -> QFont:
    """The face for identifiers a person copies character by character."""
    result = QFont(base)
    result.setFamilies(["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo"])
    result.setStyleHint(QFont.StyleHint.Monospace)
    return result


def stylesheet(k: Tokens, arrows: Mapping[str, str] | None = None) -> str:
    """The ONE stylesheet. Every colour in it is a token and every length a scale step.

    ``arrows`` are the images ``_arrow_images`` wrote; without them the boxes keep the
    arrows Fusion gives them."""
    s = SPACE
    alternate = k.bg_subtle if k.zebra else k.bg_surface
    tones = "\n".join(
        f'QWidget[tone="{role}"] {{ color: {colour(role, k)}; }}'
        for role in ("text", "secondary", "tertiary", "accent", "danger", "warning", "success")
    )
    return f"""
QWidget {{
    background: {k.bg_surface};
    color: {k.text};
}}
QMainWindow {{ background: {k.bg_app}; }}
QMainWindow::separator {{ background: {k.bg_app}; width: 1px; height: 1px; }}
QLabel {{ background: transparent; }}
{tones}
{_box_arrows(arrows) if arrows else ''}

QMenuBar {{
    background: {k.bg_surface};
    border-bottom: 1px solid {k.border};
    padding: {s["2xs"]}px {s["sm"]}px;
}}
QMenuBar::item {{
    padding: {s["xs"]}px {s["md"]}px;
    border-radius: {RADIUS_SM}px;
    color: {k.text_secondary};
}}
QMenuBar::item:selected {{ background: {k.bg_hover}; color: {k.text}; }}
QMenu {{
    background: {k.bg_raised};
    border: 1px solid {k.border_strong};
    border-radius: {RADIUS_LG}px;
    padding: {s["xs"]}px;
}}
QMenu::item {{
    padding: {s["sm"]}px {s["2xl"]}px {s["sm"]}px {s["lg"]}px;
    border-radius: {RADIUS_SM}px;
}}
QMenu::item:selected {{ background: {k.bg_hover}; }}
QMenu::item:disabled {{ color: {k.text_tertiary}; }}
QMenu::separator {{ height: 1px; background: {k.border}; margin: {s["xs"]}px {s["md"]}px; }}

QToolButton {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_SM}px;
    padding: {s["2xs"]}px {s["xs"]}px;
}}
QToolButton:hover {{ background: {k.bg_hover}; }}
QToolButton:pressed {{ background: {k.bg_pressed}; }}

QToolBar {{
    background: {k.bg_surface};
    border: none;
    border-bottom: 1px solid {k.border};
    padding: {s["xs"]}px {s["md"]}px;
    spacing: {s["2xs"]}px;
}}
QToolBar QToolButton {{
    background: transparent;
    color: {k.text_secondary};
    border: none;
    padding: {s["xs"]}px {s["md"]}px;
    border-radius: {RADIUS_MD}px;
}}
QToolBar QToolButton:hover {{ background: {k.bg_hover}; color: {k.text}; }}
QToolBar QToolButton:pressed {{ background: {k.bg_pressed}; }}
QToolBar QToolButton:checked {{ background: {k.accent_subtle}; color: {k.accent_text}; }}
QToolBar QToolButton:disabled {{ color: {k.text_tertiary}; }}
QToolButton::menu-button {{
    background: transparent;
    border: none;
    width: {s["lg"]}px;
}}
QToolButton[popupMode="1"] {{ padding-right: {s["xl"]}px; }}
QToolBar#headerToolbar {{ border: 0; padding: 0; spacing: 0; }}
QToolBar::separator {{ width: 1px; background: {k.border}; margin: {s["md"]}px {s["sm"]}px; }}

QDockWidget {{
    color: {k.text_secondary};
    font-weight: {SEMIBOLD};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {k.bg_surface};
    padding: {s["md"]}px {s["lg"]}px;
    border-bottom: 1px solid {k.border};
    /* Left-aligned: a centred dock title over a wide panel reads as a heading for the
       whole window rather than a label for the panel it belongs to. */
    text-align: left;
}}
QTabBar {{ background: {k.bg_app}; }}
QTabBar::tab {{
    background: {k.bg_app};
    color: {k.text_tertiary};
    padding: {s["sm"]}px {s["lg"]}px;
    border: none;
    border-top: 2px solid transparent;
}}
QTabBar::tab:selected {{
    background: {k.bg_surface};
    color: {k.text};
    border-top: 2px solid {k.accent};
}}
QTabBar::tab:hover:!selected {{ color: {k.text}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {k.bg_input};
    border: 1px solid {k.border_strong};
    border-radius: {RADIUS_SM}px;
    padding: {s["xs"]}px {s["md"]}px;
    selection-background-color: {k.accent_subtle};
    selection-color: {k.text};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {k.text_tertiary};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {k.accent}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {k.text_tertiary};
}}
QComboBox QAbstractItemView {{
    background: {k.bg_raised};
    border: 1px solid {k.border_strong};
    selection-background-color: {k.accent_subtle};
    selection-color: {k.text};
}}

QPushButton {{
    background: {k.bg_surface};
    color: {k.text};
    border: 1px solid {k.border_strong};
    border-radius: {RADIUS_MD}px;
    padding: {s["sm"]}px {s["lg"]}px;
}}
QPushButton:hover {{ background: {k.bg_hover}; }}
QPushButton:pressed {{ background: {k.bg_pressed}; }}
QPushButton:focus {{ border-color: {k.accent}; }}
QPushButton:disabled {{ color: {k.text_tertiary}; }}
QPushButton:default, QPushButton[variant="primary"] {{
    background: {k.accent};
    color: {k.text_on_accent};
    border: 1px solid {k.accent};
    font-weight: {SEMIBOLD};
}}
QPushButton:default:hover, QPushButton[variant="primary"]:hover {{
    background: {k.accent_hover};
    border-color: {k.accent_hover};
}}
QPushButton:default:pressed, QPushButton[variant="primary"]:pressed {{
    background: {k.accent_pressed};
}}
QPushButton:flat, QPushButton[variant="link"] {{ background: transparent; border: none; }}
QPushButton[variant="link"] {{
    color: {k.text_secondary};
    text-align: left;
    padding: {s["2xs"]}px {s["xs"]}px;
    text-decoration: underline;
}}
QPushButton[variant="link"]:hover {{ color: {k.accent_text}; }}
/* The shell, by name: ux's header, step bar, floating tools, problems drawer and
   properties panel. Their widgets carry the names and properties; the look lives here. */
QWidget#header {{ background: {k.bg_surface}; border-bottom: 1px solid {k.border}; }}
QLabel#headerTitle {{ color: {k.text}; font-weight: {SEMIBOLD}; }}
QToolButton#headerUnsaved {{
    color: {k.warning};
    background: transparent;
    border: none;
    text-decoration: underline;
}}
QWidget#workflowBar QToolButton {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_SM}px;
    color: {k.text_secondary};
}}
QWidget#workflowBar QToolButton:hover {{ background: {k.bg_hover}; }}
QWidget#workflowBar QToolButton[status="done"] {{ color: {k.text_secondary}; }}
QWidget#workflowBar QToolButton[status="current"] {{ color: {k.text}; font-weight: {SEMIBOLD}; }}
QWidget#workflowBar QToolButton[status="problem"] {{ color: {k.danger}; font-weight: {SEMIBOLD}; }}
QWidget#workflowBar QToolButton[status="todo"] {{ color: {k.text_tertiary}; }}
QPushButton[variant="primary"][problem="true"] {{
    background: {k.warning};
    border-color: {k.warning};
    color: {k.text_on_status};
}}
QFrame[floating="true"] {{
    background: {k.bg_raised};
    border: 1px solid {k.border_strong};
    border-radius: {RADIUS_LG}px;
}}
QFrame[floating="true"] QToolButton {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_SM}px;
    padding: {s["xs"]}px;
}}
QFrame[floating="true"] QToolButton:hover {{ background: {k.bg_hover}; }}
QFrame[floating="true"] QToolButton:checked {{ background: {k.accent_subtle}; color: {k.accent_text}; }}
QWidget#problemsBar {{ background: {k.bg_surface}; border-top: 1px solid {k.border}; }}
QLabel#problemsBadge[tone="danger"], QLabel#problemsBadge[tone="warning"] {{
    border-radius: 8px;
    padding: 0 {s["sm"]}px;
    font-weight: {SEMIBOLD};
}}
QLabel#problemsBadge[tone="danger"] {{ background: {k.danger}; color: {k.text_on_status}; }}
QLabel#problemsBadge[tone="warning"] {{ background: {k.warning}; color: {k.text_on_status}; }}
QWidget#propertiesPanel {{ background: {k.bg_surface}; border-left: 1px solid {k.border}; }}
QLabel[role="caption"] {{
    color: {k.text_secondary};
    font-size: {CAPTION_PX}px;
    font-weight: {SEMIBOLD};
}}

QWidget[variant="card"] {{
    background: {k.bg_raised};
    border: 1px solid {k.border};
    border-radius: {RADIUS_LG}px;
}}

/* The update strip above the board: news, not a question. */
QFrame#updateBar {{ background: {k.bg_subtle}; border-bottom: 1px solid {k.border}; }}
QFrame#updateBar QLabel#updateHeadline {{ color: {k.text}; font-weight: {SEMIBOLD}; }}
QFrame#updateBar QLabel#updateDetail {{ color: {k.text_secondary}; }}

/* Text pinned over the board (view2d.ViewOverlay). The armed mode in the accent: a
   state the user chose and can leave, not a problem. The empty board's guidance
   dim, because it is guidance, and OPAQUE, because the pad grid showing through a
   paragraph is what makes people stop reading it. */
QLabel#modeBanner {{
    background: {k.accent_subtle};
    color: {k.text};
    border: 1px solid {k.accent};
    border-radius: {RADIUS_MD}px;
    padding: {s["sm"]}px {s["lg"]}px;
}}
QLabel#emptyHint {{
    background: {k.bg_raised};
    color: {k.text_secondary};
    border: 1px solid {k.border};
    border-radius: {RADIUS_LG}px;
    padding: {s["xl"]}px {s["2xl"]}px;
}}

QTreeView, QListView, QTableView {{
    background: {k.bg_surface};
    alternate-background-color: {alternate};
    border: none;
    outline: none;
}}
QTreeView::item, QListView::item {{ padding: {s["2xs"]}px {s["xs"]}px; }}
QTreeView::item:hover, QListView::item:hover {{ background: {k.bg_hover}; }}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{
    background: {k.accent_subtle};
    color: {k.text};
}}
QDialog QListView, QDialog QTreeView, QDialog QTableView {{
    border: 1px solid {k.border};
    border-radius: {RADIUS_LG}px;
    padding: {s["xs"]}px;
}}
QHeaderView {{ background: {k.bg_surface}; }}
QHeaderView::section {{
    background: {k.bg_surface};
    color: {k.text_tertiary};
    font-size: {CAPTION_PX}px;
    padding: {s["sm"]}px {s["md"]}px;
    border: none;
    border-bottom: 1px solid {k.border};
}}

QStatusBar {{
    background: {k.bg_app};
    border-top: 1px solid {k.border};
    color: {k.text_secondary};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ padding: {s["2xs"]}px {s["md"]}px; font-size: {CAPTION_PX}px; }}

QSplitter::handle {{ background: {k.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QScrollBar:vertical, QScrollBar:horizontal {{ background: transparent; border: none; margin: 0; }}
QScrollBar:vertical {{ width: 10px; }}
QScrollBar:horizontal {{ height: 10px; }}
QScrollBar::handle {{
    background: {k.border_strong};
    border-radius: {RADIUS_SM}px;
    min-width: 28px;
    min-height: 28px;
    margin: {s["2xs"]}px;
}}
QScrollBar::handle:hover {{ background: {k.text_tertiary}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QToolTip {{
    background: {k.bg_raised};
    color: {k.text};
    border: 1px solid {k.border_strong};
    border-radius: {RADIUS_SM}px;
    padding: {s["xs"]}px {s["md"]}px;
}}
QCheckBox, QRadioButton {{ background: transparent; spacing: {s["md"]}px; }}
QGroupBox {{
    border: 1px solid {k.border};
    border-radius: {RADIUS_LG}px;
    margin-top: {s["lg"]}px;
    padding-top: {s["md"]}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: {s["md"]}px;
    padding: 0 {s["xs"]}px;
    color: {k.text_secondary};
}}
QProgressBar {{
    background: {k.bg_subtle};
    border: 1px solid {k.border};
    border-radius: {RADIUS_SM}px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {k.accent}; border-radius: {RADIUS_SM}px; }}
"""


def _box_arrows(arrows: Mapping[str, str]) -> str:
    """The combo box's and the spin box's buttons: no bevel, and the token-drawn arrows."""
    s = SPACE
    return f"""
QComboBox::drop-down {{ border: none; background: transparent; width: {s["2xl"]}px; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    border: none;
    background: transparent;
    width: {s["xl"]}px;
}}
QComboBox::down-arrow, QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({arrows["down"]});
    width: {ARROW_PX}px;
    height: {ARROW_PX}px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({arrows["up"]});
    width: {ARROW_PX}px;
    height: {ARROW_PX}px;
}}
QComboBox::down-arrow:disabled, QSpinBox::down-arrow:disabled,
QDoubleSpinBox::down-arrow:disabled {{ image: url({arrows["down-disabled"]}); }}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{
    image: url({arrows["up-disabled"]});
}}
"""


def palette(k: Tokens) -> QPalette:
    """What the stylesheet does not reach: placeholders, links, the selection Qt draws
    itself, and the parts of each widget Fusion paints from the palette."""
    result = QPalette()
    roles = {
        QPalette.ColorRole.Window: k.bg_surface,
        QPalette.ColorRole.WindowText: k.text,
        QPalette.ColorRole.Base: k.bg_input,
        QPalette.ColorRole.AlternateBase: k.bg_subtle,
        QPalette.ColorRole.Text: k.text,
        QPalette.ColorRole.Button: k.bg_surface,
        QPalette.ColorRole.ButtonText: k.text,
        QPalette.ColorRole.Highlight: k.accent_subtle,
        QPalette.ColorRole.HighlightedText: k.text,
        QPalette.ColorRole.PlaceholderText: k.text_tertiary,
        QPalette.ColorRole.ToolTipBase: k.bg_raised,
        QPalette.ColorRole.ToolTipText: k.text,
        QPalette.ColorRole.Link: k.accent_text,
        QPalette.ColorRole.LinkVisited: k.accent_text,
        QPalette.ColorRole.BrightText: k.text_on_accent,
        QPalette.ColorRole.Light: k.bg_hover,
        QPalette.ColorRole.Midlight: k.border,
        QPalette.ColorRole.Mid: k.border_strong,
        QPalette.ColorRole.Dark: k.bg_app,
        QPalette.ColorRole.Accent: k.accent,
    }
    for role, value in roles.items():
        result.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(k.text_tertiary))
    return result


def _chevron(painter: QPainter, box: QRectF, up: bool, colour: str) -> None:
    """A chevron centred in ``box``: every arrow the chrome draws."""
    half = min(box.width(), box.height(), 10.0) * 0.4
    centre = box.center()
    rise = -half / 2 if up else half / 2
    path = QPainterPath()
    path.moveTo(centre.x() - half, centre.y() - rise)
    path.lineTo(centre.x(), centre.y() + rise)
    path.lineTo(centre.x() + half, centre.y() - rise)
    pen = QPen(QColor(colour), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.restore()


#: The side of an arrow image, in logical pixels.
ARROW_PX = 10


def _arrow_images(k: Tokens, folder: Path) -> dict[str, str]:
    """The combo box's and the spin box's arrows, written as PNGs into ``folder``.

    A restyled combo or spin box draws its arrows from ``image: url(...)`` or not at all --
    Qt asks the style for nothing there -- so these are drawn by the same chevron as every
    other arrow, in this theme's colours, when the theme is applied. PNG rather than SVG
    because PNG needs no image plugin in a frozen build, with an @2x beside each that Qt
    picks on a hidpi screen.
    """
    paths: dict[str, str] = {}
    for name, up, colour in (
        ("up", True, k.text_secondary),
        ("down", False, k.text_secondary),
        ("up-disabled", True, k.text_tertiary),
        ("down-disabled", False, k.text_tertiary),
    ):
        for scale, suffix in ((1, ""), (2, "@2x")):
            image = QImage(ARROW_PX * scale, ARROW_PX * scale, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.scale(scale, scale)
            _chevron(painter, QRectF(0, 0, ARROW_PX, ARROW_PX), up, colour)
            painter.end()
            image.save(str(folder / f"{name}{suffix}.png"))
        paths[name] = (folder / f"{name}.png").as_posix()
    return paths


#: Widgets that draw an underlined access key, repainted when the cues come and go.
_SHOWS_MNEMONICS = (QMenuBar, QMenu, QAbstractButton, QLabel, QGroupBox, QTabBar)


class _Style(QProxyStyle):
    """Fusion, with two things it does differently from the native styles put back.

    Access keys are underlined only once Alt has been pressed, as Windows draws them --
    Fusion underlines every one all the time, which is most of what makes a menu bar look
    old. And the check box, the radio button and the arrows are drawn from the tokens: a
    stylesheet can only draw a tick or an arrow from an image file, and a file shipped with
    a colour in it is a second place for the palette to live (``icons.py`` says why not).
    The one place a stylesheet insists on a file -- a combo box's and a spin box's arrows,
    once their boxes are restyled -- gets one drawn from the tokens at start
    (``_arrow_images``).
    """

    def __init__(self, tokens: Tokens) -> None:
        super().__init__("Fusion")
        self.tokens = tokens
        self.cues = False

    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
        returnData: QStyleHintReturn | None = None,
    ) -> int:
        if hint == QStyle.StyleHint.SH_UnderlineShortcut:
            return int(self.cues)
        return super().styleHint(hint, option, widget, returnData)

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        if element in (
            QStyle.PrimitiveElement.PE_IndicatorCheckBox,
            QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
        ):
            self._indicator(option, painter, radio=False)
            return
        if element == QStyle.PrimitiveElement.PE_IndicatorRadioButton:
            self._indicator(option, painter, radio=True)
            return
        if element in (
            QStyle.PrimitiveElement.PE_IndicatorArrowDown,
            QStyle.PrimitiveElement.PE_IndicatorArrowUp,
        ):
            self._arrow(option, painter, up=element == QStyle.PrimitiveElement.PE_IndicatorArrowUp)
            return
        super().drawPrimitive(element, option, painter, widget)

    def _arrow(self, option: QStyleOption, painter: QPainter, up: bool) -> None:
        """A menu button's arrow, a disclosure triangle's: the same chevron as the boxes'."""
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        colour = self.tokens.text_secondary if enabled else self.tokens.text_tertiary
        _chevron(painter, QRectF(option.rect), up, colour)

    def _indicator(self, option: QStyleOption, painter: QPainter, radio: bool) -> None:
        k = self.tokens
        state = option.state
        on = bool(state & QStyle.StateFlag.State_On)
        partial = bool(state & QStyle.StateFlag.State_NoChange)
        enabled = bool(state & QStyle.StateFlag.State_Enabled)
        hover = bool(state & QStyle.StateFlag.State_MouseOver)
        filled = (on or partial) and enabled
        box = option.rect
        side = min(box.width(), box.height(), 16) - 2
        x = box.x() + (box.width() - side) / 2
        y = box.y() + (box.height() - side) / 2

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        edge = k.accent if filled or (hover and enabled) else k.border_strong
        painter.setPen(QPen(QColor(edge), 1))
        painter.setBrush(QColor(k.accent if filled else k.bg_input))
        if radio:
            painter.drawEllipse(QRectF(x + 0.5, y + 0.5, side - 1, side - 1))
        else:
            painter.drawRoundedRect(
                QRectF(x + 0.5, y + 0.5, side - 1, side - 1), RADIUS_SM, RADIUS_SM
            )
        mark = QColor(k.text_on_accent if enabled else k.text_tertiary)
        if radio and on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(mark)
            r = side * 0.2
            painter.drawEllipse(QRectF(x + side / 2 - r, y + side / 2 - r, 2 * r, 2 * r))
        elif not radio and (on or partial):
            pen = QPen(mark, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            if partial:
                path.moveTo(x + side * 0.28, y + side * 0.5)
                path.lineTo(x + side * 0.72, y + side * 0.5)
            else:
                path.moveTo(x + side * 0.25, y + side * 0.52)
                path.lineTo(x + side * 0.43, y + side * 0.7)
                path.lineTo(x + side * 0.76, y + side * 0.32)
            painter.drawPath(path)
        painter.restore()


class _KeyboardCues(QObject):
    """Turns the access-key underlines on at Alt and off at the next click, as Windows does."""

    def __init__(self, style: _Style) -> None:
        super().__init__()
        self.target = style

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.KeyPress:
            if cast(QKeyEvent, event).key() == Qt.Key.Key_Alt:
                self._show(True)
        elif kind == QEvent.Type.MouseButtonPress:
            self._show(False)
        return False

    def _show(self, on: bool) -> None:
        if self.target.cues == on:
            return
        self.target.cues = on
        for widget in QApplication.allWidgets():
            if isinstance(widget, _SHOWS_MNEMONICS) and widget.isVisible():
                widget.update()


#: The style and the cue filter, held here so Python does not collect what Qt is using.
_applied: tuple[_Style, _KeyboardCues] | None = None


def apply(app: QApplication, tokens: Tokens = ACTIVE) -> None:
    """Style the whole application: Fusion, the palette, the font and the one stylesheet.

    On the application rather than a window, so a dialog with no parent, a tooltip and a
    message box are themed too. Idempotent: every window calls it, and a test suite builds
    a great many.
    """
    global _applied
    if _applied is not None and _applied[0].tokens is tokens:
        return
    style = _Style(tokens)
    cues = _KeyboardCues(style)
    # A folder of its own, removed at exit: eight small files nobody should find later.
    folder = Path(tempfile.mkdtemp(prefix="perfboard-studio-theme-"))
    atexit.register(shutil.rmtree, folder, True)
    app.setStyle(style)
    app.setPalette(palette(tokens))
    app.setFont(font(app.font()))
    app.setStyleSheet(stylesheet(tokens, _arrow_images(tokens, folder)))
    app.installEventFilter(cues)
    if _applied is not None:
        app.removeEventFilter(_applied[1])
    _applied = (style, cues)


def font(base: QFont) -> QFont:
    """The interface face at the body size. Segoe UI Variable is the Windows 11 face, and a
    Windows 10 machine without it falls through to Segoe UI; elsewhere the desktop's own."""
    result = QFont(base)
    if sys.platform == "win32":
        result.setFamilies(["Segoe UI Variable", "Segoe UI", base.family()])
    result.setPixelSize(FONT_PX)
    return result


# The names the rest of ``ui/`` has always imported, kept pointing at the active theme while
# their call sites move to roles. New code reads the tokens or the roles above.
WINDOW = ACTIVE.bg_app
PANEL = ACTIVE.bg_surface
PANEL_ALT = ACTIVE.bg_subtle
BORDER = ACTIVE.border
TEXT = ACTIVE.text
TEXT_DIM = ACTIVE.text_secondary
ACCENT = ACTIVE.accent
ACCENT_DIM = ACTIVE.accent_subtle
#: Severity colours, shared with the DRC dock's own text so a warning reads the same
#: whether it appears in a tree, a status field or on the board.
ERROR = ACTIVE.danger
WARNING = ACTIVE.warning
OK = ACTIVE.success
