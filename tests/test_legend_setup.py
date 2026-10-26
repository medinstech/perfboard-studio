"""Board Setup sets a board's own printed numbering, and the hover says it (#13).

The engine half -- what is printed, what is refused, what the guide says -- is in
test_printed_legend.py. This is the window: the fields that set it, the one sentence that
holds OK off while it is wrong, OK keeping what the dialog does not ask about, and the
hole under the pointer.
"""

from __future__ import annotations

import dataclasses
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from perfboard_studio.commands import DEFAULT_BOARD, create_empty_document
from perfboard_studio.geometry import parse_legend_runs
from perfboard_studio.model import AxisLegend, BoardLabels, DocumentMeta, PerfDocument
from perfboard_studio.ui.main import BoardSetupDialog

META = DocumentMeta(name="legend", created="2026-01-01", modified="2026-01-01")
#: 42 × 30 holes printed A..Z, A..P along and A..Z, 1..4 down: the issue's 8 × 12 cm board.
BOARD = dataclasses.replace(
    DEFAULT_BOARD,
    cols=42,
    rows=30,
    border_x_mm=2.0,
    border_y_mm=2.0,
    labels=BoardLabels(
        row_digits=2,
        columns=AxisLegend(runs=(("A", "Z"), ("A", "P"))),
        rows=AxisLegend(runs=(("A", "Z"), ("1", "4"))),
    ),
)


@pytest.fixture(scope="module", autouse=True)
def qapp():  # type: ignore[no-untyped-def]
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def test_the_dialog_opens_on_the_numbering_the_board_has() -> None:
    dialog = BoardSetupDialog(BOARD)
    assert dialog.legend_columns.runs.text() == "A–Z, A–P"
    assert dialog.legend_rows.runs.text() == "A–Z, 1–4"
    assert dialog.board().labels == BOARD.labels


def test_what_is_typed_is_what_ok_gives() -> None:
    dialog = BoardSetupDialog(dataclasses.replace(BOARD, labels=BoardLabels(row_digits=2)))
    dialog.legend_columns.runs.setText("1-60")
    dialog.legend_columns.every.setValue(5)
    dialog.legend_columns.digits.setValue(2)
    labels = dialog.board().labels
    assert labels is not None
    assert labels.columns == AxisLegend(runs=(("1", "60"),), every=5, digits=2)
    assert labels.rows is None  # left empty: the row numbers


def test_ok_keeps_the_face_and_the_edges_it_does_not_ask_about() -> None:
    """OK rebuilt the legend from nothing, which put a board printed on one face along one
    edge back to both faces and all four edges every time the dialog was closed."""
    labels = dataclasses.replace(BOARD.labels, face="top", all_edges=False)  # type: ignore[arg-type]
    dialog = BoardSetupDialog(dataclasses.replace(BOARD, labels=labels))
    kept = dialog.board().labels
    assert kept is not None and kept.face == "top" and kept.all_edges is False


def test_a_numbering_no_board_could_print_holds_ok_off_in_the_engines_words() -> None:
    dialog = BoardSetupDialog(BOARD)
    ok = dialog._ok_button
    assert ok is not None and ok.isEnabled()
    assert dialog.legend_error.isHidden()

    dialog.legend_rows.runs.setText("Z-A")
    assert not ok.isEnabled()
    assert not dialog.legend_error.isHidden()
    # The engine's sentence, word for word: the one a .perf file or an agent is told.
    with pytest.raises(ValueError) as raised:
        parse_legend_runs("Z-A")
    assert dialog.legend_error.text() == str(raised.value)

    dialog.legend_rows.runs.setText("A-Z, 1-4")
    assert ok.isEnabled() and dialog.legend_error.isHidden()


def test_the_reason_is_said_in_the_windows_language() -> None:
    """The engine's sentence through ``engine_text.say``, like every refusal the window
    shows: in a Turkish window it was the one English line in the dialog."""
    from perfboard_studio.ui.i18n import set_language

    set_language("tr")
    try:
        dialog = BoardSetupDialog(BOARD)
        dialog.legend_rows.runs.setText("Z-A")
        assert dialog.legend_error.text() == "Z–A basılamaz: geriye doğru sayıyor."
        dialog.legend_rows.runs.setText("A-4")
        assert dialog.legend_error.text().startswith("A–4 basılamaz: bir dizi ya büyük harften")
    finally:
        set_language("en")


def test_only_one_digits_is_asked_for_the_rows_and_only_beside_a_run() -> None:
    """Row digits pads the row NUMBERS, so it goes while the rows print a numbering of their
    own and comes back when they print the numbers; and an empty run's two spin boxes are
    greyed, because they describe nothing."""
    dialog = BoardSetupDialog(BOARD)
    form = dialog._advanced_form
    assert not form.isRowVisible(dialog.row_digits)  # the rows print A..Z, 1..4
    dialog.legend_rows.runs.setText("")
    assert form.isRowVisible(dialog.row_digits)
    assert not dialog.legend_rows.every.isEnabled() and not dialog.legend_rows.digits.isEnabled()
    assert dialog.legend_columns.every.isEnabled()
    dialog.legend_rows.runs.setText("1-30")
    assert not form.isRowVisible(dialog.row_digits)
    assert dialog.legend_rows.every.isEnabled()
    # The error is a row of its own, shown only with something in it.
    assert not form.isRowVisible(dialog.legend_error)
    dialog.legend_rows.runs.setText("30-1")
    assert form.isRowVisible(dialog.legend_error)


def test_the_numbering_is_asked_only_of_a_board_with_a_legend() -> None:
    dialog = BoardSetupDialog(BOARD)
    form = dialog._advanced_form
    assert form.isRowVisible(dialog.legend_columns.row)
    dialog.legend.setChecked(False)
    assert not form.isRowVisible(dialog.legend_columns.row)
    assert not form.isRowVisible(dialog.legend_rows.row)
    # ...and a wrong field cannot hold OK off for a legend that is not there.
    dialog.legend_rows.runs.setText("Z-A")
    assert dialog._ok_button is not None and dialog._ok_button.isEnabled()
    assert dialog.board().labels is None


def test_a_stocked_size_brings_back_the_addresses() -> None:
    dialog = BoardSetupDialog(BOARD)
    index = next(i for i in range(dialog.preset.count()) if dialog.preset.itemData(i))
    dialog.preset.setCurrentIndex(index)
    assert dialog.legend_columns.runs.text() == ""
    labels = dialog.board().labels
    assert labels is None or (labels.columns is None and labels.rows is None)


# -- the hole under the pointer ------------------------------------------------------------


@pytest.fixture
def window(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import autosave as autosave_module
    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    monkeypatch.setattr(autosave_module, "default_directory", lambda: tmp_path / "recovery")
    made = main_module.MainWindow(_document(BOARD))
    yield made
    made._saved_document = made.bus.document
    made.close()


def _document(board: object) -> PerfDocument:
    return create_empty_document(META, board)  # type: ignore[arg-type]


def test_the_hole_under_the_pointer_says_what_the_board_has_printed_there(window) -> None:  # type: ignore[no-untyped-def]
    window._on_hovered_hole(26, 6)  # AA7: the second run's A, and G down the side
    text = window.label_hole.text()
    assert "<b>AA7</b>" in text and "printed A·G" in text
    window._on_hovered_hole(41, 29)  # AP30
    assert "printed P·4" in window.label_hole.text()


def test_a_board_printing_the_addresses_is_not_told_them_twice(window) -> None:  # type: ignore[no-untyped-def]
    plain = dataclasses.replace(BOARD, labels=BoardLabels(row_digits=2))
    window.bus.dispatch("board.set", _set(plain))
    window._on_hovered_hole(26, 6)
    assert "printed" not in window.label_hole.text()


def _set(board: object):  # type: ignore[no-untyped-def]
    from perfboard_studio.commands import SetBoardPayload

    return SetBoardPayload(board=board)  # type: ignore[arg-type]
