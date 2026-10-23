"""What the window costs before anybody sees it.

Nearly all of a start is imports: on a desktop the window was up 700 ms after the
interpreter started, 560 of them importing, and 425 of those were ``import vtk`` -- the
umbrella module that imports every one of VTK's forty Python modules, from the web
exporter to volume rendering, for a view that draws with thirteen. ``ui/view3d.py`` now
imports those thirteen and binds them to the name ``vtk`` it always used.

Every check that matters runs in a CHILD process. The suite imports the umbrella itself
(several 3D tests do ``import vtk``), and once anything in a process has, every object
factory VTK has is registered -- so a view that had lost the one registering, say, the
OpenGL backend would render perfectly in here and not in the application.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

from perfboard_studio.ui import view3d

from .test_gl import requires_offscreen_gl

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
VIEW3D = SRC / "perfboard_studio" / "ui" / "view3d.py"
EXAMPLE = REPO_ROOT / "examples" / "ne555-astable.perf"


def _run(script: str, *args: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_the_3d_view_does_not_import_the_whole_of_vtk() -> None:
    """``vtk`` itself, or any module only the umbrella brings, means the cost is back."""
    out = _run(
        "import sys, perfboard_studio.ui.view3d\n"
        "print(sorted(m for m in ('vtk', 'vtkmodules.all', 'vtkmodules.vtkWebCore',\n"
        "    'vtkmodules.vtkRenderingVolumeOpenGL2', 'vtkmodules.vtkChartsCore')\n"
        "    if m in sys.modules))"
    )
    assert out.strip() == "[]"


def test_every_vtk_name_the_3d_view_uses_is_in_its_namespace() -> None:
    """A ``vtk.vtkSomething`` from a module not in the list is an AttributeError --

    raised only when the code path that names it runs, which for a rarely taken branch
    is somebody's 3D panel going blank months later. Read off the source, so a new name
    is checked the day it is written.
    """
    used: set[str] = set()
    for node in ast.walk(ast.parse(VIEW3D.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "vtk"
        ):
            used.add(node.attr)
    assert used, "found no vtk.<name> at all; has the module stopped calling it vtk?"
    missing = sorted(name for name in used if not hasattr(view3d.vtk, name))
    assert not missing, (
        f"view3d uses {missing}, which none of the modules it imports provides; add the "
        "vtkmodules module that defines each to the list beside `vtk: Any`"
    )


@requires_offscreen_gl
def test_the_3d_view_renders_the_same_without_the_rest_of_vtk(tmp_path: Path) -> None:
    """The same board rendered twice, with and without the umbrella imported first.

    What a narrower import can lose is a REGISTRATION: VTK swaps in its OpenGL classes,
    its text and its interactor styles when the module that holds them is imported, and
    nothing raises when one is missing -- the picture simply comes out different, or
    empty. So the comparison is the picture. Identical to the byte on the machine this
    was written on; held to a fraction of a level so a renderer that dithers differently
    between two processes is not a failure.
    """
    script = (
        "import sys\n"
        "if sys.argv[1] == 'umbrella':\n"
        "    import vtk\n"
        "from perfboard_studio import persist\n"
        "from perfboard_studio.footprints import footprint_lookup\n"
        "from perfboard_studio.ui import view3d\n"
        "text = open(sys.argv[2], encoding='utf-8').read()\n"
        "doc = persist.deserialize_document(text).document\n"
        "view3d.render_offscreen(doc, footprint_lookup(), sys.argv[3], width=320, height=240)\n"
        "print('vtk' in sys.modules)\n"
    )
    pictures = {}
    for mode in ("slim", "umbrella"):
        path = tmp_path / f"{mode}.png"
        imported_umbrella = _run(script, mode, str(EXAMPLE), str(path)).strip()
        assert imported_umbrella == str(mode == "umbrella")
        pictures[mode] = _pixels(path)

    slim, umbrella = pictures["slim"], pictures["umbrella"]
    assert len(slim) == len(umbrella)
    assert len(set(slim)) > 16, "the render is a flat colour; nothing was drawn"
    mean_difference = sum(abs(a - b) for a, b in zip(slim, umbrella, strict=True)) / len(slim)
    assert mean_difference < 0.5, f"renders differ by {mean_difference:.2f} levels on average"


def _pixels(path: Path) -> bytes:
    """Every channel of every pixel, through Qt so no GL is needed to read it back."""
    from PySide6.QtGui import QImage

    image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGB888)
    assert not image.isNull(), f"{path} did not load"
    row = image.width() * 3
    data = bytes(image.constBits())
    stride = image.bytesPerLine()
    return b"".join(data[y * stride : y * stride + row] for y in range(image.height()))
