"""Entry point for bundled standalone applications (macOS .app / Windows .exe).

This module serves as the entry point when the application is packaged with PyInstaller.
It bypasses the CLI layer and launches the GUI directly, making it suitable for
double-clicking the application bundle.

SECURITY: This app uses secure storage for credentials:
- Non-sensitive settings stored in: ~/.onelogin-migration/settings.json
- Credentials stored in: System keyring (never written to disk)
- No YAML config files with plaintext credentials
"""

from __future__ import annotations

import sys

# Ensure GUI is launched directly without CLI arguments


def main() -> None:
    """Launch the GUI application."""
    from onelogin_migration_gui import run_gui_secure

    try:
        # Launch GUI with secure settings (no YAML config needed)
        run_gui_secure()
    except Exception as exc:
        # Show error in a message box if possible
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None, "OneLogin Migration Tool Error", f"Failed to start application:\n\n{exc}"
            )
        except Exception:
            # Fallback to console
            print(f"ERROR: Failed to start application: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
