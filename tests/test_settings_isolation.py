"""No test reaches the real settings store or the real recovery directory.

The fixtures that redirect both live in ``tests/conftest.py`` and apply to every test. They
used to live in ``tests/test_ui.py`` alone, and two other files that build windows had no
copy, so the suite wrote an offscreen test window's geometry and docks over the developer's
own layout in the registry. These fail if the redirection goes away again -- and they check
the store BEFORE building a window, so a failure here does not itself write anything.
"""

from __future__ import annotations

import os
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from perfboard_studio import persist
from perfboard_studio.ui import autosave
from perfboard_studio.ui import main as main_module

GOLDEN = pathlib.Path(__file__).resolve().parent.parent / "tools" / "diffcheck" / "golden" / "dense.perf"


def _real_store_name() -> str:
    """Where the application keeps its settings, said without opening it for writing."""
    return QSettings("Perfboard Studio", "Perfboard Studio").fileName()


def test_every_test_is_given_a_settings_store_of_its_own(tmp_path: pathlib.Path) -> None:
    store = main_module.app_settings()
    assert store.fileName() != _real_store_name()
    assert pathlib.Path(store.fileName()).resolve().is_relative_to(tmp_path.resolve())


def test_every_test_is_given_a_recovery_directory_of_its_own(tmp_path: pathlib.Path) -> None:
    assert autosave.default_directory().resolve().is_relative_to(tmp_path.resolve())


def test_a_window_built_and_closed_saves_its_session_where_the_test_said(
    tmp_path: pathlib.Path,
) -> None:
    """The seam, not the parts: the window's own save path lands in the test's store."""
    store = main_module.app_settings()
    assert pathlib.Path(store.fileName()).resolve().is_relative_to(tmp_path.resolve())

    QApplication.instance() or QApplication(["perfboard-studio-tests"])
    document = persist.deserialize_document(GOLDEN.read_text(encoding="utf-8")).document
    window = main_module.MainWindow(document)
    window._mark_saved()
    window.close()

    assert main_module.app_settings().value(main_module.GEOMETRY_KEY) is not None
