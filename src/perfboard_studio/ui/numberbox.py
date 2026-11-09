"""A number field that takes the comma a Turkish hand types.

Every number in the window is written the engine's way, with a decimal point
(``main.use_one_number_format``), and somebody who writes 2,28 by hand types the comma
anyway -- which a ``QDoubleSpinBox``'s validator swallows without a word, leaving 228.
``NumberBox`` hands the key on as the point it means.

THE FILTER IS ON THE FIELD, NOT ON THE APPLICATION. It was one application-wide event
filter: a Python call on every event the application delivered -- 11 312 of them while the
window was built, and every one after -- to catch a key typed into one kind of widget. On
the field it runs only for that field's own events. The price is that a field made as a
plain ``QDoubleSpinBox`` would turn 2,28 into 228 without a word, so none is:
``tests/test_ui.py`` reads the sources and fails on a ``QDoubleSpinBox(`` made anywhere but
here, and types a comma into every number field the window can show.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QWidget


class _CommaIsAPoint(QObject):
    """A comma typed into a number field is a decimal point."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.text() == ","
        ):
            point = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Period, event.modifiers(), ".")
            QApplication.sendEvent(watched, point)
            return True
        return super().eventFilter(watched, event)


#: The one filter, shared by every field and kept alive here.
_COMMA_IS_A_POINT: _CommaIsAPoint | None = None


def _comma_filter() -> _CommaIsAPoint:
    global _COMMA_IS_A_POINT
    if _COMMA_IS_A_POINT is None:
        _COMMA_IS_A_POINT = _CommaIsAPoint()
    return _COMMA_IS_A_POINT


class NumberBox(QDoubleSpinBox):
    """A ``QDoubleSpinBox`` that reads a typed comma as the decimal point.

    The filter goes on the line edit, which is where the keys arrive -- the box makes it
    its focus proxy -- and on the box too, for a key sent to the box itself."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        comma = _comma_filter()
        self.installEventFilter(comma)
        self.lineEdit().installEventFilter(comma)
