"""Comprehensive tests for state_manager module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from onelogin_migration_core.state_manager import StateManager


class TestStateManagerInitialization:
    """Tests for StateManager initialization."""

    def test_init_creates_manager(self, tmp_path: Path) -> None:
        """Test StateManager initialization."""
        state_file = tmp_path / "migration_state.json"
        manager = StateManager(state_file)

        assert manager._state_file == state_file
        assert manager._state_loaded is False
        assert manager._state == {}
        assert manager._completed_ids == {}


class TestStateManagerLoadState:
    """Tests for load_state method."""

    def test_load_state_from_empty_file(self, tmp_path: Path) -> None:
        """Test loading state when file doesn't exist."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        manager.load_state()

        assert manager._state_loaded is True
        assert manager._state == {}
        assert manager._completed_ids == {}

    def test_load_state_from_existing_file(self, tmp_path: Path) -> None:
        """Test loading state from existing file."""
        state_file = tmp_path / "state.json"
        state_data = {
            "completed": {
                "users": ["user1", "user2"],
                "groups": ["group1"],
            },
            "lookups": {
                "users": {"okta_user1": 101, "okta_user2": 102},
                "groups": {"okta_group1": 201},
            },
            "export_path": "/tmp/export.json",
        }
        state_file.write_text(json.dumps(state_data))

        manager = StateManager(state_file)
        manager.load_state()

        assert manager._state_loaded is True
        assert "user1" in manager._completed_ids["users"]
        assert "user2" in manager._completed_ids["users"]
        assert "group1" in manager._completed_ids["groups"]
        assert manager._lookup_state["users"]["okta_user1"] == 101
        assert manager._lookup_state["groups"]["okta_group1"] == 201

    def test_load_state_handles_invalid_json(self, tmp_path: Path) -> None:
        """Test loading state with invalid JSON."""
        state_file = tmp_path / "state.json"
        state_file.write_text("{invalid json")

        manager = StateManager(state_file)
        manager.load_state()

        # Should recover gracefully
        assert manager._state_loaded is True
        assert manager._state == {}

    def test_load_state_only_once(self, tmp_path: Path) -> None:
        """Test that state is only loaded once."""
        state_file = tmp_path / "state.json"
        state_data = {"completed": {"users": ["user1"]}}
        state_file.write_text(json.dumps(state_data))

        manager = StateManager(state_file)
        manager.load_state()

        # Modify file
        state_file.write_text(json.dumps({"completed": {"users": ["user2"]}}))

        # Load again - should not reload
        manager.load_state()

        # Should still have original data
        assert "user1" in manager._completed_ids["users"]
        assert "user2" not in manager._completed_ids.get("users", set())

    def test_load_state_with_null_values(self, tmp_path: Path) -> None:
        """Test loading state with null values."""
        state_file = tmp_path / "state.json"
        state_data = {
            "completed": {
                "users": ["user1", None, "user2"],
            }
        }
        state_file.write_text(json.dumps(state_data))

        manager = StateManager(state_file)
        manager.load_state()

        # Null values should be filtered out
        assert manager._completed_ids["users"] == {"user1", "user2"}


class TestStateManagerSaveState:
    """Tests for save_state_locked method."""

    def test_save_state_creates_file(self, tmp_path: Path) -> None:
        """Test that save_state creates the state file."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        manager._completed_ids = {"users": {"user1"}}
        manager.save_state_locked()

        assert state_file.exists()
        saved_data = json.loads(state_file.read_text())
        assert "user1" in saved_data["completed"]["users"]

    def test_save_state_creates_parent_directory(self, tmp_path: Path) -> None:
        """Test that save_state creates parent directories."""
        state_file = tmp_path / "nested" / "dir" / "state.json"
        manager = StateManager(state_file)

        manager._completed_ids = {"users": {"user1"}}
        manager.save_state_locked()

        assert state_file.exists()
        assert state_file.parent.exists()

    def test_save_state_preserves_lookups(self, tmp_path: Path) -> None:
        """Test that save_state preserves lookup mappings."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        manager._lookup_state = {
            "users": {"okta_user1": 101},
            "groups": {"okta_group1": 201},
        }
        manager.save_state_locked()

        saved_data = json.loads(state_file.read_text())
        assert saved_data["lookups"]["users"]["okta_user1"] == 101
        assert saved_data["lookups"]["groups"]["okta_group1"] == 201


class TestStateManagerResetCompletionState:
    """Tests for reset_completion_state method."""

    def test_reset_clears_completed(self, tmp_path: Path) -> None:
        """Test that reset clears completion tracking."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager._completed_ids = {"users": {"user1", "user2"}}
        manager._lookup_state = {"users": {"okta1": 101}}
        manager._state["export_path"] = "/tmp/export.json"
        manager.save_state_locked()

        manager.reset_completion_state()

        assert manager._completed_ids == {}
        assert manager._lookup_state == {"groups": {}, "users": {}}
        assert manager._state.get("export_path") == "/tmp/export.json"


class TestStateManagerClearState:
    """Tests for clear_state method."""

    def test_clear_state_removes_file(self, tmp_path: Path) -> None:
        """Test that clear_state removes the state file."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager._completed_ids = {"users": {"user1"}}
        manager.save_state_locked()

        assert state_file.exists()

        manager.clear_state()

        assert not state_file.exists()
        assert manager._state == {}
        assert manager._completed_ids == {}
        assert manager._state_loaded is False

    def test_clear_state_handles_missing_file(self, tmp_path: Path) -> None:
        """Test that clear_state doesn't fail if file doesn't exist."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        # Should not raise
        manager.clear_state()

        assert manager._state == {}


class TestStateManagerExportPath:
    """Tests for export path management."""

    def test_record_export_path(self, tmp_path: Path) -> None:
        """Test recording export path."""
        state_file = tmp_path / "state.json"
        export_path = tmp_path / "export.json"
        manager = StateManager(state_file)

        manager.record_export_path(export_path)

        saved_data = json.loads(state_file.read_text())
        assert saved_data["export_path"] == str(export_path)

    def test_get_export_path(self, tmp_path: Path) -> None:
        """Test retrieving export path."""
        state_file = tmp_path / "state.json"
        export_path = tmp_path / "export.json"
        manager = StateManager(state_file)

        manager.record_export_path(export_path)
        retrieved = manager.get_export_path()

        assert retrieved == export_path

    def test_get_export_path_none(self, tmp_path: Path) -> None:
        """Test getting export path when none is set."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        result = manager.get_export_path()

        assert result is None


class TestStateManagerCompletionTracking:
    """Tests for completion tracking methods."""

    def test_is_completed_false_by_default(self, tmp_path: Path) -> None:
        """Test that items are not completed by default."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        assert manager.is_completed("users", "user1") is False

    def test_mark_completed_and_check(self, tmp_path: Path) -> None:
        """Test marking item as completed and checking."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.mark_completed("users", "user1")

        assert manager.is_completed("users", "user1") is True
        assert state_file.exists()

    def test_mark_completed_none_identifier(self, tmp_path: Path) -> None:
        """Test that marking None identifier does nothing."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.mark_completed("users", None)

        assert not state_file.exists()

    def test_mark_completed_idempotent(self, tmp_path: Path) -> None:
        """Test that marking completed is idempotent."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.mark_completed("users", "user1")
        first_mtime = state_file.stat().st_mtime

        # Mark again
        manager.mark_completed("users", "user1")
        second_mtime = state_file.stat().st_mtime

        # Should not save again (file times should be same or very close)
        assert abs(second_mtime - first_mtime) < 0.1


class TestStateManagerLookupTracking:
    """Tests for lookup ID tracking methods."""

    def test_update_lookup_users(self, tmp_path: Path) -> None:
        """Test updating user ID lookup."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.update_lookup("users", "okta_user1", 101)

        lookups = manager.get_lookup_ids("users")
        assert lookups["okta_user1"] == 101

    def test_update_lookup_groups(self, tmp_path: Path) -> None:
        """Test updating group ID lookup."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.update_lookup("groups", "okta_group1", 201)

        lookups = manager.get_lookup_ids("groups")
        assert lookups["okta_group1"] == 201

    def test_update_lookup_ignores_invalid_category(self, tmp_path: Path) -> None:
        """Test that invalid categories are ignored."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.update_lookup("invalid", "id1", 999)

        # Should not create file
        assert not state_file.exists()

    def test_update_lookup_ignores_none_values(self, tmp_path: Path) -> None:
        """Test that None values are ignored."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.update_lookup("users", None, 101)
        manager.update_lookup("users", "okta1", None)

        assert not state_file.exists()

    def test_update_lookup_idempotent(self, tmp_path: Path) -> None:
        """Test that updating with same value is idempotent."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.update_lookup("users", "okta1", 101)
        first_mtime = state_file.stat().st_mtime

        # Update with same value
        manager.update_lookup("users", "okta1", 101)
        second_mtime = state_file.stat().st_mtime

        # Should not save again
        assert abs(second_mtime - first_mtime) < 0.1

    def test_get_lookup_ids_empty(self, tmp_path: Path) -> None:
        """Test getting lookup IDs when none exist."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        lookups = manager.get_lookup_ids("users")

        assert lookups == {}


class TestStateManagerMembershipTracking:
    """Tests for membership tracking methods."""

    def test_mark_membership(self, tmp_path: Path) -> None:
        """Test marking membership as completed."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.mark_membership("group1:user1")

        memberships = manager.get_completed_memberships()
        assert "group1:user1" in memberships

    def test_get_completed_memberships_empty(self, tmp_path: Path) -> None:
        """Test getting memberships when none exist."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        memberships = manager.get_completed_memberships()

        assert memberships == set()

    def test_multiple_memberships(self, tmp_path: Path) -> None:
        """Test tracking multiple memberships."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        manager.mark_membership("g1:u1")
        manager.mark_membership("g1:u2")
        manager.mark_membership("g2:u1")

        memberships = manager.get_completed_memberships()
        assert len(memberships) == 3
        assert "g1:u1" in memberships
        assert "g1:u2" in memberships
        assert "g2:u1" in memberships


class TestStateManagerThreadSafety:
    """Tests for thread-safe operations."""

    def test_concurrent_mark_completed(self, tmp_path: Path) -> None:
        """Test that concurrent mark_completed calls are thread-safe."""
        import threading

        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)
        manager.load_state()

        def mark_items(prefix: str) -> None:
            for i in range(10):
                manager.mark_completed("users", f"{prefix}_user{i}")

        threads = [
            threading.Thread(target=mark_items, args=(f"thread{i}",))
            for i in range(5)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # All items should be marked
        for i in range(5):
            for j in range(10):
                assert manager.is_completed("users", f"thread{i}_user{j}")


class TestStateManagerPersistence:
    """Tests for state persistence across instances."""

    def test_state_persists_across_instances(self, tmp_path: Path) -> None:
        """Test that state persists when creating new manager instance."""
        state_file = tmp_path / "state.json"

        # First instance
        manager1 = StateManager(state_file)
        manager1.load_state()
        manager1.mark_completed("users", "user1")
        manager1.update_lookup("users", "okta1", 101)

        # Second instance
        manager2 = StateManager(state_file)
        manager2.load_state()

        assert manager2.is_completed("users", "user1")
        assert manager2.get_lookup_ids("users")["okta1"] == 101
