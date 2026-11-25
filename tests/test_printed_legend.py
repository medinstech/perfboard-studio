"""A legend in the board's own numbering (#13): what a board prints is not always the address.

An 8 × 12 cm board prints A..Z and then A..P again along its long edge and A..Z then 1..4
along the short one; a Protopatch prints numbers on both axes and marks every fifth hole.
``BoardLabels.columns`` / ``rows`` say what such a board prints, ``geometry.printed_label``
is what every renderer of the legend draws, and the addresses themselves never move --
which is what the first group below holds before anything else is asked.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from perfboard_studio import persist
from perfboard_studio.command import CommandBus, CommandContext, create_id_generator
from perfboard_studio.commands import (
    DEFAULT_BOARD,
    SetBoardPayload,
    create_empty_document,
    create_standard_registry,
)
from perfboard_studio.footprints import footprint_lookup
from perfboard_studio.geometry import (
    LEGEND_LETTER_STYLES,
    column_label,
    legend_label,
    legend_problem,
    legend_run_spans,
    legend_runs_text,
    parse_legend_runs,
    printed_label,
    printed_row_label,
)
from perfboard_studio.guide import GuideOptions, build_guide
from perfboard_studio.mcp.session import BoardSession
from perfboard_studio.model import AxisLegend, BoardLabels, DocumentMeta, PerfDocument

from .test_gl import requires_offscreen_gl

META = DocumentMeta(name="legend", created="2026-01-01", modified="2026-01-01")
LOOKUP = footprint_lookup()

#: The issue's 8 × 12 cm board: 42 columns printed A..Z, A..P and 30 rows printed A..Z, 1..4.
EIGHT_BY_TWELVE = BoardLabels(
    row_digits=2,
    columns=AxisLegend(runs=(("A", "Z"), ("A", "P"))),
    rows=AxisLegend(runs=(("A", "Z"), ("1", "4"))),
)
#: Numbers both ways, every fifth marked, two digits.
PROTOPATCH = BoardLabels(
    columns=AxisLegend(runs=(("1", "60"),), every=5, digits=2),
    rows=AxisLegend(runs=(("1", "40"),), every=5, digits=2),
)


def _doc(labels: BoardLabels | None, cols: int = 42, rows: int = 30) -> PerfDocument:
    board = dataclasses.replace(DEFAULT_BOARD, cols=cols, rows=rows, labels=labels)
    return create_empty_document(META, board)


def _bus(doc: PerfDocument) -> CommandBus:
    return CommandBus(doc, create_standard_registry(), CommandContext(next_id=create_id_generator()))


# -- a board that prints the addresses prints exactly what it printed before ---------------


@pytest.mark.parametrize("labels", [BoardLabels(), BoardLabels(row_digits=2)])
def test_with_no_numbering_of_its_own_the_legend_is_the_addresses(labels: BoardLabels) -> None:
    """Every board modelled before this prints the addresses; the one function the
    renderers now draw from must give them exactly what the two old ones did."""
    for index in range(60):
        assert printed_label("columns", index, labels) == column_label(index)
        assert printed_label("rows", index, labels) == printed_row_label(index, labels)


# -- a board that counts its own way -------------------------------------------------------


def test_the_eight_by_twelve_board_prints_its_runs_again_from_the_start() -> None:
    columns = [printed_label("columns", i, EIGHT_BY_TWELVE) for i in range(42)]
    assert columns[:26] == [column_label(i) for i in range(26)]
    assert columns[26:] == [column_label(i) for i in range(16)]  # A..P a second time
    rows = [printed_label("rows", i, EIGHT_BY_TWELVE) for i in range(30)]
    assert rows[:26] == [column_label(i) for i in range(26)]
    # Its own digits, not row_digits: that is the padding of the addresses' numbers.
    assert rows[26:] == ["1", "2", "3", "4"]


def test_a_board_that_marks_every_fifth_hole_prints_only_those() -> None:
    printed = {i: printed_label("columns", i, PROTOPATCH) for i in range(60)}
    assert {i: text for i, text in printed.items() if text is not None} == {
        i: f"{i + 1:02d}" for i in range(4, 60, 5)
    }
    # ...and the hole between the marks still has its number in that numbering, which is
    # what a person counting from "05" arrives at.
    assert legend_label("columns", 6, PROTOPATCH) == "07"


def test_past_the_last_run_nothing_is_printed() -> None:
    assert printed_label("columns", 41, EIGHT_BY_TWELVE) == "P"
    assert printed_label("columns", 42, EIGHT_BY_TWELVE) is None
    assert legend_label("rows", 30, EIGHT_BY_TWELVE) is None
    assert legend_label("rows", -1, EIGHT_BY_TWELVE) is None


def test_a_run_is_cut_where_the_board_ends() -> None:
    assert legend_run_spans(EIGHT_BY_TWELVE.columns, 30) == ((0, 25), (26, 29))  # type: ignore[arg-type]
    assert legend_run_spans(EIGHT_BY_TWELVE.columns, 20) == ((0, 19),)  # type: ignore[arg-type]


# -- written the way a person writes it ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "runs"),
    [
        ("A-Z, A-P", (("A", "Z"), ("A", "P"))),
        ("a – z  1—4", (("A", "Z"), ("1", "4"))),
        ("A - Z; AA - AP", (("A", "Z"), ("AA", "AP"))),
        ("1-60", (("1", "60"),)),
        ("7", (("7", "7"),)),
    ],
)
def test_runs_are_read_as_people_write_them(text: str, runs: tuple[tuple[str, str], ...]) -> None:
    assert parse_legend_runs(text) == runs
    assert parse_legend_runs(legend_runs_text(runs)) == runs


@pytest.mark.parametrize("text", ["", "Z-A", "A-4", "AAAA-B", "-", "A-Z, 9-1", "1.5-3"])
def test_a_run_no_board_could_print_is_refused_with_a_reason(text: str) -> None:
    with pytest.raises(ValueError, match=r"\w"):
        parse_legend_runs(text)


# -- refused in one sentence, by the command and by the file ------------------------------

BAD_LEGENDS = [
    BoardLabels(columns=AxisLegend(runs=())),
    BoardLabels(rows=AxisLegend(runs=(("Z", "A"),))),
    BoardLabels(rows=AxisLegend(runs=(("A", "4"),))),
    BoardLabels(columns=AxisLegend(runs=(("1", "9"),), every=0)),
    BoardLabels(columns=AxisLegend(runs=(("1", "9"),), digits=0)),
    BoardLabels(columns=AxisLegend(runs=(("1", "9"),), digits=9)),
]


@pytest.mark.parametrize("labels", BAD_LEGENDS)
def test_board_set_and_the_file_refuse_the_same_legend_in_the_same_words(labels: BoardLabels) -> None:
    problem = legend_problem(labels)
    assert problem is not None
    result = _bus(_doc(None)).dispatch(
        "board.set", SetBoardPayload(board=dataclasses.replace(DEFAULT_BOARD, labels=labels))
    )
    assert not result.ok and result.code == "invalid-board" and result.message == problem

    # The same board in a file, which the writer does not stop -- it is a hand edit's job
    # to get one there -- does not open.
    text = persist.serialize_document(_doc(labels))
    loaded = persist.deserialize_document(text)
    assert not loaded.ok
    assert loaded.message == problem


@pytest.mark.parametrize("labels", [EIGHT_BY_TWELVE, PROTOPATCH])
def test_a_legend_any_board_can_print_is_taken(labels: BoardLabels) -> None:
    assert legend_problem(labels) is None
    result = _bus(_doc(None)).dispatch(
        "board.set",
        SetBoardPayload(board=dataclasses.replace(DEFAULT_BOARD, cols=42, rows=30, labels=labels)),
    )
    assert result.ok
    assert result.document.board.labels == labels


# -- in the file -------------------------------------------------------------------------


def test_the_file_carries_the_runs_and_only_what_is_not_a_default() -> None:
    text = persist.serialize_document(_doc(EIGHT_BY_TWELVE))
    labels = json.loads(text)["board"]["labels"]
    assert labels["columns"] == {"runs": [["A", "Z"], ["A", "P"]]}
    assert labels["rows"] == {"runs": [["A", "Z"], ["1", "4"]]}
    protopatch = json.loads(persist.serialize_document(_doc(PROTOPATCH)))["board"]["labels"]
    assert protopatch["columns"] == {"runs": [["1", "60"]], "every": 5, "digits": 2}

    for labels_in in (EIGHT_BY_TWELVE, PROTOPATCH):
        doc = _doc(labels_in)
        again = persist.deserialize_document(persist.serialize_document(doc))
        assert again.ok and again.document == doc
        assert persist.serialize_document(again.document) == persist.serialize_document(doc)


def test_a_legend_of_the_addresses_writes_no_new_key() -> None:
    """The stripAxis rule: every board that prints the addresses keeps its bytes."""
    labels = json.loads(persist.serialize_document(_doc(BoardLabels(row_digits=2))))["board"][
        "labels"
    ]
    assert set(labels) == {"face", "rowDigits", "allEdges"}


def test_a_run_that_is_not_a_pair_does_not_load() -> None:
    data = json.loads(persist.serialize_document(_doc(EIGHT_BY_TWELVE)))
    data["board"]["labels"]["columns"]["runs"] = [["A", "Z", "Q"]]
    loaded = persist.deserialize_document(json.dumps(data, indent=2))
    assert not loaded.ok
    assert loaded.path == "board.labels.columns.runs[0]"


# -- said where it is used ---------------------------------------------------------------


def _preparation(doc: PerfDocument, language: str = "en") -> str:
    guide = build_guide(doc, LOOKUP, GuideOptions(language=language))  # type: ignore[arg-type]
    return guide.phases[0].summary


def test_the_guide_says_once_how_the_boards_numbering_lines_up_with_its_own() -> None:
    said = _preparation(_doc(EIGHT_BY_TWELVE))
    assert "check which corner the board's own numbering starts in" in said
    assert (
        "This board prints a numbering of its own, and this guide keeps to its own addresses "
        "— the columns: A–Z are printed A–Z, AA–AP are printed A–P; the rows: 1–26 are "
        "printed A–Z, 27–30 are printed 1–4."
    ) in said
    turkish = _preparation(_doc(EIGHT_BY_TWELVE), "tr")
    assert "sütunlarda A–Z kartta A–Z olarak basılı, AA–AP kartta A–P olarak basılı" in turkish


def test_the_guide_names_the_marks_and_the_holes_past_the_last_run() -> None:
    said = _preparation(_doc(PROTOPATCH, cols=62, rows=40))
    assert (
        "the columns: A–BH are printed 01–60, with a mark every 5 holes, BI–BJ are not printed"
    ) in said
    assert "the rows: 1–40 are printed 01–40, with a mark every 5 holes." in said


def test_a_board_printing_the_addresses_is_told_nothing_new() -> None:
    said = _preparation(_doc(BoardLabels(row_digits=2)))
    assert "check which corner the board's printed A1 is in" in said
    assert "numbering of its own" not in said


def test_the_screen_and_the_one_to_one_print_show_what_the_board_prints(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The 2D legend, which the 1:1 PDF is a render of, reads ``printed_label`` too.

    Recorded at the call rather than read off pixels, for the reason test_ui's legend tests
    give: on a Qt platform with no font database nothing that small is drawn at all.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui import view2d

    QApplication.instance() or QApplication([])
    said: list[str] = []
    real = view2d.draw_physical_label

    def record(painter, centre, text, height_mm, *args, **kwargs):  # type: ignore[no-untyped-def]
        said.append(text)
        return real(painter, centre, text, height_mm, *args, **kwargs)

    monkeypatch.setattr(view2d, "draw_physical_label", record)

    def drawn(doc: PerfDocument) -> list[str]:
        said.clear()
        scene = view2d.BoardScene(doc, LOOKUP, show_rulers=False, show_ratsnest=False)
        rect = scene.sceneRect()
        image = QImage(int(rect.width() * 4), int(rect.height() * 4), QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        scene.render(painter, QRectF(0, 0, image.width(), image.height()), rect)
        painter.end()
        return list(said)

    letters = [column_label(i) for i in range(26)]
    eight = dataclasses.replace(EIGHT_BY_TWELVE, face="top", all_edges=False)
    assert drawn(_doc(eight)) == letters + letters[:16] + letters + ["1", "2", "3", "4"]
    protopatch = dataclasses.replace(PROTOPATCH, face="top", all_edges=False)
    assert drawn(_doc(protopatch, 62, 40)) == (
        [f"{i:02d}" for i in range(5, 61, 5)] + [f"{i:02d}" for i in range(5, 41, 5)]
    )


def test_a_board_printing_its_own_numbering_keeps_the_ruler() -> None:
    """The ruler is hidden where the board prints the addresses, because it would say them
    twice. A board printing A..P a second time does not say them at all, and then the ruler
    is what says AA."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from perfboard_studio.ui import view2d

    QApplication.instance() or QApplication([])
    for labels, readable in (
        (BoardLabels(row_digits=2), True),
        (EIGHT_BY_TWELVE, False),
        (dataclasses.replace(BoardLabels(), rows=PROTOPATCH.rows), False),
    ):
        scene = view2d.BoardScene(_doc(labels), LOOKUP)
        assert scene.legend_is_readable() is readable
        rulers = [item for item in scene.items() if isinstance(item, view2d.HoleRulerItem)]
        assert bool(rulers) is not readable


@requires_offscreen_gl
def test_the_3d_board_prints_what_the_board_in_hand_prints(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The 3D legend reads ``printed_label`` like the 2D one: a second A..P along the top,
    letters down the side, and nothing beside a hole a board leaves unmarked."""
    from perfboard_studio.ui import view3d

    said: list[str] = []
    real = view3d._glyphs

    def recording(text: str, bold: bool = True):  # type: ignore[no-untyped-def]
        said.append(text)
        return real(text, bold)

    monkeypatch.setattr(view3d, "_glyphs", recording)
    # One face and one edge each, so every label is said once: the columns, then the rows.
    labels = dataclasses.replace(EIGHT_BY_TWELVE, face="top", all_edges=False)
    view3d.build_legend(_doc(labels))
    letters = [column_label(i) for i in range(26)]
    assert said == letters + letters[:16] + letters + ["1", "2", "3", "4"]

    said.clear()
    view3d.build_legend(_doc(dataclasses.replace(PROTOPATCH, face="top", all_edges=False), 62, 40))
    assert said == [f"{i:02d}" for i in range(5, 61, 5)] + [f"{i:02d}" for i in range(5, 41, 5)]


def test_an_agent_is_told_what_the_board_prints() -> None:
    info = BoardSession(document=_doc(PROTOPATCH, cols=60, rows=40)).get_board_info()
    assert info["printed_legend"]["columns"] == {"printed": "1–60", "every": 5, "digits": 2}
    assert info["top_left_hole"] == "A1"  # the addresses are still the tool's own


# -- doubled letters past Z (#16) --------------------------------------------------------

#: A board that prints A..Z and then AA, BB, .. along its long edge.
DOUBLED = BoardLabels(columns=AxisLegend(runs=(("A", "ZZ"),), letters="doubled"))


def test_doubled_letters_go_on_past_z_one_letter_repeated() -> None:
    printed = [legend_label("columns", i, DOUBLED) for i in range(60)]
    assert printed[:3] == ["A", "B", "C"]
    assert printed[25:29] == ["Z", "AA", "BB", "CC"]
    assert printed[51] == "ZZ"
    assert printed[52:] == [None] * 8  # past the run's end
    # The addresses are still the tool's own: the 28th column is AB, printed BB.
    assert column_label(27) == "AB"


def test_doubled_letters_carry_on_to_three_and_are_read_back_as_written() -> None:
    labels = BoardLabels(columns=AxisLegend(runs=(("AA", "CCC"),), letters="doubled"))
    printed = [legend_label("columns", i, labels) for i in range(56)]
    assert printed[0] == "AA" and printed[25] == "ZZ" and printed[26] == "AAA"
    assert printed[28] == "CCC" and printed[29] is None


def test_one_run_means_different_holes_in_each_style() -> None:
    spreadsheet = AxisLegend(runs=(("AA", "ZZ"),))
    doubled = dataclasses.replace(spreadsheet, letters="doubled")
    assert legend_run_spans(spreadsheet, 1000) == ((0, 675),)
    assert legend_run_spans(doubled, 1000) == ((0, 25),)


def test_parse_reads_runs_in_the_style_asked_for() -> None:
    assert parse_legend_runs("A-Z, AA-PP", "doubled") == (("A", "Z"), ("AA", "PP"))
    assert parse_legend_runs("AB-CC") == (("AB", "CC"),)
    with pytest.raises(ValueError, match="one letter repeated"):
        parse_legend_runs("AB-CC", "doubled")
    with pytest.raises(ValueError, match="backwards"):
        parse_legend_runs("BB-AA", "doubled")


@pytest.mark.parametrize(
    "labels",
    [
        BoardLabels(columns=AxisLegend(runs=(("AB", "CC"),), letters="doubled")),
        BoardLabels(rows=AxisLegend(runs=(("A", "Z"),), letters="tripled")),  # type: ignore[arg-type]
    ],
)
def test_board_set_and_the_file_refuse_a_doubled_legend_in_the_same_words(labels: BoardLabels) -> None:
    test_board_set_and_the_file_refuse_the_same_legend_in_the_same_words(labels)


def test_the_file_carries_doubled_and_leaves_the_default_out() -> None:
    doc = _doc(DOUBLED, cols=60)
    data = json.loads(persist.serialize_document(doc))
    assert data["board"]["labels"]["columns"] == {"runs": [["A", "ZZ"]], "letters": "doubled"}
    again = persist.deserialize_document(persist.serialize_document(doc))
    assert again.ok and again.document == doc
    assert "letters" not in json.loads(persist.serialize_document(_doc(EIGHT_BY_TWELVE)))["board"][
        "labels"
    ]["columns"]
    assert LEGEND_LETTER_STYLES == ("spreadsheet", "doubled")


def test_the_guide_says_the_doubled_letters_the_board_prints() -> None:
    """Thirty columns: the guide's A..AD are the board's A..Z, AA, BB, CC, DD."""
    summary = _preparation(_doc(DOUBLED, cols=30, rows=10))
    assert "A–AD are printed A–DD" in summary, summary


def test_an_agent_is_told_the_letters_go_on_doubled() -> None:
    info = BoardSession(document=_doc(DOUBLED, cols=60, rows=10)).get_board_info()
    assert info["printed_legend"]["columns"] == {
        "printed": "A–ZZ", "every": 1, "digits": 1, "letters": "doubled",
    }


def test_a_board_family_saved_with_doubled_letters_comes_back_with_them() -> None:
    from perfboard_studio.boardfamily import (
        GREEN_DOUBLE_SIDED,
        family_from_json,
        family_to_json,
    )

    legend = GREEN_DOUBLE_SIDED.legend
    assert legend is not None
    family = dataclasses.replace(
        GREEN_DOUBLE_SIDED,
        legend=dataclasses.replace(legend, columns=DOUBLED.columns),
    )
    assert family_from_json(family_to_json(family)) == family
