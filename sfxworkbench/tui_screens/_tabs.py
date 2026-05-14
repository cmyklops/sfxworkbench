"""Registry of per-tab page modules.

The App reads ``TAB_REGISTRY`` to wire up navigation, key bindings, and the
``ContentSwitcher``. Each entry pins a tab key (used in widget ids and binding
names) to the module that owns its ``compose`` + ``fill`` functions.

Adding a new tab is now a one-line edit here plus a new ``*_tab.py`` module
with the standard interface, rather than a 30-line surgery on the App class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from textual.app import ComposeResult


class _TabModule(Protocol):
    """Structural shape every per-tab module satisfies."""

    KEY: str
    TITLE: str
    NOTE: str

    def compose(self, app) -> ComposeResult: ...  # pragma: no cover (Protocol method)

    def fill(self, app) -> None: ...  # pragma: no cover (Protocol method)


@dataclass(frozen=True)
class TabSpec:
    """One entry in the registry: tab key + the module that owns it."""

    key: str
    label: str
    module: _TabModule


def _import_registry() -> tuple[TabSpec, ...]:
    """Build the registry by importing the tab modules.

    Wrapped in a function so the import order is explicit (and so swapping a
    tab for an alternate implementation in a test is one ``monkeypatch`` away).
    """
    from sfxworkbench.tui_screens import (
        clean_tab,
        dedupe_tab,
        files_tab,
        history_tab,
        metadata_tab,
        scan_tab,
    )

    # Order here matches the visible tab order in ``sfx tui``.
    return (
        TabSpec(key=scan_tab.KEY, label="Scan", module=scan_tab),
        TabSpec(key=clean_tab.KEY, label="Cleanup", module=clean_tab),
        TabSpec(key=dedupe_tab.KEY, label="Dedupe", module=dedupe_tab),
        TabSpec(key=metadata_tab.KEY, label="Metadata", module=metadata_tab),
        TabSpec(key=files_tab.KEY, label="Files", module=files_tab),
        TabSpec(key=history_tab.KEY, label="History", module=history_tab),
    )


TAB_REGISTRY: tuple[TabSpec, ...] = _import_registry()
"""Ordered list of all feature tabs the App composes."""


TAB_BY_KEY: dict[str, TabSpec] = {spec.key: spec for spec in TAB_REGISTRY}
"""Lookup by short key (matches widget ids like ``scan-page``)."""
