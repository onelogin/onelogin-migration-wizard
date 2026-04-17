"""Fatal error dialog for migration failures."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..theme_manager import get_theme_manager


class FatalErrorDialog(QDialog):
    """Dialog displayed when a fatal error stops the migration."""

    def __init__(self, error_message: str, error_details: str | None = None, parent=None):
        """
        Initialize the fatal error dialog.

        Args:
            error_message: Brief error message to display
            error_details: Full error details (stack trace, verbose info)
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Migration Failed")
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self.theme_manager = get_theme_manager()
        self.error_message = error_message
        self.error_details = error_details

        self._setup_ui()
        self._apply_theme()
        self.theme_manager.theme_changed.connect(self._apply_theme)

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(self.theme_manager.get_spacing("lg"))

        # Error icon and title
        header_layout = QHBoxLayout()
        header_layout.setSpacing(self.theme_manager.get_spacing("md"))

        # Error icon (using emoji for now - could be replaced with QIcon)
        icon_label = QLabel("🔴")
        icon_typo = self.theme_manager.get_typography("h1")
        icon_label.setStyleSheet(f"font-size: {icon_typo['size']}px;")
        header_layout.addWidget(icon_label)

        # Title
        title_label = QLabel("Migration Failed")
        self.title_label = title_label
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Error message
        message_label = QLabel(self.error_message)
        message_label.setWordWrap(True)
        self.message_label = message_label
        layout.addWidget(message_label)

        # Error details (if available)
        if self.error_details:
            details_label = QLabel("Error Details:")
            self.details_label = details_label
            layout.addWidget(details_label)

            self.details_text = QTextEdit()
            self.details_text.setReadOnly(True)
            self.details_text.setPlainText(self.error_details)
            self.details_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

            # Set monospace font for details
            font = self.details_text.font()
            font.setFamily("Courier New, Monaco, Menlo, monospace")
            font.setPointSize(9)
            self.details_text.setFont(font)

            layout.addWidget(self.details_text, 1)  # Give it stretch factor

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        if self.error_details:
            self.copy_button = QPushButton("Copy Error Details")
            self.copy_button.clicked.connect(self._copy_to_clipboard)
            button_layout.addWidget(self.copy_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        self.close_button.setDefault(True)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def _apply_theme(self) -> None:
        """Apply theme styling to the dialog."""
        # Background color
        bg_color = self.theme_manager.get_color("background")
        self.setStyleSheet(f"QDialog {{ background-color: {bg_color}; }}")

        # Title styling
        title_typo = self.theme_manager.get_typography("h2")
        self.title_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: {title_typo['size']}px;
                font-weight: {title_typo['weight']};
                color: {self.theme_manager.get_color('error')};
            }}
            """
        )

        # Message styling
        body_typo = self.theme_manager.get_typography("body")
        self.message_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: {body_typo['size']}px;
                color: {self.theme_manager.get_color('text_primary')};
                padding: {self.theme_manager.get_spacing('md')}px;
                background-color: {self.theme_manager.get_color('surface')};
                border-left: 4px solid {self.theme_manager.get_color('error')};
                border-radius: 4px;
            }}
            """
        )

        # Details label styling
        if self.error_details:
            caption_typo = self.theme_manager.get_typography("caption")
            self.details_label.setStyleSheet(
                f"""
                QLabel {{
                    font-size: {caption_typo['size']}px;
                    font-weight: {caption_typo['weight']};
                    color: {self.theme_manager.get_color('text_secondary')};
                    margin-top: {self.theme_manager.get_spacing('md')}px;
                }}
                """
            )

            # Details text styling
            surface_color = self.theme_manager.get_color("surface")
            text_color = self.theme_manager.get_color("text_primary")
            border_color = self.theme_manager.get_color("border")
            self.details_text.setStyleSheet(
                f"""
                QTextEdit {{
                    background-color: {surface_color};
                    color: {text_color};
                    border: 1px solid {border_color};
                    border-radius: 4px;
                    padding: {self.theme_manager.get_spacing('sm')}px;
                }}
                """
            )

        # Button styling
        button_typo = self.theme_manager.get_typography("button")
        primary_color = self.theme_manager.get_color("primary")
        error_color = self.theme_manager.get_color("error")
        text_on_primary = self.theme_manager.get_color("text_on_primary")

        close_button_style = f"""
            QPushButton {{
                background-color: {error_color};
                color: {text_on_primary};
                border: none;
                border-radius: 6px;
                padding: {self.theme_manager.get_spacing('sm')}px {self.theme_manager.get_spacing('lg')}px;
                font-size: {button_typo['size']}px;
                font-weight: {button_typo['weight']};
                min-width: 100px;
            }}
            QPushButton:hover {{
                background-color: {self.theme_manager.get_color('error_light')};
            }}
            QPushButton:pressed {{
                background-color: {error_color};
            }}
        """
        self.close_button.setStyleSheet(close_button_style)

        if self.error_details:
            copy_button_style = f"""
                QPushButton {{
                    background-color: transparent;
                    color: {primary_color};
                    border: 1px solid {primary_color};
                    border-radius: 6px;
                    padding: {self.theme_manager.get_spacing('sm')}px {self.theme_manager.get_spacing('lg')}px;
                    font-size: {button_typo['size']}px;
                    font-weight: {button_typo['weight']};
                    min-width: 150px;
                }}
                QPushButton:hover {{
                    background-color: {primary_color};
                    color: {text_on_primary};
                }}
                QPushButton:pressed {{
                    background-color: {self.theme_manager.get_color('primary_dark')};
                    color: {text_on_primary};
                }}
            """
            self.copy_button.setStyleSheet(copy_button_style)

    def _copy_to_clipboard(self) -> None:
        """Copy error details to clipboard."""
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
        full_error = f"{self.error_message}\n\n{self.error_details}"
        clipboard.setText(full_error)

        # Update button text temporarily to show success
        original_text = self.copy_button.text()
        self.copy_button.setText("✓ Copied!")
        self.copy_button.setEnabled(False)

        # Reset after 2 seconds
        from PySide6.QtCore import QTimer

        QTimer.singleShot(
            2000,
            lambda: (
                self.copy_button.setText(original_text),
                self.copy_button.setEnabled(True),
            ),
        )
