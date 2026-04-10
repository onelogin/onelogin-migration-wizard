"""Helper utilities for the migration wizard UI."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWizardPage

from .theme_manager import ThemeMode, get_theme_manager

TOOL_VERSION = "v0.9.0 beta"
_LOGO_LIGHT = "assets/Onelogin_Logotype_black_RGB.png.webp"
_LOGO_DARK = "assets/Onelogin_Logotype_white_RGB.png.webp"
_ICON_WINDOWS = "assets/app_logos/windows/app.ico"
_ICON_MAC = "assets/app_logos/mac/app.icns"


class ThemeToggle(QPushButton):
    """Icon-based toggle button for switching between light and dark themes.

    Features:
    - Displays sun icon (☀) for light mode, moon icon (🌙) for dark mode
    - Smooth transitions with hover effects
    - Automatically syncs with ThemeManager
    - Persists theme preference via QSettings
    """

    def __init__(self, parent=None):
        """Initialize theme toggle button."""
        super().__init__(parent)

        self.theme_manager = get_theme_manager()

        # Configure button appearance
        self.setFixedSize(40, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Toggle light/dark theme")

        # Connect signals
        self.clicked.connect(self._toggle_theme)
        self.theme_manager.theme_changed.connect(self._on_theme_changed)

        # Initial update
        self._update_appearance()

    def _toggle_theme(self):
        """Toggle between light and dark themes."""
        self.theme_manager.switch_theme()

    def _on_theme_changed(self, mode: ThemeMode):
        """Handle theme change from ThemeManager."""
        self._update_appearance()

    def _update_appearance(self):
        """Update button icon and styling based on current theme."""
        is_dark = self.theme_manager.current_mode == ThemeMode.DARK

        # Set icon text (sun for light mode, moon for dark mode)
        icon_text = "🌙" if is_dark else "☀"
        self.setText(icon_text)

        # Get theme colors
        bg_color = self.theme_manager.get_color("surface_elevated")
        border_color = self.theme_manager.get_color("border")
        hover_color = self.theme_manager.get_color("neutral_100")

        # Apply styling with smooth transitions
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {bg_color};
                border: 2px solid {border_color};
                border-radius: 20px;
                font-size: 18px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                border-color: {self.theme_manager.get_color("primary")};
            }}
            QPushButton:pressed {{
                background-color: {bg_color};
                border: 3px solid {self.theme_manager.get_color("primary")};
            }}
        """
        )


def resource_path(relative: str) -> Path:
    """Return an absolute path to ``relative`` that works with PyInstaller.

    The helper tries a couple of different roots so assets continue to resolve
    whether we are running from source, an installed package, or a frozen
    binary.
    """

    candidate = Path(relative)
    if candidate.is_absolute():
        return candidate

    package_dir = Path(__file__).resolve().parent
    project_src = package_dir.parent  # .../packages/gui/src
    project_root = project_src.parent.parent  # go up to repo root

    search_roots: Iterable[Path] = (
        Path(getattr(sys, "_MEIPASS", "")),  # PyInstaller bundle
        package_dir / "assets",
        package_dir,
        project_src,
        project_root,
    )

    variants = [candidate]
    if candidate.parts and len(candidate.parts) >= 2:
        prefixes = [
            ("src", "onelogin_migration_gui"),
            ("src", "onelogin_migration_tool"),
            ("onelogin_migration_gui",),
            ("onelogin_migration_tool",),
        ]
        for prefix in prefixes:
            if candidate.parts[: len(prefix)] == prefix:
                variants.append(Path(*candidate.parts[len(prefix) :]))
                break
        if candidate.parts[0] == "src":
            variants.append(Path(*candidate.parts[1:]))

    for root in search_roots:
        if not root or not root.exists():
            continue
        for variant in variants:
            candidate_path = (root / variant).resolve()
            if candidate_path.exists():
                return candidate_path

    # Fall back to package-local resolution so callers can surface errors.
    return (package_dir / candidate).resolve()


def load_logo(target_size: tuple[int, int], theme_mode: ThemeMode | None = None) -> QPixmap:
    """Return the OneLogin logo scaled to the requested size.

    Args:
        target_size: Tuple of (width, height) for the target size
        theme_mode: Theme mode to determine which logo to use. If None, uses current theme.

    Returns:
        QPixmap of the logo scaled to the requested size
    """
    # Get current theme if not provided
    if theme_mode is None:
        theme_manager = get_theme_manager()
        theme_mode = theme_manager.current_mode

    # Select appropriate logo based on theme
    logo_path = _LOGO_DARK if theme_mode == ThemeMode.DARK else _LOGO_LIGHT

    path = resource_path(logo_path)
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return pixmap
    width, height = target_size
    return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def load_app_icon() -> QIcon:
    """Return an application icon appropriate for the current platform."""

    candidates: list[str] = []
    platform = sys.platform
    if platform.startswith("win"):
        candidates.append(_ICON_WINDOWS)
    elif platform == "darwin":
        candidates.append(_ICON_MAC)
    else:
        # Linux/other platforms - try logo files
        candidates.append(_LOGO_LIGHT)
        candidates.append(_ICON_WINDOWS)

    if _LOGO_LIGHT not in candidates:
        candidates.append(_LOGO_LIGHT)

    for relative in candidates:
        path = resource_path(relative)
        if not path.exists():
            continue
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon

    return QIcon()


def add_branding(page: QWizardPage) -> tuple[QLabel | None, QLabel | None]:
    """Decorate ``page`` with the top-right logo and theme toggle."""

    layout = page.layout()
    if layout is None:
        layout = QVBoxLayout(page)
        page.setLayout(layout)

    # Avoid duplicating branding when called multiple times
    if getattr(page, "_branding_applied", False):
        return page._branding_widgets  # type: ignore[return-value]

    suppress_logo = bool(getattr(page, "suppress_brand_logo", False))

    logo_label = QLabel()
    if not suppress_logo:
        top_row = QHBoxLayout()

        # Add theme toggle button on the left
        theme_toggle = ThemeToggle(page)
        top_row.addWidget(theme_toggle)
        top_row.addStretch(1)  # Push logo to the right

        # Add logo on the right
        logo = load_logo((140, 60))
        if not logo.isNull():
            logo_label.setPixmap(logo)
        logo_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        top_row.addWidget(logo_label)
        layout.insertLayout(0, top_row)

        # Connect theme change signal to update logo
        theme_manager = get_theme_manager()

        def update_logo(mode: ThemeMode):
            new_logo = load_logo((140, 60), mode)
            if not new_logo.isNull():
                logo_label.setPixmap(new_logo)

        theme_manager.theme_changed.connect(update_logo)

    layout.addStretch(1)

    version_label: QLabel | None = None
    page._branding_applied = True  # type: ignore[attr-defined]
    page._branding_widgets = (logo_label, version_label)  # type: ignore[attr-defined]
    return logo_label, version_label
