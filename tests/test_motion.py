"""Tests for the global motion switch (ui/motion.py) and View ▸ Reduce Motion."""

from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication

from perfboard_studio.ui import arrival, motion

from .test_ui import _close, _shown_window_without_3d


@pytest.fixture(scope="module", autouse=True)
def _qapp():
    return QApplication.instance() or QApplication(["perfboard-studio-tests"])


def test_the_suite_runs_with_reduced_motion() -> None:
    """conftest.py turns animations off for determinism."""
    assert os.environ.get(motion.REDUCE_MOTION_VARIABLE) == "1"
    assert motion.reduced() is True
    assert motion.enabled() is False
    assert motion.duration(240) == 0


def test_chosen_reduced_precedence() -> None:
    assert motion.chosen_reduced({motion.REDUCE_MOTION_VARIABLE: "1"}, False) is True
    assert motion.chosen_reduced({motion.REDUCE_MOTION_VARIABLE: "0"}, True) is False
    assert (
        motion.chosen_reduced(
            {motion.REDUCE_MOTION_VARIABLE: "0", "QT_QPA_PLATFORM": "offscreen"}, False
        )
        is False
    )
    assert motion.chosen_reduced({"QT_QPA_PLATFORM": "offscreen"}, False) is True
    assert motion.chosen_reduced({}, True) is True
    assert motion.chosen_reduced({}, "true") is True
    assert motion.chosen_reduced({}, False) is False
    assert motion.chosen_reduced({}, None) is False


def test_set_reduced_toggles_live_and_resets() -> None:
    motion.set_reduced(False)
    assert motion.enabled() is True
    assert motion.duration(240) == 240
    motion.set_reduced(True)
    assert motion.enabled() is False
    assert motion.duration(240) == 0
    motion.reset()
    assert motion.reduced() is True


def test_flip_skips_curtain_when_motion_is_reduced(monkeypatch) -> None:
    window = _shown_window_without_3d(monkeypatch)
    try:
        assert motion.reduced() is True
        window.on_flip_board()
        assert window.view._curtain is None
        assert window.side == "bottom" and window.scene.side == "bottom"
    finally:
        _close(window)


def test_arrival_skips_when_motion_is_reduced() -> None:
    class _StubActor:
        def GetPosition(self) -> tuple[float, float, float]:
            return (0.0, 0.0, 0.0)

        def SetPosition(self, x: float, y: float, z: float) -> None:
            pass

    anim = arrival.ArrivalAnimation()
    assert motion.reduced() is True
    assert anim.start([_StubActor()], 15.0, lambda: None) is False
    assert not anim.running


def test_view_menu_reduce_motion_toggles_live_and_persists(monkeypatch) -> None:
    from perfboard_studio.ui import main as main_module

    window = _shown_window_without_3d(monkeypatch)
    try:
        assert window.act_reduce_motion.isChecked() is True
        window.act_reduce_motion.setChecked(False)
        assert motion.enabled() is True
        assert main_module.app_settings().value(motion.REDUCE_MOTION_KEY) in (False, "false")
        window.act_reduce_motion.setChecked(True)
        assert motion.reduced() is True
        assert main_module.app_settings().value(motion.REDUCE_MOTION_KEY) in (True, "true")
    finally:
        _close(window)
