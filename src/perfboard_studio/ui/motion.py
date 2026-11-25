"""One switch for every interface animation: on by default, off under tests and Reduce Motion.

Every transition in the window -- the board turning over, 3D parts arriving, the step bar,
toasts, camera flights and drawer slides -- asks :func:`enabled` (or :func:`reduced`) before
starting a timer or a ``QVariantAnimation``. When motion is reduced, every transition lands
on its final state synchronously in 0 ms with no timer left running, so offscreen tests and
golden renders stay deterministic and someone who prefers a still window gets one immediately,
without restarting.

Precedence mirrors ``ui/theme.py``:
  1. An explicit live choice in this process (``set_reduced``, from ``View ▸ Reduce Motion``).
  2. The ``PERFBOARD_STUDIO_REDUCE_MOTION`` environment variable (set to ``1`` by
     ``tests/conftest.py`` so a developer's own preference never reaches the suite).
  3. Offscreen Qt (``QT_QPA_PLATFORM=offscreen``) defaults to reduced motion unless the
     variable explicitly asks for ``0``.
  4. The View menu's stored setting (``session/reduceMotion``), defaulting to ``False``.

Pure stdlib at import time so importing this module costs nothing at startup.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: The View menu's stored preference, in ``main.app_settings()``'s store.
REDUCE_MOTION_KEY = "session/reduceMotion"

#: Environment override for one run; ``tests/conftest.py`` sets this to ``"1"``.
REDUCE_MOTION_VARIABLE = "PERFBOARD_STUDIO_REDUCE_MOTION"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})

#: Live process-wide override from ``View ▸ Reduce Motion`` (or a test), or ``None`` to read
#: the environment and stored setting.
_override: bool | None = None


def _parse_flag(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        word = raw.strip().lower()
        if word in _TRUTHY:
            return True
        if word in _FALSY:
            return False
    return None


def chosen_reduced(environ: Mapping[str, str], stored: object) -> bool:
    """Resolve whether motion is reduced from environment and stored setting."""
    env = _parse_flag(environ.get(REDUCE_MOTION_VARIABLE))
    if env is not None:
        return env
    if environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
        return True
    saved = _parse_flag(stored)
    return bool(saved) if saved is not None else False


def _stored_choice() -> object:
    """Read the View menu's stored choice from the same store as ``main.app_settings()``."""
    from PySide6.QtCore import QSettings

    return QSettings("Perfboard Studio", "Perfboard Studio").value(REDUCE_MOTION_KEY)


def reduced() -> bool:
    """True when animations should snap synchronously to their final state."""
    if _override is not None:
        return _override
    if _parse_flag(os.environ.get(REDUCE_MOTION_VARIABLE)) is not None:
        return chosen_reduced(os.environ, None)
    if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
        return True
    return chosen_reduced(os.environ, _stored_choice())


def enabled() -> bool:
    """True when animations should run."""
    return not reduced()


def set_reduced(on: bool) -> None:
    """Turn reduced motion on or off immediately for this process."""
    global _override
    _override = bool(on)


def reset() -> None:
    """Clear any live override so environment and stored preference take over again."""
    global _override
    _override = None


def duration(ms: int) -> int:
    """``ms`` when animations are enabled, ``0`` when reduced."""
    return 0 if reduced() else max(0, ms)
