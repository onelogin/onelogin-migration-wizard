"""PySide6-based migration wizard entry point."""

from __future__ import annotations

__version__ = "0.2.0"

import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import requests
import yaml
from onelogin_migration_core.config import MigrationSettings, ensure_config_file
from onelogin_migration_core.credentials import AutoSaveCredentialManager
from onelogin_migration_core.manager import MigrationAborted, MigrationManager
from onelogin_migration_core.progress import MigrationProgress, ProgressSnapshot

# Configure PySide6 plugin/library paths before any Qt modules are imported.
# On macOS Sequoia with Python 3.13, the default plugin discovery may return "",
# leading to "Could not find the Qt platform plugin 'cocoa'". We proactively
# point Qt at the wheel's bundled plugins before any PySide6 import occurs.
_PYSIDE_SPEC = importlib.util.find_spec("PySide6")
_QT_PLUGIN_PATH: Path | None = None
_QT_PLATFORM_PLUGIN_PATH: Path | None = None
if _PYSIDE_SPEC and _PYSIDE_SPEC.origin:
    _pyside_path = Path(_PYSIDE_SPEC.origin).parent
    _qt_root = _pyside_path / "Qt"
    _plugin_dir = _qt_root / "plugins"
    if _plugin_dir.exists():
        if sys.platform == "darwin":
            try:
                subprocess.run(
                    ["/usr/bin/chflags", "-R", "nohidden", str(_plugin_dir)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                pass

        _QT_PLUGIN_PATH = _plugin_dir
        _platform_dir = _plugin_dir / "platforms"
        if _platform_dir.exists():
            _QT_PLATFORM_PLUGIN_PATH = _platform_dir
            # Ensure Qt sees the wheel's plugin directories before it initialises
            os.environ.setdefault("QT_PLUGIN_PATH", str(_QT_PLUGIN_PATH))
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_QT_PLATFORM_PLUGIN_PATH))
    _qt_lib_dir = _qt_root / "lib"
    if _qt_lib_dir.exists():
        _lib_path = str(_qt_lib_dir)
        existing = os.environ.get("DYLD_LIBRARY_PATH")
        if existing:
            if _lib_path not in existing.split(os.pathsep):
                os.environ["DYLD_LIBRARY_PATH"] = os.pathsep.join([_lib_path, existing])
        else:
            os.environ["DYLD_LIBRARY_PATH"] = _lib_path

        existing_fw = os.environ.get("DYLD_FRAMEWORK_PATH")
        if existing_fw:
            if _lib_path not in existing_fw.split(os.pathsep):
                os.environ["DYLD_FRAMEWORK_PATH"] = os.pathsep.join([_lib_path, existing_fw])
        else:
            os.environ["DYLD_FRAMEWORK_PATH"] = _lib_path

try:
    from PySide6 import __version__ as _PYSIDE_VERSION
    from PySide6.QtCore import (
        QCoreApplication,
        QObject,
        Qt,
        QThread,
        QUrl,
        Signal,
        Slot,
    )
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QStackedWidget,
        QStyleFactory,
        QVBoxLayout,
        QWidget,
    )

    # Also set library paths programmatically
    try:
        if _QT_PLUGIN_PATH and _QT_PLUGIN_PATH.exists():
            if str(_QT_PLUGIN_PATH) not in QCoreApplication.libraryPaths():
                QCoreApplication.addLibraryPath(str(_QT_PLUGIN_PATH))
        if _QT_PLATFORM_PLUGIN_PATH and _QT_PLATFORM_PLUGIN_PATH.exists():
            if str(_QT_PLATFORM_PLUGIN_PATH) not in QCoreApplication.libraryPaths():
                QCoreApplication.addLibraryPath(str(_QT_PLATFORM_PLUGIN_PATH))
    except Exception:
        pass

    if sys.platform == "darwin":

        def _parse_version(raw: str) -> tuple[int, ...]:
            parts: list[int] = []
            for piece in re.split(r"[.+-]", raw):
                if piece.isdigit():
                    parts.append(int(piece))
                else:
                    match = re.match(r"(\d+)", piece)
                    if match:
                        parts.append(int(match.group(1)))
                    break
            return tuple(parts)

        _parsed_version = _parse_version(_PYSIDE_VERSION)
        if _parsed_version >= (6, 9) or _parsed_version < (6, 8, 3):
            raise RuntimeError(
                "PySide6 6.8.[0-2] and 6.9.x are incompatible with macOS Sequoia and Python 3.13 "
                "because the bundled Cocoa platform plugin fails to load. Install PySide6 6.8.3 "
                "(with matching Essentials/Addons) before launching the GUI."
            )

    PYSIDE_AVAILABLE = True
except ModuleNotFoundError as exc:  # pragma: no cover - guard when GUI deps missing
    PYSIDE_AVAILABLE = False
    _PYSIDE_IMPORT_ERROR = exc

from .components import ModernButton, ModernCard, ModernCheckbox, ModernLineEdit
from .helpers import (
    TOOL_VERSION,
    ThemeToggle,
    add_branding,
    load_app_icon,
    resource_path,
)
from .steps import (
    AnalysisPage,
    ModeSelectionPage,
    ObjectSelectionPage,
    OptionsPage,
    ProgressPage,
    SourceSettingsPage,
    SummaryPage,
    TargetSettingsPage,
    WelcomePage,
)
from .styles.button_styles import (
    PRIMARY_BUTTON_STYLE,
    SECONDARY_BUTTON_STYLE,
    TERTIARY_BUTTON_STYLE,
)
from .theme_manager import ThemeMode, get_theme_manager

DEFAULT_EXPORT_DIRECTORY = Path("artifacts")
DEFAULT_SOURCE_PROVIDER = "Okta"
DEFAULT_TARGET_PROVIDER = "OneLogin"
OBJECT_KEYS = ["users", "groups", "applications", "policies"]
DEFAULT_OKTA_RATE_LIMIT = 600
DEFAULT_ONELOGIN_RATE_LIMIT = 5000


@dataclass
class WizardState:
    mode: Literal["discovery", "migration"] = "migration"
    source_provider: str = DEFAULT_SOURCE_PROVIDER
    source_settings: dict[str, Any] = field(default_factory=dict)
    target_provider: str = DEFAULT_TARGET_PROVIDER
    target_settings: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(
        default_factory=lambda: {
            "dry_run": True,
            "concurrency_enabled": False,
            "max_workers": 4,
            "export_directory": str(DEFAULT_EXPORT_DIRECTORY),
            "chunk_size": 200,
            "bulk_user_upload": False,
            "verbose": False,
        }
    )
    objects: dict[str, bool] = field(
        default_factory=lambda: {
            "users": True,
            "groups": True,
            "applications": True,
            "policies": False,
        }
    )
    # Selective migration: uses inverse selection for scalability with 100k+ entities
    # Either selected_* OR excluded_* is set, never both:
    # - selected_X set = include only these IDs (exclude all others)
    # - excluded_X set = exclude only these IDs (include all others)
    # - both None = include all (default)
    selected_users: set[str] | None = None
    selected_groups: set[str] | None = None
    selected_applications: set[str] | None = None
    selected_custom_attributes: set[str] | None = None
    excluded_users: set[str] | None = None
    excluded_groups: set[str] | None = None
    excluded_applications: set[str] | None = None
    excluded_custom_attributes: set[str] | None = None
    profile_path: Path | None = None
    raw_export: dict[str, Any] | None = None
    export_file_path: Path | None = None  # Path to saved encrypted export file

    def to_config_dict(self) -> dict[str, Any]:
        def _int_value(source: dict[str, Any], key: str, default: int) -> int:
            raw = source.get(key, default)
            try:
                return int(str(raw).strip())
            except (TypeError, ValueError):
                return default

        provider = (self.source_provider or DEFAULT_SOURCE_PROVIDER).strip()
        provider_slug = provider.lower()
        domain = self.source_settings.get("domain", "").strip()
        legacy_subdomain = self.source_settings.get("subdomain", "").strip()
        if not domain and legacy_subdomain:
            domain = f"{legacy_subdomain}.okta.com"
        if not domain:
            raise ValueError(f"{provider} domain is required")
        token = self.source_settings.get("token", "").strip()
        if not token:
            raise ValueError(f"{provider} API token is required")

        # Skip target validation in Discovery mode
        if self.mode == "discovery":
            target_id = ""
            target_secret = ""
        else:
            target_id = self.target_settings.get("client_id", "").strip()
            target_secret = self.target_settings.get("client_secret", "").strip()
            if not target_id or not target_secret:
                raise ValueError("OneLogin credentials are required")
        region = self.target_settings.get("region", "us").strip() or "us"
        subdomain_target = self.target_settings.get("subdomain", "").strip()
        source_rate_limit = _int_value(
            self.source_settings, "rate_limit_per_minute", DEFAULT_OKTA_RATE_LIMIT
        )
        onelogin_rate_limit = _int_value(
            self.target_settings, "rate_limit_per_hour", DEFAULT_ONELOGIN_RATE_LIMIT
        )
        max_workers_option = self.options.get("max_workers", 0)
        try:
            max_workers_value = int(max_workers_option)
        except (TypeError, ValueError):
            max_workers_value = 4
        # Prepare selections for config using inverse selection for scalability
        # Format: {"users": {"ids": [...], "inverse": bool}}
        selections = {}
        for category in ["users", "groups", "applications", "custom_attributes"]:
            selected_attr = f"selected_{category}"
            excluded_attr = f"excluded_{category}"
            selected = getattr(self, selected_attr, None)
            excluded = getattr(self, excluded_attr, None)

            if excluded is not None:
                # Exclude mode: store excluded IDs
                selections[category] = {
                    "ids": list(excluded) if excluded else [],
                    "inverse": True,
                }
            elif selected is not None:
                # Include mode: store selected IDs
                selections[category] = {
                    "ids": list(selected) if selected else [],
                    "inverse": False,
                }
            # If both None, don't add to selections (means "all")

        return {
            "dry_run": bool(self.options.get("dry_run", True)),
            "export_directory": self.options.get("export_directory", str(DEFAULT_EXPORT_DIRECTORY)),
            "chunk_size": int(self.options.get("chunk_size", 200)),
            "concurrency_enabled": bool(self.options.get("concurrency_enabled", False)),
            "max_workers": max_workers_value,
            "bulk_user_upload": bool(self.options.get("bulk_user_upload", False)),
            "source": {
                "provider": provider_slug,
                "domain": domain,
                "token": token,
                "rate_limit_per_minute": source_rate_limit,
                "page_size": 200,
            },
            "onelogin": {
                "client_id": target_id,
                "client_secret": target_secret,
                "region": region,
                "subdomain": subdomain_target,
                "rate_limit_per_hour": onelogin_rate_limit,
            },
            "categories": dict(self.objects),
            "selections": selections,  # Add selections to config
            "metadata": {},
        }

    def to_profile_dict(self, include_credentials: bool = False) -> dict[str, Any]:
        source_settings = dict(self.source_settings)
        target_settings = dict(self.target_settings)

        if not include_credentials:
            source_settings.pop("token", None)
            target_settings.pop("client_secret", None)

        profile: dict[str, Any] = {
            "source": {
                "provider": self.source_provider,
                "settings": source_settings,
            },
            "target": {
                "provider": self.target_provider,
                "settings": target_settings,
            },
            "options": dict(self.options),
            "objects": dict(self.objects),
        }
        return profile

    def to_migration_settings(self) -> MigrationSettings:
        return MigrationSettings.from_dict(self.to_config_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WizardState:
        if "source" not in data or "target" not in data:
            try:
                settings = MigrationSettings.from_dict(data)
            except Exception:
                return cls()
            return cls.from_migration_settings(settings)
        instance = cls()
        source = data.get("source", {})
        target = data.get("target", {})
        options = data.get("options", {})
        objects = data.get("objects", {})
        instance.source_provider = source.get("provider", DEFAULT_SOURCE_PROVIDER)
        instance.source_settings = source.get("settings", {})
        if (
            isinstance(instance.source_settings, dict)
            and "domain" not in instance.source_settings
            and instance.source_settings.get("subdomain")
        ):
            instance.source_settings["domain"] = (
                f"{instance.source_settings['subdomain'].strip()}.okta.com"
            )
        instance.target_provider = target.get("provider", DEFAULT_TARGET_PROVIDER)
        instance.target_settings = target.get("settings", {})
        instance.options.update(options)
        instance.objects.update(objects)
        return instance

    @classmethod
    def from_migration_settings(cls, settings: MigrationSettings) -> WizardState:
        state = cls()
        state.source_provider = getattr(
            settings.source, "provider_display_name", DEFAULT_SOURCE_PROVIDER
        )
        domain = getattr(settings.source, "domain", "")
        normalized = domain.replace("https://", "").replace("http://", "")
        state.source_settings = {
            "domain": normalized,
            "token": getattr(settings.source, "token", ""),
            "rate_limit_per_minute": str(
                getattr(settings.source, "rate_limit_per_minute", DEFAULT_OKTA_RATE_LIMIT)
            ),
        }
        state.target_settings = {
            "client_id": getattr(settings.onelogin, "client_id", ""),
            "client_secret": getattr(settings.onelogin, "client_secret", ""),
            "region": getattr(settings.onelogin, "region", ""),
            "subdomain": getattr(settings.onelogin, "subdomain", ""),
            "rate_limit_per_hour": str(
                getattr(
                    settings.onelogin,
                    "rate_limit_per_hour",
                    DEFAULT_ONELOGIN_RATE_LIMIT,
                )
            ),
        }
        state.options.update(
            {
                "dry_run": settings.dry_run,
                "concurrency_enabled": settings.concurrency_enabled,
                "max_workers": settings.max_workers,
                "export_directory": str(settings.export_directory),
                "chunk_size": settings.chunk_size,
                "bulk_user_upload": getattr(settings, "bulk_user_upload", False),
                "verbose": state.options.get("verbose", False),
            }
        )
        state.objects.update(settings.categories)
        return state


class MigrationWorker(QObject):
    overall_progress = Signal(int)
    object_progress = Signal(str, int)
    category_progress = Signal(str, int, int)  # (category, completed, total)
    log_message = Signal(str)
    log_entry = Signal(dict)  # Structured log entry
    fatal_error = Signal(dict)  # Fatal error details
    finished = Signal()
    failed = Signal(str)

    def __init__(self, state: WizardState) -> None:
        super().__init__()
        self.state = state
        self._cancelled = False
        self.manager: MigrationManager | None = None
        self.bulk_output_path: str | None = None
        self._log_handler: QtLogHandler | None = None
        self._file_handler: logging.FileHandler | None = None

    @Slot()
    def run(self) -> None:  # pragma: no cover - threaded execution
        import logging
        import traceback
        from datetime import datetime

        from .logging_handler import QtLogHandler

        try:
            # Set up logging
            verbose = self.state.options.get("verbose", False)
            self._setup_logging(verbose)

            settings = self.state.to_migration_settings()
            self.manager = MigrationManager(settings, dry_run=settings.dry_run)

            def progress_callback(snapshot: ProgressSnapshot) -> None:
                self.overall_progress.emit(int(snapshot.overall_percent))
                for key in OBJECT_KEYS:
                    self.object_progress.emit(key, int(snapshot.percent(key)))
                    # Emit actual counts for status cards
                    completed = snapshot.completed.get(key, 0)
                    total = snapshot.totals.get(key, 0)
                    self.category_progress.emit(key, completed, total)

            self.manager.progress.subscribe(progress_callback)
            self.log_message.emit("Starting migration...")

            # Handle custom attribute provisioning if enabled
            provision_attributes = self.state.options.get("provision_attributes", False)
            if provision_attributes:
                self.log_message.emit("Provisioning custom attributes...")
                try:
                    # Export users from the source provider to analyze
                    export_data = self.manager.export_from_source()
                    users = export_data.get("users", [])

                    # Discover custom attributes
                    attributes = self.manager.discover_custom_attributes(users)

                    if attributes:
                        self.log_message.emit(f"Discovered {len(attributes)} custom attributes")

                        # Provision them in OneLogin
                        result = self.manager.provision_custom_attributes(attributes)

                        if result["created"]:
                            self.log_message.emit(
                                f"✓ Created {len(result['created'])} new attributes"
                            )
                        if result["existing"]:
                            self.log_message.emit(
                                f"ℹ {len(result['existing'])} attributes already exist"
                            )
                        if result["failed"]:
                            self.log_message.emit(
                                f"✗ Failed to create {len(result['failed'])} attributes"
                            )
                    else:
                        self.log_message.emit("No custom attributes found")
                except Exception as exc:
                    self.log_message.emit(f"Warning: Custom attribute provisioning failed: {exc}")

            # Save the analysis export if it exists and hasn't been saved yet
            export_file_to_use = None
            if self.state.raw_export and not self.state.export_file_path:
                try:
                    self.log_message.emit("Saving analysis data to encrypted file...")
                    export_file_to_use = self.manager.save_export(self.state.raw_export)
                    self.state.export_file_path = export_file_to_use
                    logging.getLogger(__name__).info(
                        "Saved analysis export to %s", export_file_to_use
                    )
                except Exception as exc:
                    logging.getLogger(__name__).warning("Failed to save analysis export: %s", exc)
                    # Continue anyway - manager will fetch from the source provider
            elif self.state.export_file_path:
                export_file_to_use = self.state.export_file_path
                logging.getLogger(__name__).info("Reusing saved export from %s", export_file_to_use)

            try:
                self.manager.run(export_file=export_file_to_use, force_import=True)
                if self._cancelled or self.manager.was_stopped():
                    self.log_message.emit("Migration cancelled.")
                else:
                    self.log_message.emit("Migration complete.")
            except MigrationAborted:
                self.log_message.emit("Migration cancelled.")
            self.bulk_output_path = (
                str(self.manager.last_bulk_export)
                if self.manager.last_bulk_export is not None
                else None
            )
            self.finished.emit()
        except Exception as exc:  # pragma: no cover - best effort logging
            # This is a fatal error
            error_message = str(exc)
            error_details = traceback.format_exc() if verbose else None

            # Emit fatal error signal
            self.fatal_error.emit(
                {
                    "message": error_message,
                    "details": error_details,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Also persist to database
            self._persist_error_to_db(error_message, error_details)

            self.failed.emit(error_message)
        finally:
            # Clean up logging handlers
            self._cleanup_logging()

            # Clean up manager resources
            if self.manager:
                try:
                    # Close any open HTTP sessions
                    source_client = getattr(self.manager, "source", None) or getattr(
                        self.manager, "okta", None
                    )
                    if source_client and hasattr(source_client, "session"):
                        source_client.session.close()

                    onelogin_client = getattr(self.manager, "onelogin", None) or getattr(
                        self.manager, "onelogin_client", None
                    )
                    if onelogin_client and hasattr(onelogin_client, "session"):
                        onelogin_client.session.close()
                except Exception:
                    pass  # Best effort cleanup
                finally:
                    self.manager = None

    def _setup_logging(self, verbose: bool) -> None:
        """Set up logging handlers for the migration.

        Args:
            verbose: Whether to enable verbose logging
        """
        import logging
        from datetime import datetime

        from .logging_handler import QtLogHandler

        # Create Qt log handler
        self._log_handler = QtLogHandler(verbose=verbose)
        self._log_handler.log_entry_signal.connect(self.log_entry.emit)
        # Set handler level to allow DEBUG messages in verbose mode
        self._log_handler.setLevel(logging.DEBUG if verbose else logging.INFO)

        # Add handler to root logger for onelogin_migration_core
        core_logger = logging.getLogger("onelogin_migration_core")
        core_logger.addHandler(self._log_handler)
        core_logger.setLevel(logging.DEBUG if verbose else logging.INFO)

        # Set up file logging if verbose mode is enabled
        if verbose:
            export_dir = Path(self.state.options.get("export_directory", "./exports"))
            export_dir.mkdir(parents=True, exist_ok=True)

            # Create log filename: source_target_date.log
            source = self.state.source_provider.lower()
            target = self.state.target_provider.lower()
            date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            log_filename = f"{source}_{target}_{date_str}.log"
            log_path = export_dir / log_filename

            # Create file handler
            self._file_handler = logging.FileHandler(log_path, encoding="utf-8")
            self._file_handler.setLevel(logging.DEBUG)

            # Set formatter
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            self._file_handler.setFormatter(formatter)

            # Add file handler to core logger
            core_logger.addHandler(self._file_handler)

            self.log_message.emit(f"Verbose logging enabled. Log file: {log_path}")

    def _cleanup_logging(self) -> None:
        """Clean up logging handlers."""
        import logging

        core_logger = logging.getLogger("onelogin_migration_core")

        if self._log_handler:
            core_logger.removeHandler(self._log_handler)
            self._log_handler = None

        if self._file_handler:
            core_logger.removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None

    def _persist_error_to_db(self, error_message: str, error_details: str | None) -> None:
        """Persist fatal error to database.

        Args:
            error_message: Brief error message
            error_details: Full error details (stack trace)
        """
        try:
            from datetime import datetime

            from onelogin_migration_core.db.database_manager import get_database_manager

            db = get_database_manager()

            # Insert into migration_events table
            db.user_conn.execute(
                """
                INSERT INTO migration_events
                (migration_run_id, timestamp, event_type, error_message, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "gui_migration",  # We don't have a specific run ID in GUI yet
                    datetime.now().isoformat(),
                    "fatal_error",
                    error_message,
                    error_details,  # Store full stack trace in metadata
                ),
            )
            db.user_conn.commit()
        except Exception:
            # Best effort - don't let DB errors break the error handling
            pass

    def request_cancel(self) -> None:
        self._cancelled = True
        if self.manager is not None:
            self.manager.request_stop()


class MigrationWizardWindow(QMainWindow):
    def __init__(
        self,
        config_path: Path | None = None,
        template_path: Path | None = None,
        export_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("OneLogin Migration Wizard")
        self.state = WizardState()
        self.template_path = template_path
        self.export_path = export_path
        self.config_path = Path(config_path) if config_path else Path("config/migration.yaml")
        self.thread: QThread | None = None
        self.worker: MigrationWorker | None = None
        self.bulk_output_path: str | None = None

        # Initialize credential manager
        # Use memory backend for PyInstaller builds (unsigned) to avoid keychain errors
        # PyInstaller builds can't reliably use macOS keychain because each build
        # appears as a different app (error -25244: Invalid attempt to change owner)
        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            # PyInstaller build: use memory backend (credentials don't persist across restarts)
            self.credential_manager = AutoSaveCredentialManager(
                storage_backend="memory",
                enable_auto_save=True,
                enable_audit_log=True,
                auto_save_delay=2.0,
            )
        else:
            # Development build: try keyring, fallback to memory if it fails
            try:
                self.credential_manager = AutoSaveCredentialManager(
                    storage_backend="keyring",
                    enable_auto_save=True,
                    enable_audit_log=True,
                    auto_save_delay=2.0,
                )
            except Exception:
                # Fallback to memory backend if keyring fails
                self.credential_manager = AutoSaveCredentialManager(
                    storage_backend="memory",
                    enable_auto_save=True,
                    enable_audit_log=True,
                    auto_save_delay=2.0,
                )

        # Initialize theme manager and apply theme
        self.theme_manager = get_theme_manager()
        self.theme_manager.theme_changed.connect(self._apply_theme)

        self._build_ui()
        self._apply_theme()  # Apply initial theme

        # Check for stale migration state and prompt user
        stale_info = self._check_stale_state()
        if stale_info:
            action = self._show_state_cleanup_dialog(stale_info)
            if action == "start_fresh":
                # Delete the stale state file
                try:
                    state_file = stale_info.get("state_file")
                    if state_file and state_file.exists():
                        state_file.unlink()
                        from PySide6.QtWidgets import QMessageBox

                        QMessageBox.information(
                            self,
                            "State Cleared",
                            "Previous migration state has been cleared. You can start a fresh migration.",
                        )
                except Exception as e:
                    from PySide6.QtWidgets import QMessageBox

                    QMessageBox.warning(
                        self,
                        "Error Clearing State",
                        f"Failed to delete state file: {e}\n\nYou may need to delete it manually.",
                    )

        if self.config_path.exists():
            self.load_profile(self.config_path)

    def _apply_theme(self) -> None:
        """Apply current theme to the main window."""
        bg_color = self.theme_manager.get_color("background")
        text_color = self.theme_manager.get_color("text_primary")
        surface_color = self.theme_manager.get_color("surface")

        # Apply theme to main window and all widgets
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background-color: {bg_color};
            }}
            QWidget {{
                background-color: {bg_color};
                color: {text_color};
            }}
            QLabel {{
                color: {text_color};
                background-color: transparent;
            }}
            QGroupBox {{
                color: {text_color};
                background-color: transparent;
            }}
        """
        )

        # Re-apply button styles with updated palette values
        self.load_button.setStyleSheet(PRIMARY_BUTTON_STYLE())
        self.prev_button.setStyleSheet(SECONDARY_BUTTON_STYLE())
        self.next_button.setStyleSheet(PRIMARY_BUTTON_STYLE())
        self.start_button.setStyleSheet(PRIMARY_BUTTON_STYLE())

    def _check_stale_state(self) -> dict[str, Any] | None:
        """Check for stale migration state file from previous failed run.

        Returns dict with state info if stale, None if clean.
        """
        from datetime import datetime
        from pathlib import Path

        # Get export directory from state options or default
        export_dir_str = self.state.options.get("export_directory", "./artifacts")
        export_dir = Path(export_dir_str)
        state_file = export_dir / "migration_state.json"

        if not state_file.exists():
            return None

        try:
            import json

            # Read state file
            state_data = json.loads(state_file.read_text())
            status = state_data.get("status", "unknown")
            last_updated_str = state_data.get("last_updated")
            migration_run_id = state_data.get("migration_run_id")
            error_type = state_data.get("error_type")
            error_message = state_data.get("error_message")

            # Parse timestamp
            last_updated = None
            if last_updated_str:
                try:
                    last_updated = datetime.fromisoformat(last_updated_str)
                except (ValueError, TypeError):
                    pass

            # Check if state indicates failure
            if status == "failed":
                return {
                    "state_file": state_file,
                    "status": status,
                    "last_updated": last_updated,
                    "migration_run_id": migration_run_id,
                    "error_type": error_type,
                    "error_message": error_message,
                    "reason": "failed",
                }

            # Check if state is in-progress but old (>24 hours)
            if status == "in_progress" and last_updated:
                age_hours = (datetime.now() - last_updated).total_seconds() / 3600
                if age_hours > 24:
                    return {
                        "state_file": state_file,
                        "status": status,
                        "last_updated": last_updated,
                        "migration_run_id": migration_run_id,
                        "reason": "stale",
                        "age_hours": age_hours,
                    }

            # Check if state is cancelled
            if status == "cancelled":
                return {
                    "state_file": state_file,
                    "status": status,
                    "last_updated": last_updated,
                    "migration_run_id": migration_run_id,
                    "reason": "cancelled",
                }

        except (json.JSONDecodeError, OSError) as e:
            # State file is corrupted
            return {
                "state_file": state_file,
                "status": "corrupted",
                "reason": "corrupted",
                "error": str(e),
            }

        return None

    def _show_state_cleanup_dialog(self, stale_info: dict[str, Any]) -> str:
        """Show dialog asking user what to do with stale state.

        Args:
            stale_info: Dictionary with stale state information

        Returns:
            "start_fresh" or "resume" or "view_details"
        """
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QTextEdit,
            QVBoxLayout,
        )

        reason = stale_info.get("reason", "unknown")
        status = stale_info.get("status", "unknown")
        last_updated = stale_info.get("last_updated")

        # Build message based on reason
        if reason == "failed":
            error_type = stale_info.get("error_type", "Unknown")
            error_msg = stale_info.get("error_message", "No details available")
            title = "Previous Migration Failed"
            message = (
                f"A previous migration failed with an error.\n\n"
                f"Error Type: {error_type}\n"
                f"Error: {error_msg[:200]}...\n"
            )
            if last_updated:
                message += f"\nFailed at: {last_updated.strftime('%Y-%m-%d %H:%M:%S')}\n"
        elif reason == "stale":
            age_hours = stale_info.get("age_hours", 0)
            title = "Incomplete Migration Detected"
            message = (
                f"Found an incomplete migration from {last_updated.strftime('%Y-%m-%d %H:%M:%S') if last_updated else 'unknown time'}.\n\n"
                f"Age: {age_hours:.1f} hours\n\n"
                "The migration appears to have been interrupted."
            )
        elif reason == "cancelled":
            title = "Cancelled Migration Detected"
            message = (
                f"Found a cancelled migration from {last_updated.strftime('%Y-%m-%d %H:%M:%S') if last_updated else 'unknown time'}.\n\n"
                "The previous migration was cancelled before completion."
            )
        elif reason == "corrupted":
            title = "Corrupted State File"
            error = stale_info.get("error", "Unknown error")
            message = (
                "The migration state file is corrupted and cannot be read.\n\n"
                f"Error: {error}\n\n"
                "It's recommended to start fresh."
            )
        else:
            title = "Unexpected State Detected"
            message = f"Found migration state with status: {status}\n\n"

        message += (
            "\n\nWhat would you like to do?\n\n"
            "• Start Fresh: Delete the old state and begin a new migration\n"
            "  (Recommended for errors)\n\n"
            "• Resume: Attempt to continue from where it left off\n"
            "  (May fail if state is invalid)"
        )

        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout()

        # Message label
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)

        # Button box
        button_box = QDialogButtonBox()
        start_fresh_button = button_box.addButton(
            "Start Fresh", QDialogButtonBox.ButtonRole.AcceptRole
        )
        resume_button = button_box.addButton("Resume", QDialogButtonBox.ButtonRole.RejectRole)

        # Set default button based on reason
        if reason in ("failed", "corrupted"):
            start_fresh_button.setDefault(True)
        else:
            resume_button.setDefault(True)

        layout.addWidget(button_box)
        dialog.setLayout(layout)

        # Connect buttons
        result = {"action": "resume"}

        def on_start_fresh():
            result["action"] = "start_fresh"
            dialog.accept()

        def on_resume():
            result["action"] = "resume"
            dialog.accept()

        start_fresh_button.clicked.connect(on_start_fresh)
        resume_button.clicked.connect(on_resume)

        dialog.exec()
        return result["action"]

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        # Add these lines immediately after setCentralWidget:
        self.resize(800, 850)  # Set a good default size
        self.setMinimumSize(
            750, 850
        )  # Prevent window from getting too small - enough for all form fields
        self.setMaximumSize(1000, 850)  # Fixed height, variable width

        root_layout = QVBoxLayout(central)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack)
        self._containers: dict[QWidget, QWidget] = {}

        nav_row = QHBoxLayout()
        self.version_label = QLabel(TOOL_VERSION)
        self.version_label.setObjectName("MigrationWizardVersionLabel")
        self.version_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.version_label.setStyleSheet("color: #00adef; font-size: 10pt;")
        nav_row.addWidget(self.version_label)
        nav_row.addStretch(1)
        self.load_button = QPushButton("Load Profile 📂")
        self.load_button.setStyleSheet(PRIMARY_BUTTON_STYLE())
        self.prev_button = QPushButton("← Previous")
        self.prev_button.setStyleSheet(SECONDARY_BUTTON_STYLE())
        self.next_button = QPushButton("Next →")
        self.next_button.setStyleSheet(PRIMARY_BUTTON_STYLE())
        self.start_button = QPushButton("Start Migration")
        self.start_button.setStyleSheet(PRIMARY_BUTTON_STYLE())
        self.start_button.setVisible(False)
        self.finish_button = QPushButton("Finish")
        self.finish_button.setStyleSheet(PRIMARY_BUTTON_STYLE())
        self.finish_button.setVisible(False)
        nav_row.addWidget(self.load_button)
        nav_row.addStretch(1)
        nav_row.addWidget(self.prev_button)
        nav_row.addWidget(self.next_button)
        nav_row.addWidget(self.start_button)
        nav_row.addWidget(self.finish_button)
        root_layout.addLayout(nav_row)

        self.mode_selection_page = ModeSelectionPage()
        self.welcome_page = WelcomePage()
        self.source_settings_page = SourceSettingsPage(credential_manager=self.credential_manager)
        self.target_settings_page = TargetSettingsPage(credential_manager=self.credential_manager)
        self.analysis_page = AnalysisPage()
        self.options_page = OptionsPage()
        self.objects_page = ObjectSelectionPage()
        self.summary_page = SummaryPage()
        self.progress_page = ProgressPage()

        ordered_pages = (
            self.mode_selection_page,
            self.welcome_page,
            self.source_settings_page,
            self.target_settings_page,
            self.options_page,
            self.analysis_page,
            self.objects_page,
            self.summary_page,
            self.progress_page,
        )

        for page in ordered_pages:
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.addWidget(page)
            layout.addStretch(1)
            self.stack.addWidget(container)
            self._containers[page] = container

        # Build initial page sequence based on current mode
        self._rebuild_page_sequence()

        self.mode_selection_page.completeChanged.connect(self.update_navigation)
        self.mode_selection_page.mode_changed.connect(self._on_mode_changed)
        self.welcome_page.completeChanged.connect(self.update_navigation)
        self.source_settings_page.completeChanged.connect(self.update_navigation)
        self.source_settings_page.connection_test_requested.connect(self._handle_source_test)
        self.source_settings_page.auto_advance_requested.connect(self._handle_auto_advance)
        self.target_settings_page.completeChanged.connect(self.update_navigation)
        self.target_settings_page.connection_test_requested.connect(self._handle_target_test)
        self.target_settings_page.auto_advance_requested.connect(self._handle_auto_advance)
        self.options_page.completeChanged.connect(self.update_navigation)
        self.objects_page.completeChanged.connect(self.update_navigation)
        self.analysis_page.completeChanged.connect(self.update_navigation)
        self.summary_page.completeChanged.connect(self.update_navigation)
        self.progress_page.cancel_requested.connect(self.cancel_migration)
        self.progress_page.open_bulk_location_requested.connect(self.open_bulk_location)
        self.progress_page.finish_requested.connect(self.finish_wizard)

        self.prev_button.clicked.connect(self.go_previous)
        self.next_button.clicked.connect(self.go_next)
        self.start_button.clicked.connect(self.start_migration)
        self.finish_button.clicked.connect(self.finish_wizard)
        self.load_button.clicked.connect(self.load_profile_dialog)

        self.mode_selection_page.on_enter(self.state)
        self.welcome_page.on_enter(self.state)
        self.source_settings_page.set_values(self.state.source_settings)
        self.target_settings_page.set_values(self.state.target_settings)
        self.options_page.on_enter(self.state)
        self.objects_page.on_enter(self.state)
        self.update_navigation()

    def _rebuild_page_sequence(self) -> None:
        """Rebuild the pages list based on current mode."""
        if self.state.mode == "discovery":
            # Discovery mode: Mode Selection -> Welcome -> Source -> Analysis
            self.pages: list[Any] = [
                self.mode_selection_page,
                self.welcome_page,
                self.source_settings_page,
                self.analysis_page,
            ]
        else:
            # Migration mode: Full workflow
            self.pages: list[Any] = [
                self.mode_selection_page,
                self.welcome_page,
                self.source_settings_page,
                self.target_settings_page,
                self.options_page,
                self.analysis_page,
                self.objects_page,
                self.summary_page,
            ]

        # Update page titles with dynamic step numbers
        self._update_page_titles()

    def _update_page_titles(self) -> None:
        """Update page titles with dynamic step numbers based on position in pages list."""
        # Mapping of pages to their base titles (without step numbers)
        title_map = {
            self.mode_selection_page: "Choose Your Workflow",
            self.welcome_page: "Welcome",
            self.source_settings_page: "Source Settings",
            self.target_settings_page: "Target Settings",
            self.options_page: "Migration Options",
            self.analysis_page: "Environment Analysis",
            self.objects_page: "Select Objects to Migrate",
            self.summary_page: "Review and Start Migration",
        }

        for index, page in enumerate(self.pages):
            if page in title_map:
                base_title = title_map[page]
                # Don't add step numbers to mode selection or welcome pages
                if page in (self.mode_selection_page, self.welcome_page):
                    page.setTitle(base_title)
                else:
                    # Step number starts after welcome page
                    step_num = index - 1  # Subtract 1 to account for mode selection page
                    page.setTitle(f"Step {step_num} – {base_title}")

    def _on_mode_changed(self, mode: str) -> None:
        """Handle mode change from ModeSelectionPage."""
        self.state.mode = mode
        self._rebuild_page_sequence()
        self.update_navigation()

    def _handle_source_test(self, data: dict[str, Any]) -> None:
        success, message = self._perform_connection_test(DEFAULT_SOURCE_PROVIDER, data)
        # Customize success message with provider name
        if success:
            provider_name = self.source_settings_page.get_provider_name()
            message = f"Successfully Authenticated with {provider_name}"
        self.source_settings_page.show_validation_status(success, message)
        if success:
            self.state.source_settings.update(data)

    def _handle_target_test(self, data: dict[str, Any]) -> None:
        success, message = self._perform_connection_test(DEFAULT_TARGET_PROVIDER, data)
        # Hardcode success message to "Successfully Authenticated with OneLogin"
        if success:
            message = "Successfully Authenticated with OneLogin"
        self.target_settings_page.show_validation_status(success, message)
        if success:
            self.state.target_settings.update(data)

    def _handle_auto_advance(self) -> None:
        """Handle auto-advance from provider settings pages after successful verification."""
        self.go_next()

    def update_navigation(self) -> None:
        current_page = self.current_page
        is_progress = current_page is self.progress_page

        # Find current page's position in the pages list
        try:
            page_index = self.pages.index(current_page)
        except ValueError:
            # Current page not in pages list (e.g., progress page)
            page_index = -1

        if is_progress and (self.thread is None or not self.thread.isRunning()):
            self.prev_button.setEnabled(True)
        else:
            self.prev_button.setEnabled(page_index > 0 and not is_progress)
        can_proceed = current_page.can_proceed(self.state)

        # Check if we're in Discovery mode on the last page (Analysis)
        is_discovery_final = (
            self.state.mode == "discovery"
            and current_page is self.analysis_page
            and page_index == len(self.pages) - 1
        )

        # Show Finish button in Discovery mode on Analysis page, otherwise Next
        if is_discovery_final:
            self.next_button.setVisible(False)
            self.finish_button.setVisible(True)
            self.finish_button.setEnabled(can_proceed)
        else:
            self.finish_button.setVisible(False)
            self.next_button.setVisible(
                page_index >= 0 and page_index < len(self.pages) - 1 and not is_progress
            )
            self.next_button.setEnabled(not is_progress and can_proceed)

        # Change button label based on whether provider page needs verification
        page = self.current_page
        if isinstance(page, (SourceSettingsPage, TargetSettingsPage)):
            if hasattr(page, "needs_verification") and page.needs_verification():
                self.next_button.setText("Verify →")
            else:
                self.next_button.setText("Next →")
        else:
            self.next_button.setText("Next →")

        self.start_button.setVisible(self.current_page is self.summary_page)
        self.load_button.setEnabled(not is_progress)

    @property
    def current_page(self) -> Any:
        """Get the current page from the stack."""
        stack_index = self.stack.currentIndex()
        # Find which page in self.pages corresponds to this stack index
        for page in self.pages:
            if self._containers.get(page) is self.stack.widget(stack_index):
                return page
        # If not found in pages list, check if it's the progress page
        if self._containers.get(self.progress_page) is self.stack.widget(stack_index):
            return self.progress_page
        # Fallback to progress page
        return self.progress_page

    def go_next(self) -> None:
        page = self.current_page

        # Cancel any pending auto-advance timer from provider pages
        if isinstance(page, (SourceSettingsPage, TargetSettingsPage)):
            page._cancel_auto_advance()

        # For provider pages, handle verification differently
        if isinstance(page, SourceSettingsPage):
            page.collect(self.state)
            # If not yet validated, perform verification (button says "Verify")
            if page.needs_verification():
                data = self.state.source_settings
                success, message = self._perform_connection_test(DEFAULT_SOURCE_PROVIDER, data)
                # Customize success message with provider name
                if success:
                    provider_name = self.source_settings_page.get_provider_name()
                    message = f"Successfully Authenticated with {provider_name}"
                self.source_settings_page.show_validation_status(success, message)
                # Don't proceed to next page - just show result and change button to "Next →"
                self.update_navigation()
                return
            else:
                # Already validated, now actually proceed to next page
                valid, message = page.validate(self.state)
                if not valid:
                    return
        elif isinstance(page, TargetSettingsPage):
            page.collect(self.state)
            # If not yet validated, perform verification (button says "Verify")
            if page.needs_verification():
                data = self.state.target_settings
                success, message = self._perform_connection_test(DEFAULT_TARGET_PROVIDER, data)
                # Hardcode success message to "Successfully Authenticated with OneLogin"
                if success:
                    message = "Successfully Authenticated with OneLogin"
                self.target_settings_page.show_validation_status(success, message)
                # Don't proceed to next page - just show result and change button to "Next →"
                self.update_navigation()
                return
            else:
                # Already validated, now actually proceed to next page
                valid, message = page.validate(self.state)
                if not valid:
                    return
        else:
            # For non-provider pages, use standard validation
            valid, message = page.validate(self.state)
            if not valid:
                QMessageBox.warning(self, "Validation", message)
                return
            page.collect(self.state)

        # Proceed to next page
        current_page = self.current_page
        # Find current page's position in the pages list
        try:
            current_page_index = self.pages.index(current_page)
        except ValueError:
            # Current page not in pages list, shouldn't happen
            return

        # Get the next page from the pages list
        next_page_index = current_page_index + 1
        if next_page_index < len(self.pages):
            next_page = self.pages[next_page_index]
            # Find the stack index for this page
            next_stack_index = self.stack.indexOf(self._containers[next_page])
            if next_stack_index >= 0:
                self.stack.setCurrentIndex(next_stack_index)
                next_page.on_enter(self.state)
                self.update_navigation()
        self.persist_state()

    def go_previous(self) -> None:
        current_page = self.current_page
        # Find current page's position in the pages list
        try:
            current_page_index = self.pages.index(current_page)
        except ValueError:
            # Current page not in pages list, shouldn't happen
            return

        # Can't go back from first page
        if current_page_index == 0:
            return

        # Get the previous page from the pages list
        prev_page_index = current_page_index - 1
        prev_page = self.pages[prev_page_index]
        # Find the stack index for this page
        prev_stack_index = self.stack.indexOf(self._containers[prev_page])
        if prev_stack_index >= 0:
            self.stack.setCurrentIndex(prev_stack_index)
            self.update_navigation()

    def start_migration(self) -> None:
        for page in self.pages:
            page.collect(self.state)
        self.persist_state()
        self.progress_page.reset()
        self.progress_page.set_active_categories(self.state.objects)
        self.progress_page.cancel_button.setEnabled(True)
        self.progress_page.finish_button.setVisible(False)
        self.progress_page.finish_button.setEnabled(False)
        self.stack.setCurrentWidget(self._containers[self.progress_page])
        self.update_navigation()
        self.prev_button.setEnabled(False)
        self.next_button.setVisible(False)
        self.start_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.bulk_output_path = None

        self.worker = MigrationWorker(self.state)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.failed.connect(self.on_worker_failed)
        self.worker.overall_progress.connect(self.progress_page.overall_bar.setValue)
        self.worker.object_progress.connect(self.on_object_progress)
        self.worker.category_progress.connect(
            self.progress_page.update_category_progress
        )  # Update status cards
        self.worker.log_message.connect(self.progress_page.append_log)
        self.worker.log_entry.connect(self.progress_page.append_log_entry)  # New structured logging
        self.worker.fatal_error.connect(self.on_fatal_error)  # New fatal error handler
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def on_worker_finished(self) -> None:
        self.progress_page.append_log("Worker signalled completion.")
        self.prev_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.start_button.setEnabled(True)
        self.update_navigation()
        if self.worker:
            self.bulk_output_path = self.worker.bulk_output_path
        self.progress_page.cancel_button.setEnabled(False)
        if self.state.options.get("bulk_user_upload") and self.bulk_output_path:
            self.progress_page.show_bulk_ready(self.bulk_output_path)
            QMessageBox.information(
                self,
                "Bulk User Upload",
                f"Bulk upload CSV is ready at {self.bulk_output_path}.",
            )
        else:
            QMessageBox.information(self, "Migration", "Migration complete.")
            self.progress_page.finish_button.setVisible(True)
            self.progress_page.finish_button.setEnabled(True)
        self.worker = None
        self.thread = None

    def on_worker_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Migration failed", message)
        self.start_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.prev_button.setEnabled(True)
        self.progress_page.cancel_button.setEnabled(False)
        self.progress_page.finish_button.setVisible(True)
        self.progress_page.finish_button.setEnabled(True)
        self.worker = None
        self.thread = None
        self.update_navigation()

    def on_fatal_error(self, error_dict: dict) -> None:
        """Handle fatal error from migration worker.

        Args:
            error_dict: Dictionary with error details (message, details, timestamp)
        """
        from .dialogs import FatalErrorDialog

        # Extract error information
        error_message = error_dict.get("message", "Unknown error occurred")
        error_details = error_dict.get("details")

        # Show the fatal error dialog (only if verbose mode to show details)
        verbose = self.state.options.get("verbose", False)
        if verbose and error_details:
            dialog = FatalErrorDialog(error_message, error_details, parent=self)
            dialog.exec()
        else:
            # Non-verbose mode: just show a simple error message
            QMessageBox.critical(
                self,
                "Migration Failed",
                f"A fatal error occurred:\n\n{error_message}\n\n"
                "Enable verbose mode in Migration Options to see detailed error information.",
            )

        # Re-enable UI controls
        self.start_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.prev_button.setEnabled(True)
        self.progress_page.cancel_button.setEnabled(False)
        self.progress_page.finish_button.setVisible(True)
        self.progress_page.finish_button.setEnabled(True)
        self.worker = None
        self.thread = None
        self.update_navigation()

    def on_object_progress(self, name: str, percent: int) -> None:
        self.progress_page.update_object(name, percent)

    def cancel_migration(self) -> None:
        if self.worker:
            self.worker.request_cancel()
            self.progress_page.append_log("Cancellation requested…")

    def test_connection(
        self,
        role: str,
        provider: str,
        settings: dict[str, Any],
        *,
        interactive: bool = True,
        show_success_prompt: bool = False,
    ) -> bool:
        success, message = self._perform_connection_test(provider, settings)
        if interactive:
            if success:
                QMessageBox.information(self, "Test Connection", message)
            else:
                QMessageBox.critical(self, "Test Connection", message)
        elif success and show_success_prompt:
            QMessageBox.information(self, "Test Connection", message)
        return success

    def _perform_connection_test(self, provider: str, settings: dict[str, Any]) -> tuple[bool, str]:
        try:
            if provider == DEFAULT_SOURCE_PROVIDER:
                domain = settings.get("domain", "").strip()
                token = settings.get("token", "").strip()
                if not domain or not token:
                    return False, f"Domain and API token are required for {provider}."
                from onelogin_migration_core.config import SourceApiSettings
                from onelogin_migration_core.clients import _PROVIDER_REGISTRY
                source_settings = SourceApiSettings(
                    domain=domain,
                    token=token,
                    provider=(self._state.source_provider or "okta").lower() if self._state else "okta",
                )
                provider_slug = source_settings.provider_slug
                client_cls = _PROVIDER_REGISTRY.get(provider_slug)
                if client_cls is None:
                    return False, f"Unsupported source provider: {provider_slug}"
                client = client_cls(source_settings)
                return client.test_connection()
            if provider == DEFAULT_TARGET_PROVIDER:
                client_id = settings.get("client_id", "").strip()
                client_secret = settings.get("client_secret", "").strip()
                region = settings.get("region", "us").strip() or "us"
                if not client_id or not client_secret:
                    return (
                        False,
                        "Client ID and client secret are required for OneLogin.",
                    )
                url = f"https://api.{region}.onelogin.com/auth/oauth2/v2/token"
                response = requests.post(
                    url,
                    json={"grant_type": "client_credentials"},
                    auth=(client_id, client_secret),
                    headers={"Content-Type": "application/json"},
                    timeout=15,
                )
                if response.ok:
                    return True, "Successfully authenticated with OneLogin."
                return (
                    False,
                    f"OneLogin connection failed: {response.status_code} {response.text.strip()[:200]}",
                )
            return False, f"No connection test implemented for {provider}."
        except requests.RequestException as exc:
            return False, f"Network error: {exc}"

    def open_bulk_location(self) -> None:
        path_str = self.progress_page.bulk_path or self.bulk_output_path
        if not path_str:
            QMessageBox.information(self, "Bulk Export", "Bulk CSV file is not available.")
            return
        path = Path(path_str)
        if not path.exists():
            QMessageBox.information(self, "Bulk Export", "Bulk CSV file is not available.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def finish_wizard(self) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.close()

    def load_profile_dialog(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Profile", "", "Profiles (*.json *.yaml *.yml)"
        )
        if file_path:
            self.load_profile(Path(file_path))

    def load_profile(self, path: Path) -> None:
        try:
            if path.suffix.lower() in {".yaml", ".yml"}:
                data = yaml.safe_load(path.read_text())
            else:
                data = json.loads(path.read_text())
        except Exception as exc:  # pragma: no cover - I/O safety
            QMessageBox.critical(self, "Profile", f"Failed to load profile: {exc}")
            return
        state = WizardState.from_dict(data or {})
        state.profile_path = path
        self.state = state
        self.source_settings_page.set_values(state.source_settings)
        self.target_settings_page.set_values(state.target_settings)
        self.options_page.on_enter(state)
        self.objects_page.on_enter(state)
        self.summary_page.on_enter(state)
        self.stack.setCurrentIndex(0)
        self.update_navigation()
        self.state.profile_path = path
        self.config_path = path

    def persist_state(self) -> None:
        if not self.config_path:
            return
        try:
            data = self.state.to_profile_dict(include_credentials=False)
        except ValueError:
            return
        text = yaml.safe_dump(data, sort_keys=False)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(text)
        self.state.profile_path = self.config_path

    def closeEvent(self, event) -> None:  # pragma: no cover - UI hook
        if self.thread and self.thread.isRunning():
            if (
                QMessageBox.question(self, "Exit", "Migration in progress. Cancel and exit?")
                == QMessageBox.Yes
            ):
                self.cancel_migration()
                # Give the worker time to cancel gracefully; avoid forced termination
                self.thread.quit()
                if not self.thread.wait(5000):  # Wait up to 5 seconds
                    QMessageBox.information(
                        self,
                        "Stopping Migration",
                        "Migration is still shutting down. Please wait a moment and try closing again.",
                    )
                    event.ignore()
                    return
            else:
                event.ignore()
                return

        # Clean up any remaining resources
        self._cleanup_resources()
        super().closeEvent(event)

    def _cleanup_resources(self) -> None:
        """Clean up all resources before exit to prevent file corruption."""
        try:
            # Clean up analysis page worker if running
            if hasattr(self, "analysis_page") and hasattr(self.analysis_page, "worker"):
                if self.analysis_page.worker and self.analysis_page.worker.isRunning():
                    # Request cooperative cancellation if available
                    if hasattr(self.analysis_page.worker, "request_cancel"):
                        try:
                            self.analysis_page.worker.request_cancel()
                        except Exception:
                            pass
                    self.analysis_page.worker.quit()
                    self.analysis_page.worker.wait(5000)

            # Clean up migration worker
            if self.worker:
                self.worker.deleteLater()
                self.worker = None

            # Clean up thread
            if self.thread:
                if self.thread.isRunning():
                    # Ask worker to stop cooperatively
                    if self.worker:
                        try:
                            self.worker.request_cancel()
                        except Exception:
                            pass
                    self.thread.quit()
                    self.thread.wait(5000)
                self.thread.deleteLater()
                self.thread = None

            # Save credential manager state
            if hasattr(self, "credential_manager") and self.credential_manager:
                try:
                    self.credential_manager.shutdown()
                except Exception:
                    pass  # Best effort

            # Process any pending Qt events
            if QApplication.instance():
                QApplication.processEvents()

        except Exception as e:
            # Log error but don't prevent closing
            import logging

            logging.error(f"Error during cleanup: {e}")


def run_gui(
    config_path: Path,
    template_path: Path | None = None,
    export_path: Path | None = None,
) -> None:
    if not PYSIDE_AVAILABLE:
        raise RuntimeError(
            "PySide6 is not installed. Install the optional 'gui' extras (pip install okta-to-onelogin[gui])."
        ) from _PYSIDE_IMPORT_ERROR

    ensure_config_file(config_path, template_path)

    # Create or get existing QApplication with error handling
    app = QApplication.instance()
    created = False
    if app is None:
        try:
            if _QT_PLUGIN_PATH and _QT_PLUGIN_PATH.exists():
                # Ensure Qt keeps the wheel's plugin directory even if applicationDirPath differs
                paths = [str(_QT_PLUGIN_PATH)]
                if _QT_PLATFORM_PLUGIN_PATH and str(_QT_PLATFORM_PLUGIN_PATH) not in paths:
                    paths.append(str(_QT_PLATFORM_PLUGIN_PATH))
                QCoreApplication.setLibraryPaths(paths)
            app = QApplication(sys.argv)
            created = True
        except Exception as exc:
            import platform

            system_arch = platform.machine()
            error_msg = str(exc)

            if "cocoa" in error_msg.lower() and system_arch == "arm64":
                raise RuntimeError(
                    "Qt platform plugin 'cocoa' failed to initialize.\n\n"
                    "This usually means PySide6 was installed with x86_64-only binaries on Apple Silicon.\n\n"
                    "Solution:\n"
                    "  pip uninstall -y PySide6 PySide6-Essentials PySide6-Addons shiboken6\n"
                    "  pip install --no-cache-dir --force-reinstall PySide6\n\n"
                    f"Original error: {error_msg}"
                ) from exc
            else:
                raise RuntimeError(
                    f"Failed to initialize Qt application: {error_msg}\n\n"
                    "Try reinstalling PySide6:\n"
                    "  pip install --force-reinstall PySide6"
                ) from exc
    QApplication.setStyle(QStyleFactory.create("Fusion"))

    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MigrationWizardWindow(
        config_path=config_path, template_path=template_path, export_path=export_path
    )
    if not icon.isNull():
        window.setWindowIcon(icon)

    # Set reasonable window size and constraints
    window.resize(800, 850)  # Better starting size
    window.setMinimumSize(
        750, 850
    )  # Don't let it get too small - enough for all form fields, fixed height
    window.setMaximumSize(1000, 850)  # Fixed height, variable width
    window.show()

    if created:
        try:
            app.exec()
        finally:
            # Ensure proper cleanup to prevent file corruption
            try:
                window._cleanup_resources()
            except Exception:
                pass
            # Process remaining events before exit
            app.processEvents()
            # Clean up the window
            window.deleteLater()
            # Final event processing
            app.processEvents()


def run_gui_secure(export_path: Path | None = None) -> None:
    """Launch GUI with secure settings (no YAML config files).

    This is the recommended entry point for bundled applications that uses:
    - JSON file for non-sensitive settings (~/.onelogin-migration/settings.json)
    - System keyring for credentials (never written to disk)
    - No YAML config files with plaintext credentials

    Args:
        export_path: Optional path for export operations.
    """
    if not PYSIDE_AVAILABLE:
        raise RuntimeError(
            "PySide6 is not installed. Install the optional 'gui' extras (pip install okta-to-onelogin[gui])."
        ) from _PYSIDE_IMPORT_ERROR

    # No config file needed - settings are loaded from secure storage
    # For backwards compatibility with existing MigrationWizardWindow,
    # we create a temporary in-memory config path
    import tempfile

    temp_config = Path(tempfile.gettempdir()) / "onelogin_temp_config.yaml"

    # Create or get existing QApplication with error handling
    app = QApplication.instance()
    created = False
    if app is None:
        try:
            if _QT_PLUGIN_PATH and _QT_PLUGIN_PATH.exists():
                paths = [str(_QT_PLUGIN_PATH)]
                if _QT_PLATFORM_PLUGIN_PATH and str(_QT_PLATFORM_PLUGIN_PATH) not in paths:
                    paths.append(str(_QT_PLATFORM_PLUGIN_PATH))
                QCoreApplication.setLibraryPaths(paths)
            app = QApplication(sys.argv)
            created = True
        except Exception as exc:
            import platform

            system_arch = platform.machine()
            error_msg = str(exc)

            if "cocoa" in error_msg.lower() and system_arch == "arm64":
                raise RuntimeError(
                    "Qt platform plugin 'cocoa' failed to initialize.\n\n"
                    "This usually means PySide6 was installed with x86_64-only binaries on Apple Silicon.\n\n"
                    "Solution:\n"
                    "  pip uninstall -y PySide6 PySide6-Essentials PySide6-Addons shiboken6\n"
                    "  pip install --no-cache-dir --force-reinstall PySide6\n\n"
                    f"Original error: {error_msg}"
                ) from exc
            else:
                raise RuntimeError(
                    f"Failed to initialize Qt application: {error_msg}\n\n"
                    "Try reinstalling PySide6:\n"
                    "  pip install --force-reinstall PySide6"
                ) from exc
    QApplication.setStyle(QStyleFactory.create("Fusion"))

    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Use existing wizard but with temp config (credentials from keyring)
    window = MigrationWizardWindow(
        config_path=temp_config, template_path=None, export_path=export_path
    )
    if not icon.isNull():
        window.setWindowIcon(icon)

    # Set reasonable window size and constraints
    window.resize(800, 850)  # Better starting size
    window.setMinimumSize(
        750, 850
    )  # Don't let it get too small - enough for all form fields, fixed height
    window.setMaximumSize(1000, 850)  # Fixed height, variable width
    window.show()

    if created:
        try:
            app.exec()
        finally:
            # Ensure proper cleanup to prevent file corruption
            try:
                window._cleanup_resources()
            except Exception:
                pass
            # Process remaining events before exit
            app.processEvents()
            # Clean up the window
            window.deleteLater()
            # Final event processing
            app.processEvents()
