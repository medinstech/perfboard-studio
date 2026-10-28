"""Settings for the whole suite, before any test module is imported."""

from __future__ import annotations

import os

import pytest

# The placer runs serially unless a test asks for workers itself (tests/test_planner_pool.py
# does, through monkeypatch). Every window a UI test builds would otherwise start up to
# four worker processes of its own on its first placement, and the suite already runs
# under a lock because parallel runs ran the machine out of memory. Set, not defaulted
# from the environment the suite inherits: a shell where somebody turned workers on to
# try the window must not change what the suite measures.
os.environ["PERFBOARD_STUDIO_PLANNER_WORKERS"] = "0"

# The dark theme, for the same reason: ui/theme.py chooses once, on import, and the View
# menu's choice is in the user's own settings. A developer who picked the light theme in
# their window must not run the suite in it.
os.environ["PERFBOARD_STUDIO_THEME"] = "dark"


@pytest.fixture(autouse=True)
def _settings_in_a_temp_file(tmp_path, monkeypatch):
    """Keep the recent-file list AND the saved session out of the real user store.

    HERE, FOR EVERY TEST, and not in the one file that builds most windows: it lived in
    ``tests/test_ui.py``, and two other files that build windows had no copy of it, so the
    suite wrote an offscreen test window's geometry (an 800 px screen) and docks over the
    developer's own layout. ``tests/test_settings_isolation.py`` fails if it goes again.

    A test suite has no business writing into somebody's registry, and one that did would
    also make these tests depend on whatever ran before them -- including on the developer
    having opened a board that morning. Since the window now saves its layout on close,
    and every test here closes a window, this fixture is what stands between the suite and
    the developer's own window geometry.
    """
    from PySide6.QtCore import QSettings

    from perfboard_studio.ui import main as main_module

    store = QSettings(str(tmp_path / "recent.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_module, "app_settings", lambda: store)
    yield store


@pytest.fixture(autouse=True)
def _recovery_in_a_temp_dir(tmp_path, monkeypatch):
    """Keep autosave records out of the real user data directory.

    The same argument as ``_settings_in_a_temp_file`` above and one step sharper: every
    window built here constructs an ``Autosave``, and closing one deletes its record, so
    without this the suite would be creating and unlinking files in the developer's own
    profile -- in the one directory whose whole purpose is to hold work that must not be
    lost.
    """
    from perfboard_studio.ui import autosave as autosave_module

    directory = tmp_path / "recovery"
    monkeypatch.setattr(autosave_module, "default_directory", lambda: directory)
    yield directory
