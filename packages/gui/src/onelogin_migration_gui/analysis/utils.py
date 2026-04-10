"""Shared utilities for the analysis UI."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeVar

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QWidget

T = TypeVar("T")


def format_int(value: int | float | None) -> str:
    """Format numbers using the active locale with thousand separators."""
    if value is None:
        return "0"
    locale = QLocale()
    if isinstance(value, float):
        return locale.toString(value, "f", 2)
    return locale.toString(int(value))


def pluralize(noun: str, count: int, include_count: bool = True) -> str:
    """Return pluralized noun with optional count.

    Args:
        noun: The noun to pluralize
        count: The count to use for pluralization logic
        include_count: Whether to include the count in the returned string (default True)
    """
    suffix = noun if count == 1 else f"{noun}s"
    if include_count:
        text = format_int(count)
        return f"{text} {suffix}"
    return suffix


def set_sticky(scroll_area: QScrollArea, widget: QWidget) -> None:
    """Configure the scroll area for sticky header/footer behavior."""
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    scroll_area.setWidget(widget)


def chunked(items: Iterable[T], size: int) -> list[list[T]]:
    """Split an iterable into fixed-size chunks."""
    chunk: list[T] = []
    result: list[list[T]] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            result.append(chunk)
            chunk = []
    if chunk:
        result.append(chunk)
    return result


@dataclass(slots=True)
class TableColumn:
    """Table column configuration for simple data tables."""

    header: str
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft
    stretch: int = 1
