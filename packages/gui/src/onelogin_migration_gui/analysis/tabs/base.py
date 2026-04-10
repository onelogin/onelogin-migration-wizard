"""Base tab classes for analysis UI."""

from __future__ import annotations

from PySide6.QtWidgets import QSizePolicy, QWidget

from ..model import AnalysisModel


class AnalysisTab(QWidget):
    """Base class for analysis tabs with a common bind API."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Ensure tabs expand to fill available space
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def bind(self, model: AnalysisModel) -> None:
        """Populate tab content from the analysis model."""
        raise NotImplementedError
