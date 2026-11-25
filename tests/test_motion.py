"""Tests for the global motion switch (ui/motion.py) and View ▸ Reduce Motion."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

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


def test_a_window_built_offscreen_with_no_variable_stays_still(monkeypatch) -> None:
    """With the variable unset, an offscreen window on a profile that stored "animate"
    still comes up reduced: rule 3 (offscreen) outranks the stored choice, as in
    ``motion.reduced``. The window used to install the stored choice as a live override,
    so every screenshot script on a fresh profile captured its windows mid-animation."""
    from perfboard_studio.ui import main as main_module

    monkeypatch.delenv(motion.REDUCE_MOTION_VARIABLE, raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    main_module.app_settings().setValue(motion.REDUCE_MOTION_KEY, False)
    motion.reset()
    window = _shown_window_without_3d(monkeypatch)
    try:
        assert motion.reduced() is True
        assert window.act_reduce_motion.isChecked() is True
    finally:
        _close(window)
        main_module.app_settings().remove(motion.REDUCE_MOTION_KEY)


def test_closing_an_offscreen_window_does_not_overwrite_stored_motion(monkeypatch) -> None:
    """An offscreen window ticks Reduce Motion from the environment; closing it must not
    write that forced True back to the stored setting and silently turn animations off on
    the next normal launch."""
    from perfboard_studio.ui import main as main_module

    monkeypatch.delenv(motion.REDUCE_MOTION_VARIABLE, raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    main_module.app_settings().setValue(motion.REDUCE_MOTION_KEY, False)
    motion.reset()
    window = _shown_window_without_3d(monkeypatch)
    try:
        assert motion.reduced() is True
        assert window.act_reduce_motion.isChecked() is True
        _close(window)
        assert main_module.app_settings().value(motion.REDUCE_MOTION_KEY) in (False, "false")
    finally:
        if window.isVisible():
            _close(window)
        main_module.app_settings().remove(motion.REDUCE_MOTION_KEY)
        motion.reset()


#: What an interface animation is built from: Qt's animation classes, and the clock a
#: hand-written, timer-driven tween reads (``arrival.ArrivalAnimation``).
_ANIMATION_TYPES = (
    "QPropertyAnimation",
    "QVariantAnimation",
    "QTimeLine",
    "QParallelAnimationGroup",
    "QSequentialAnimationGroup",
    "QElapsedTimer",
)
_BUILDS_ANIMATION = re.compile(r"\b(?:" + "|".join(_ANIMATION_TYPES) + r")\(")
_ASKS_MOTION = re.compile(r"\bmotion\.(?:reduced|enabled|duration)\(")


def _functions_in(tree: ast.AST) -> list[tuple[ast.FunctionDef, ast.ClassDef | None]]:
    found: list[tuple[ast.FunctionDef, ast.ClassDef | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            found.extend((item, node) for item in node.body if isinstance(item, ast.FunctionDef))
    methods = {id(f) for f, _ in found}
    found.extend(
        (node, None)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and id(node) not in methods
    )
    return found


def test_every_animation_asks_motion_first() -> None:
    """View ▸ Reduce Motion is one switch only if every animation asks it, and nothing
    else would make a new one ask (``motion.py``'s promise was written before most of the
    animations were). A function that builds one passes if it asks ``motion`` itself, or
    its class does (the gate in ``start``); otherwise its class is an animation in its own
    right, and every place that builds THAT must ask -- the board's flip curtain, built
    only once ``turn_over`` has asked."""
    ui = Path(motion.__file__).parent
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(ui.glob("*.py"))
        if path.name != "motion.py"
    }
    ungated_classes: dict[str, str] = {}
    gated_sites = 0
    for name, source in sources.items():
        tree = ast.parse(source)
        for function, owner in _functions_in(tree):
            text = ast.get_source_segment(source, function) or ""
            if not _BUILDS_ANIMATION.search(text):
                continue
            owner_text = (ast.get_source_segment(source, owner) or "") if owner else ""
            if _ASKS_MOTION.search(text) or _ASKS_MOTION.search(owner_text):
                gated_sites += 1
                continue
            assert owner is not None, (
                f"{name}:{function.lineno} {function.name} builds an animation and never "
                "asks motion.reduced()"
            )
            ungated_classes[owner.name] = f"{name}:{function.lineno}"
    unasked: list[str] = []
    for class_name, where in ungated_classes.items():
        built = re.compile(rf"\b{class_name}\(")
        for name, source in sources.items():
            tree = ast.parse(source)
            for function, _owner in _functions_in(tree):
                text = ast.get_source_segment(source, function) or ""
                if built.search(text) and not _ASKS_MOTION.search(text):
                    unasked.append(
                        f"{name}:{function.lineno} {function.name} builds {class_name} "
                        f"({where}) without asking motion.reduced()"
                    )
                elif built.search(text):
                    gated_sites += 1
    assert not unasked, "\n".join(unasked)
    # The arrival (two clocks) and the flip curtain at least: a scan that finds nothing
    # proves nothing.
    assert gated_sites >= 2
