"""Every comparison with the original's output runs on the original's inputs (``differential.py``).

A test that compared this code on the REAL bodies with what the original produced on its own
would read a body made larger as a regression in the rules -- or, worse, pass for a reason
nobody intended. So this reads the test sources: a function that loads a fixture's
``*.expected.json`` and goes on to use what it expects must take its footprints from
``differential_lookup()``, never from ``footprint_lookup()``. Reading the sources is the only
way to see it: both lookups answer every id, and on the ids that do not diverge they answer
alike.

``test_footprints.py`` is the one module allowed the registry beside the golden: it is the
comparison of the registry WITH the original's footprints, field by field.
"""

from __future__ import annotations

import ast
from pathlib import Path

from perfboard_studio.footprints import footprint_lookup

from .differential import DIVERGES_FROM_TYPESCRIPT, ORIGINAL_FOOTPRINTS, differential_lookup

TESTS = Path(__file__).resolve().parent
#: What hands a test the registry's footprints: a lookup, the table, or one footprint.
REGISTRY_FACTORIES = ("footprint_lookup", "standard_footprints", "get_footprint")
#: Compares the registry itself with ``footprints.expected.json``, on purpose.
REGISTRY_COMPARISON = "test_footprints.py"


def _called(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _bound_at_module(tree: ast.Module, *factories: str) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and _called(node.value) in factories:
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _called(node.value) in factories
            and isinstance(node.target, ast.Name)
        ):
            names.add(node.target.id)
    return names


def _expected_names(function: ast.FunctionDef, loaders: set[str]) -> set[str]:
    """The names a function binds to what a loader EXPECTS: every element of a loader's
    tuple after the document, or its ``[1]``."""
    names: set[str] = set()
    for node in ast.walk(function):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.For):
            targets, value = [node.target], node.iter
        if value is None:
            continue
        if _called(value) in loaders:
            for target in targets:
                if isinstance(target, ast.Tuple):
                    names |= {e.id for e in target.elts[1:] if isinstance(e, ast.Name)}
        elif (
            isinstance(value, ast.Subscript)
            and _called(value.value) in loaders
            and isinstance(value.slice, ast.Constant)
            and value.slice.value != 0
        ):
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


def comparisons(source: str) -> dict[str, tuple[bool, bool]]:
    """For every function that uses a fixture's expected output: whether it reaches the
    registry, and whether it reaches the differential lookup."""
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    loaders = {f.name for f in functions if "expected.json" in ast.get_source_segment(source, f)}  # type: ignore[operator]
    registry = _bound_at_module(tree, *REGISTRY_FACTORIES)
    differential = _bound_at_module(tree, "differential_lookup")
    found: dict[str, tuple[bool, bool]] = {}
    for function in functions:
        if function.name in loaders:
            continue
        expected = _expected_names(function, loaders)
        used = {n.id for n in ast.walk(function) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        if not expected & used:
            continue
        called = {_called(n) for n in ast.walk(function)}
        found[function.name] = (
            bool(used & registry) or bool(called & set(REGISTRY_FACTORIES)),
            bool(used & differential) or "differential_lookup" in called,
        )
    return found


def _modules() -> dict[str, dict[str, tuple[bool, bool]]]:
    return {
        path.name: comparisons(path.read_text(encoding="utf-8"))
        for path in sorted(TESTS.glob("test_*.py"))
        if path.name not in (REGISTRY_COMPARISON, Path(__file__).name)
    }


def test_every_comparison_with_the_original_runs_on_its_inputs() -> None:
    wrong = {
        f"{module}::{name}"
        for module, found in _modules().items()
        for name, (registry, _differential) in found.items()
        if registry
    }
    assert not wrong, f"compares with the golden output on the registry's footprints: {sorted(wrong)}"


def test_the_check_finds_the_comparisons_it_is_for() -> None:
    """Not vacuous: each of the five modules that holds this engine to the original's output
    has comparisons this finds running on the original's inputs. (A function that only counts
    what the fixtures expect runs no engine and needs no footprints at all.)"""
    holding = {
        module
        for module, found in _modules().items()
        if any(differential for _registry, differential in found.values())
    }
    assert holding == {
        "test_connectivity.py",
        "test_drc.py",
        "test_lvs.py",
        "test_occupancy_golden.py",
        "test_router.py",
    }


def test_the_check_catches_a_test_that_builds_its_own_lookup() -> None:
    source = '''
_LOOKUP = footprint_lookup()

def _load_golden(name):
    return doc, json.loads((GOLDEN_DIR / f"{name}.expected.json").read_text())

def test_it():
    doc, expected = _load_golden("dense")
    assert run_drc(doc, _LOOKUP) == expected

def test_only_the_document():
    doc, _expected = _load_golden("dense")
    assert run_drc(doc, _LOOKUP) == []
'''
    assert comparisons(source) == {"test_it": (True, False)}


def test_the_lookup_serves_the_original_exactly_where_the_registry_diverges() -> None:
    registry, served = footprint_lookup(), differential_lookup()
    for footprint_id in DIVERGES_FROM_TYPESCRIPT:
        assert served(footprint_id) is ORIGINAL_FOOTPRINTS[footprint_id]
        assert served(footprint_id) != registry(footprint_id)
    # And the registry's own for every other id: the two are one footprint there anyway.
    assert served("c-elec-d5-p2") is not None
    assert served("c-elec-d5-p2") == registry("c-elec-d5-p2")
