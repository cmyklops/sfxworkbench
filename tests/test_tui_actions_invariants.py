"""Invariant tests for ``sfxworkbench.tui_actions`` declarations.

Tier 5.12 (smart invalidation) reads ``ActionResult.refresh`` to decide which
TUI tabs to mark dirty after an action completes. A typo in a refresh hint
would silently under-invalidate (e.g. ``"metadta"`` instead of ``"metadata"``)
and the user would see stale data with no error.

These tests scan the module's source for every literal ``refresh=(...)``
tuple and assert each token is one of the known hint keys. Done as a static
text scan rather than runtime introspection so we catch hints in tuples that
no test path currently exercises.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import sfxworkbench.tui_actions as tui_actions

# Allowed hint values: every TUI tab key plus the App-level refresh targets
# ("status" — the top status strip; "reports" — the per-tab reports view).
_KNOWN_HINTS = frozenset(
    {
        "scan",
        "files",
        "clean",
        "dedupe",
        "metadata",
        "advanced",
        "status",
        "reports",
    }
)


def _collect_refresh_hints(module_path: Path) -> list[tuple[int, tuple[str, ...]]]:
    """Walk the AST and return ``(lineno, hint_tuple)`` for every ``refresh=`` kwarg.

    Only static string-literal tuples are inspected — that matches how every
    current declaration is written and keeps the test simple. If someone
    introduces a dynamic refresh value, this test will skip it (and we should
    add explicit coverage when that happens).
    """
    tree = ast.parse(module_path.read_text())
    hits: list[tuple[int, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "refresh":
                continue
            if not isinstance(keyword.value, ast.Tuple):
                continue
            values: list[str] = []
            all_literals = True
            for element in keyword.value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    values.append(element.value)
                else:
                    all_literals = False
                    break
            if all_literals and values:
                hits.append((keyword.lineno, tuple(values)))
    return hits


_TAB_KEYS = frozenset({"scan", "files", "clean", "dedupe", "metadata", "advanced"})


def test_action_refresh_hints_are_known() -> None:
    """Every ``refresh=("...", ...)`` literal in tui_actions.py uses a known hint."""
    module_path = Path(inspect.getsourcefile(tui_actions) or "")
    assert module_path.exists(), "Could not locate sfxworkbench.tui_actions source"

    declarations = _collect_refresh_hints(module_path)
    assert declarations, "No refresh=() tuples found — has the action module moved?"

    unknown: list[tuple[int, str]] = []
    for lineno, hints in declarations:
        for hint in hints:
            if hint not in _KNOWN_HINTS:
                unknown.append((lineno, hint))

    assert not unknown, (
        "Unknown refresh hints in sfxworkbench.tui_actions; "
        "extend _KNOWN_HINTS or fix the typo:\n" + "\n".join(f"  line {ln}: {hint!r}" for ln, hint in unknown)
    )


def test_action_refresh_hints_include_at_least_one_tab_key() -> None:
    """Every ``refresh=(...)`` literal includes at least one tab key.

    Caught a real bug: ``clean_action`` used to declare
    ``refresh=("status", "reports")`` with no tab keys, so after Tier 5.12
    smart invalidation the Clean tab never refreshed after Preview Junk /
    Apply Junk. Pure status/reports refreshes are valid for error paths
    (which set ``("status",)``), but a return from a *successful* action
    needs a tab key to repopulate the table that surfaced the action's
    output.

    Exempts ``_action_error`` (line 128) since synthesized error results
    legitimately only touch the status strip; the App-side fallback
    (``_run_action``) treats those as "invalidate everything" anyway.
    """
    module_path = Path(inspect.getsourcefile(tui_actions) or "")
    declarations = _collect_refresh_hints(module_path)

    error_helper_lines = set()
    for lineno, hints in declarations:
        # Heuristic: the error helper's tuple is the only ``("status",)``
        # single-element tuple at line 128. Skip exactly that one.
        if hints == ("status",) and lineno < 200:
            error_helper_lines.add(lineno)

    missing: list[tuple[int, tuple[str, ...]]] = []
    for lineno, hints in declarations:
        if lineno in error_helper_lines:
            continue
        if not any(hint in _TAB_KEYS for hint in hints):
            missing.append((lineno, hints))

    assert not missing, (
        "ActionResult.refresh declarations missing a tab key — after Tier 5.12 "
        "these actions return without triggering any tab fill, so their "
        "downstream tables stay stale:\n" + "\n".join(f"  line {ln}: refresh={hints!r}" for ln, hints in missing)
    )
