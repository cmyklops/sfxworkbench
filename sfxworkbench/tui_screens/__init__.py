"""Textual screen modules for the sfxworkbench review workbench.

This package hosts Textual ``Screen`` subclasses that compose into the main
``sfx tui`` app. Splitting screens out of ``tui_app.py`` follows the same
pattern as the ``cli/`` package: each screen owns its widgets, bindings, and
data loading; the top-level app wires them in.
"""
