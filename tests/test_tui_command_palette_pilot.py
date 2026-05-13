"""Pilot-based interaction test for the command palette (Tier 4.10 exemplar).

Demonstrates the pattern future per-screen tests will follow:

1. Instantiate the screen via its factory.
2. Mount it inside a minimal ``App`` shell with ``app.run_test()``.
3. Drive interactions through ``Pilot``.
4. Assert on screen state, not visual output (snapshot tests would go in a
   different file with separate dev tooling).

Uses ``asyncio.run`` rather than ``pytest-asyncio`` so the test is callable
from the standard pytest run without a new dev dependency.
"""

from __future__ import annotations

import asyncio

import pytest

textual = pytest.importorskip("textual")


def test_command_palette_filters_and_runs_selected_handler() -> None:
    """Typing 'scan' filters to just scan commands; Enter runs the handler."""
    from sfxworkbench.tui_screens.command_palette import build_command_palette
    from textual.app import App, ComposeResult

    invocations: list[str] = []
    handlers = {
        "scan-run": lambda: invocations.append("scan-run"),
        "dedupe-build": lambda: invocations.append("dedupe-build"),
        "clean-preview": lambda: invocations.append("clean-preview"),
    }

    class _Host(App):
        def compose(self) -> ComposeResult:
            yield from ()

        def on_mount(self) -> None:
            self.push_screen(build_command_palette(handlers))

    async def _drive() -> None:
        async with _Host().run_test() as pilot:
            await pilot.pause()
            for char in "scan":
                await pilot.press(char)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_drive())
    assert invocations == ["scan-run"], f"expected scan-run to fire from palette selection, got {invocations}"


def test_command_palette_escape_pops_without_running() -> None:
    """Escape closes the palette without firing any handler."""
    from sfxworkbench.tui_screens.command_palette import build_command_palette
    from textual.app import App, ComposeResult

    invocations: list[str] = []
    handlers = {"scan-run": lambda: invocations.append("scan-run")}

    class _Host(App):
        def compose(self) -> ComposeResult:
            yield from ()

        def on_mount(self) -> None:
            self.push_screen(build_command_palette(handlers))

    async def _drive() -> None:
        async with _Host().run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(_drive())
    assert invocations == []
