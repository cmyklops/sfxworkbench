"""Rich Text rendering helpers shared by TUI screens and data adapters."""

from __future__ import annotations

from rich.text import Text

_TAG_FIELD_STYLES = {
    "description": "cyan",
    "icmt": "cyan",
    "keywords": "magenta",
    "ikey": "magenta",
    "category": "green",
    "ignr": "green",
    "subcategory": "blue",
    "ucs_category": "yellow",
    "ucs_subcategory": "yellow",
    "title": "white",
    "inam": "white",
    "comment": "dim cyan",
    "isbj": "blue",
}

_TAG_STATUS_SYMBOLS = {
    "pending": ("!", "bold yellow"),
    "approved": ("+", "green"),
    "rejected": ("x", "red"),
}

_TAG_SOURCE_SYMBOLS = {
    "filename": ("#", "dim cyan"),
    "group": ("~", "dim magenta"),
    "path": ("/", "dim blue"),
    "ucs_catalog": ("^", "dim yellow"),
    "ucs_stem": ("^", "dim yellow"),
    "synonym": ("*", "dim green"),
}


def _tag_text(value: str, field: str, *, status: str = "", source: str = "") -> Text:
    style = _TAG_FIELD_STYLES.get(field.lower(), "white")
    if status == "pending":
        style = f"bold {style}"
    text = Text()
    status_symbol = _TAG_STATUS_SYMBOLS.get(status)
    source_symbol = _TAG_SOURCE_SYMBOLS.get(source)
    if status_symbol is not None:
        text.append(status_symbol[0], style=status_symbol[1])
    if source_symbol is not None:
        text.append(source_symbol[0], style=source_symbol[1])
    if status_symbol is not None or source_symbol is not None:
        text.append(" ")
    text.append(value, style=style)
    return text


def _tags_cell(row) -> Text:
    if not row.tag_items:
        return Text("No searchable tags found", style="dim")
    text = Text()
    for index, item in enumerate(row.tag_items):
        if index:
            text.append("  |  ", style="dim")
        text.append_text(
            _tag_text(
                item.value,
                item.field,
                status=item.status if item.source == "plan" else "",
                source=item.evidence_source if item.source == "plan" else "",
            )
        )
    return text
