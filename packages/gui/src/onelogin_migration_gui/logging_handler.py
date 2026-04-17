"""Qt logging handler for bridging Python logging to GUI signals."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from PySide6.QtCore import QObject, Signal


class _LogSignals(QObject):
    """Separate QObject to hold signals without naming conflicts."""

    # Signal emitted when a log entry is created
    log_entry = Signal(object)


class LogLevel(Enum):
    """Log severity levels."""

    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    FATAL = logging.CRITICAL

    @classmethod
    def from_levelno(cls, levelno: int) -> LogLevel:
        """Convert logging level number to LogLevel enum."""
        if levelno >= logging.CRITICAL:
            return cls.FATAL
        if levelno >= logging.ERROR:
            return cls.ERROR
        if levelno >= logging.WARNING:
            return cls.WARNING
        if levelno >= logging.INFO:
            return cls.INFO
        return cls.DEBUG

    def to_color(self, theme_manager) -> str:
        """Get theme color for this log level."""
        if self == LogLevel.FATAL:
            return "#ff0000"  # Bright red for fatal
        if self == LogLevel.ERROR:
            return theme_manager.get_color("error")
        if self == LogLevel.WARNING:
            return theme_manager.get_color("warning")
        if self == LogLevel.INFO:
            return theme_manager.get_color("info")
        return theme_manager.get_color("text_secondary")


@dataclass
class LogEntry:
    """Structured log entry with metadata."""

    timestamp: datetime
    level: LogLevel
    category: str  # e.g., "users", "groups", "apps", "custom_attributes", "general"
    message: str
    details: dict[str, Any] | None = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.name,
            "category": self.category,
            "message": self.message,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LogEntry:
        """Create LogEntry from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            level=LogLevel[data["level"]],
            category=data["category"],
            message=data["message"],
            details=data.get("details"),
        )

    def format_display(self) -> str:
        """Format entry for display in UI."""
        time_str = self.timestamp.strftime("%H:%M:%S")
        level_icon = {
            LogLevel.DEBUG: "🔍",
            LogLevel.INFO: "ℹ️",
            LogLevel.WARNING: "⚠️",
            LogLevel.ERROR: "❌",
            LogLevel.FATAL: "🔴",
        }.get(self.level, "•")

        return f"{time_str} [{self.level.name}] {level_icon} {self.message}"


class QtLogHandler(logging.Handler):
    """Logging handler that emits Qt signals for GUI integration.

    Uses composition pattern to avoid naming conflicts between logging.Handler.emit()
    and Qt Signal.emit().
    """

    def __init__(self, verbose: bool = False):
        """
        Initialize the Qt log handler.

        Args:
            verbose: If True, emit individual operation logs. If False, emit summaries.
        """
        logging.Handler.__init__(self)

        # Use composition: separate QObject for signals to avoid emit() naming conflict
        self.signals = _LogSignals()

        self.verbose = verbose
        self._operation_counts: dict[str, dict[str, int]] = {}
        self._in_error_handler = False  # Prevent recursive error handling

    @property
    def log_entry_signal(self):
        """Access to the log entry signal for backward compatibility."""
        return self.signals.log_entry

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record as a Qt signal (Handler.emit implementation).

        Note: This method is required by logging.Handler. We delegate to
        _handle_log_record to avoid any naming conflicts with Qt signals.

        Args:
            record: The logging record to process.
        """
        # Delegate to the actual implementation
        self._handle_log_record(record)

    def _handle_log_record(self, record: logging.LogRecord) -> None:
        """
        Process a log record and emit it as a Qt signal.

        Args:
            record: The logging record to process.
        """
        try:
            # Get the message first
            message = record.getMessage()

            # Determine category from logger name and message
            category = self._extract_category(record.name, message)

            # Determine level
            level = LogLevel.from_levelno(record.levelno)

            # Extract details from record
            details = None
            if hasattr(record, "extra"):
                details = record.extra

            # Create log entry
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created),
                level=level,
                category=category,
                message=message,
                details=details,
            )

            # In non-verbose mode, batch certain types of messages
            if not self.verbose and self._should_batch(entry):
                self._batch_entry(entry)
            else:
                # Emit individual entry via Qt signal
                self.signals.log_entry.emit(entry.to_dict())

        except Exception:
            # Prevent recursive error handling
            if not self._in_error_handler:
                self._in_error_handler = True
                try:
                    self.handleError(record)
                finally:
                    self._in_error_handler = False

    def _extract_category(self, logger_name: str, message: str) -> str:
        """
        Extract migration category from logger name and message.

        Args:
            logger_name: Name of the logger (e.g., "onelogin_migration_core.manager")
            message: The log message content

        Returns:
            Category string (users, groups, apps, custom_attributes, or general)
        """
        # Check message first for category keywords (more specific)
        lower_message = message.lower()

        # Look for "Processing X:" or "Completed X:" patterns from individual operations
        if (
            "processing user" in lower_message
            or "completed user" in lower_message
            or "skipped user" in lower_message
        ):
            return "users"
        if (
            "processing group" in lower_message
            or "completed group" in lower_message
            or "skipped group" in lower_message
        ):
            return "groups"
        if (
            "processing application" in lower_message
            or "completed application" in lower_message
            or "skipped application" in lower_message
        ):
            return "apps"
        if (
            "processing polic" in lower_message
            or "completed polic" in lower_message
            or "skipped polic" in lower_message
        ):
            return "custom_attributes"

        # Also check for other user-related keywords
        if "user" in lower_message and (
            "creat" in lower_message or "migrat" in lower_message or "import" in lower_message
        ):
            return "users"
        if "group" in lower_message and (
            "creat" in lower_message or "migrat" in lower_message or "import" in lower_message
        ):
            return "groups"
        if "app" in lower_message and (
            "creat" in lower_message or "migrat" in lower_message or "import" in lower_message
        ):
            return "apps"
        if ("attribute" in lower_message or "custom" in lower_message) and (
            "creat" in lower_message or "migrat" in lower_message or "provision" in lower_message
        ):
            return "custom_attributes"

        # Fall back to logger name
        lower_name = logger_name.lower()

        if "user" in lower_name:
            return "users"
        if "group" in lower_name:
            return "groups"
        if "app" in lower_name or "application" in lower_name:
            return "apps"
        if "attribute" in lower_name or "custom" in lower_name:
            return "custom_attributes"

        return "general"

    def _should_batch(self, entry: LogEntry) -> bool:
        """
        Determine if this entry should be batched in non-verbose mode.

        Args:
            entry: The log entry to check.

        Returns:
            True if entry should be batched, False otherwise.
        """
        # Always show warnings, errors, and fatal errors individually
        if entry.level in (LogLevel.WARNING, LogLevel.ERROR, LogLevel.FATAL):
            return False

        # Batch INFO and DEBUG messages about routine operations
        if entry.level in (LogLevel.INFO, LogLevel.DEBUG):
            # Look for keywords that indicate routine operations
            message_lower = entry.message.lower()
            batch_keywords = ["created", "updated", "migrated", "imported", "exported"]
            return any(keyword in message_lower for keyword in batch_keywords)

        return False

    def _batch_entry(self, entry: LogEntry) -> None:
        """
        Batch an entry for summary reporting.

        Args:
            entry: The log entry to batch.
        """
        # This is a simplified batching mechanism
        # In a real implementation, you'd periodically emit summaries
        category = entry.category
        if category not in self._operation_counts:
            self._operation_counts[category] = {"success": 0, "skipped": 0, "failed": 0}

        # Increment appropriate counter based on message content
        message_lower = entry.message.lower()
        if "fail" in message_lower or "error" in message_lower:
            self._operation_counts[category]["failed"] += 1
        elif "skip" in message_lower or "already exists" in message_lower:
            self._operation_counts[category]["skipped"] += 1
        else:
            self._operation_counts[category]["success"] += 1

    def flush_batch(self, category: str) -> None:
        """
        Flush batched entries for a category as a summary.

        Args:
            category: The category to flush.
        """
        if category not in self._operation_counts:
            return

        counts = self._operation_counts[category]
        total = sum(counts.values())

        if total == 0:
            return

        # Create summary message
        parts = []
        if counts["success"] > 0:
            parts.append(f"{counts['success']} migrated successfully")
        if counts["skipped"] > 0:
            parts.append(f"{counts['skipped']} skipped (already exist)")
        if counts["failed"] > 0:
            parts.append(f"{counts['failed']} failed")

        message = f"Completed {total} {category}: {', '.join(parts)}"

        summary_entry = LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.INFO,
            category=category,
            message=message,
            details={"counts": counts},
        )

        # Emit summary via Qt signal
        self.signals.log_entry.emit(summary_entry.to_dict())

        # Reset counts
        self._operation_counts[category] = {"success": 0, "skipped": 0, "failed": 0}
