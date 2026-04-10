"""State persistence for migration operations."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class StateManager:
    """Manages persistent migration state."""

    def __init__(self, state_file: Path) -> None:
        """Initialize state manager.

        Args:
            state_file: Path to the state file
        """
        self._state_file = state_file
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = {}
        self._completed_ids: dict[str, set[str]] = {}
        self._lookup_state: dict[str, dict[str, int]] = {"groups": {}, "users": {}}
        self._state_loaded = False

    def load_state(self) -> None:
        """Load persisted migration state from disk if present."""
        with self._state_lock:
            if self._state_loaded:
                return
            state: dict[str, Any] = {}
            if self._state_file.exists():
                try:
                    state = json.loads(self._state_file.read_text())
                except json.JSONDecodeError:
                    LOGGER.warning("State file %s is not valid JSON; ignoring", self._state_file)
                    state = {}
            self._state = state if isinstance(state, dict) else {}
            completed_raw = self._state.get("completed", {})
            completed: dict[str, set[str]] = {}
            if isinstance(completed_raw, dict):
                for category, values in completed_raw.items():
                    if isinstance(values, list):
                        completed[category] = {str(value) for value in values if value is not None}
            self._completed_ids = completed
            lookup_raw = self._state.get("lookups", {})
            lookups: dict[str, dict[str, int]] = {"groups": {}, "users": {}}
            if isinstance(lookup_raw, dict):
                for category in ("groups", "users"):
                    bucket = lookup_raw.get(category)
                    if isinstance(bucket, dict):
                        lookups[category] = {
                            str(key): int(value)
                            for key, value in bucket.items()
                            if value is not None
                        }
            self._lookup_state = lookups
            self._state_loaded = True

    def save_state_locked(self) -> None:
        """Save state to disk (must be called with lock held)."""
        data = dict(self._state)
        completed = {
            key: sorted(self._completed_ids.get(key, set())) for key in self._completed_ids
        }
        data["completed"] = completed
        lookups = {
            key: {k: int(v) for k, v in bucket.items()}
            for key, bucket in self._lookup_state.items()
        }
        data["lookups"] = lookups
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(data, indent=2, sort_keys=True))

    def reset_completion_state(self) -> None:
        """Reset completion tracking (keeps other state like export path)."""
        with self._state_lock:
            self._completed_ids = {}
            self._lookup_state = {"groups": {}, "users": {}}
            self._state.pop("completed", None)
            self._state.pop("lookups", None)
            self.save_state_locked()

    def clear_state(self) -> None:
        """Clear all state and delete state file."""
        with self._state_lock:
            self._state = {}
            self._completed_ids = {}
            self._lookup_state = {"groups": {}, "users": {}}
            self._state_loaded = False
            try:
                self._state_file.unlink()
            except FileNotFoundError:
                pass

    def record_export_path(self, export_path: Path) -> None:
        """Record the path to the most recent export."""
        with self._state_lock:
            self._state["export_path"] = str(export_path)
            self.save_state_locked()

    def get_export_path(self) -> Path | None:
        """Get the path to the most recent export."""
        self.load_state()
        raw = self._state.get("export_path")
        return Path(raw) if isinstance(raw, str) else None

    def is_completed(self, category: str, identifier: str | None) -> bool:
        """Check if an item has been completed."""
        if identifier is None:
            return False
        self.load_state()
        with self._state_lock:
            completed = self._completed_ids.setdefault(category, set())
            return identifier in completed

    def mark_completed(self, category: str, identifier: str | None) -> None:
        """Mark an item as completed."""
        if identifier is None:
            return
        with self._state_lock:
            bucket = self._completed_ids.setdefault(category, set())
            if identifier in bucket:
                return
            bucket.add(identifier)
            self.save_state_locked()

    def update_lookup(
        self, category: str, source_id: str | None, target_id: int | None
    ) -> None:
        """Update the ID mapping for groups or users."""
        if source_id is None or target_id is None:
            return
        if category not in {"groups", "users"}:
            return
        with self._state_lock:
            bucket = self._lookup_state.setdefault(category, {})
            if bucket.get(source_id) == int(target_id):
                return
            bucket[source_id] = int(target_id)
            self.save_state_locked()

    def get_lookup_ids(self, category: str) -> dict[str, int]:
        """Get all ID mappings for a category."""
        self.load_state()
        return dict(self._lookup_state.get(category, {}))

    def get_completed_memberships(self) -> set[str]:
        """Get all completed membership identifiers."""
        self.load_state()
        with self._state_lock:
            return set(self._completed_ids.get("memberships", set()))

    def mark_membership(self, membership_id: str) -> None:
        """Mark a membership as completed."""
        self.mark_completed("memberships", membership_id)


__all__ = ["StateManager"]
