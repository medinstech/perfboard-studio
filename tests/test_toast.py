"""Tests for floating toast notifications (src/perfboard_studio/ui/toast.py)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from perfboard_studio.ui import motion
from perfboard_studio.ui.toast import MAX_VISIBLE, ToastHost


def _app() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


def test_toast_stack_caps_at_max_visible_and_reflows_on_dismiss() -> None:
    _app()
    host_widget = QWidget()
    host_widget.resize(900, 600)
    host_widget.show()
    host = ToastHost(host_widget)
    try:
        t1 = host.show_toast("First", kind="info", duration_ms=0)
        t2 = host.show_toast("Second", kind="success", duration_ms=0)
        t3 = host.show_toast("Third", kind="warning", duration_ms=0)
        assert len(host.cards) == MAX_VISIBLE
        # Stacked bottom-to-top: newest sits lower than older.
        assert t3.y() > t2.y() > t1.y()

        t4 = host.show_toast("Fourth", kind="danger", duration_ms=0)
        assert len(host.cards) == MAX_VISIBLE
        assert t1 not in host.cards
        assert host.cards == (t2, t3, t4)

        old_t3_y = t3.y()
        t4.dismiss()
        assert host.cards == (t2, t3)
        assert t3.y() > old_t3_y
    finally:
        host.clear()
        host_widget.close()


def test_toast_action_runs_callback_and_dismisses() -> None:
    _app()
    host_widget = QWidget()
    host_widget.resize(800, 500)
    host_widget.show()
    host = ToastHost(host_widget)
    fired: list[str] = []
    try:
        card = host.show_toast(
            "Wired 8 nets",
            kind="success",
            duration_ms=0,
            action_label="Undo",
            action=lambda: fired.append("undo"),
        )
        assert card.action_button is not None
        card.action_button.click()
        assert fired == ["undo"]
        assert len(host.cards) == 0
    finally:
        host.clear()
        host_widget.close()


def test_toast_hover_pauses_auto_dismiss_and_animates_with_motion() -> None:
    _app()
    motion.set_reduced(False)
    host_widget = QWidget()
    host_widget.resize(800, 500)
    host_widget.show()
    host = ToastHost(host_widget)
    try:
        card = host.show_toast("Saved", kind="success", duration_ms=120)
        assert card._anim is not None
        card.enterEvent(QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(10, 10)))
        assert not card._timer.isActive()
        QTest.qWait(180)
        assert card in host.cards, "hovering pauses auto-dismiss"

        card.leaveEvent(QEvent(QEvent.Type.Leave))
        assert card._timer.isActive()
        card.dismiss()
        for _ in range(25):
            QTest.qWait(15)
            if card not in host.cards:
                break
        assert card not in host.cards
    finally:
        host.clear()
        host_widget.close()
        motion.reset()


def test_main_window_notify_mirrors_status_bar_and_triggers_undo_action(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pathlib import Path

    from perfboard_studio import persist
    from perfboard_studio.ui.main import MainWindow

    _app()
    root = Path(__file__).resolve().parents[1]
    loaded = persist.parse_document_or_throw(
        (root / "examples" / "ne555-astable.perf").read_text(encoding="utf-8")
    )
    window = MainWindow(loaded)
    try:
        save_path = tmp_path / "demo.perf"
        assert window._save_to(save_path) is True
        assert window.toasts.cards
        assert window.toasts.cards[-1].kind == "success"
        assert save_path.name in window.toasts.cards[-1].message
        assert str(save_path) in window.statusBar().currentMessage()

        window.on_schematic_auto_layout()
        latest = window.toasts.cards[-1]
        assert latest.action_button is not None
        assert latest.action_button.text() == "Undo"
        before_undo = window.bus.document
        latest.action_button.click()
        assert window.bus.document is not before_undo
    finally:
        window.toasts.clear()
        window.close()
