"""Tests for atomic state file writes (Issue #4)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from onelogin_migration_core.manager import _atomic_write


class TestAtomicWrite:
    """Tests for _atomic_write function."""

    def test_atomic_write_success(self, tmp_path):
        """Test successful atomic write."""
        target_file = tmp_path / "test.json"
        content = '{"test": "data", "number": 123}'

        # Perform atomic write
        _atomic_write(target_file, content)

        # Verify file exists and has correct content
        assert target_file.exists()
        assert target_file.read_text() == content

    def test_atomic_write_overwrites_existing(self, tmp_path):
        """Test atomic write overwrites existing file."""
        target_file = tmp_path / "test.json"

        # Write initial content
        target_file.write_text("old content")

        # Atomic write new content
        new_content = "new content"
        _atomic_write(target_file, new_content)

        # Verify new content
        assert target_file.read_text() == new_content

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        """Test atomic write works when parent directory exists."""
        parent = tmp_path / "subdir"
        parent.mkdir()
        target_file = parent / "test.json"

        content = "test content"
        _atomic_write(target_file, content)

        assert target_file.exists()
        assert target_file.read_text() == content

    def test_atomic_write_cleanup_on_error(self, tmp_path):
        """Test temp file is cleaned up on error."""
        target_file = tmp_path / "test.json"

        # Mock os.replace to raise an error
        with patch(
            "onelogin_migration_tool.core.manager.os.replace", side_effect=OSError("Mock error")
        ):
            with pytest.raises(OSError, match="Mock error"):
                _atomic_write(target_file, "test content")

        # Verify no temp files left behind
        temp_files = list(tmp_path.glob("*.tmp.*"))
        assert len(temp_files) == 0, f"Found temp files: {temp_files}"

    def test_atomic_write_temp_file_in_same_dir(self, tmp_path):
        """Test that temp file is created in same directory as target."""
        target_file = tmp_path / "test.json"

        # Track temp file creation
        original_write_text = Path.write_text
        temp_files_created = []

        def track_write_text(self, *args, **kwargs):
            if ".tmp." in self.name:
                temp_files_created.append(self)
            return original_write_text(self, *args, **kwargs)

        with patch.object(Path, "write_text", track_write_text):
            _atomic_write(target_file, "test content")

        # Verify temp file was in same directory
        assert len(temp_files_created) == 1
        assert temp_files_created[0].parent == target_file.parent

    def test_atomic_write_uses_fsync(self, tmp_path):
        """Test that fsync is called to ensure data is on disk."""
        target_file = tmp_path / "test.json"

        # Track fsync calls
        fsync_called = []

        original_fsync = os.fsync

        def track_fsync(fd):
            fsync_called.append(fd)
            return original_fsync(fd)

        with patch("onelogin_migration_tool.core.manager.os.fsync", track_fsync):
            _atomic_write(target_file, "test content")

        # Verify fsync was called
        assert len(fsync_called) == 1

    def test_atomic_write_unique_temp_names(self, tmp_path):
        """Test that concurrent writes use unique temp file names."""
        target_file = tmp_path / "test.json"

        # Track temp file names
        temp_names = []

        original_replace = os.replace

        def track_replace(src, dst):
            if ".tmp." in str(src):
                temp_names.append(Path(src).name)
            return original_replace(src, dst)

        with patch("onelogin_migration_tool.core.manager.os.replace", track_replace):
            # Perform multiple writes
            for i in range(3):
                _atomic_write(target_file, f"content {i}")

        # Verify unique temp names (includes PID and UUID)
        assert len(temp_names) == 3
        assert len(set(temp_names)) == 3  # All unique

    def test_atomic_write_preserves_content_on_failure(self, tmp_path):
        """Test that original file is preserved if write fails."""
        target_file = tmp_path / "test.json"

        # Write initial content
        original_content = "original content"
        target_file.write_text(original_content)

        # Mock os.replace to fail
        with patch(
            "onelogin_migration_tool.core.manager.os.replace", side_effect=OSError("Mock error")
        ):
            with pytest.raises(OSError):
                _atomic_write(target_file, "new content")

        # Verify original content is preserved
        assert target_file.read_text() == original_content


class TestMigrationManagerAtomicWrite:
    """Integration tests for atomic write in MigrationManager."""

    def test_save_state_uses_atomic_write(self, tmp_path):
        """Test that _save_state_locked uses atomic write."""
        from onelogin_migration_core.core.manager import MigrationManager

        from onelogin_migration_core.config import MigrationSettings

        # Create minimal config
        config = MigrationSettings.from_dict(
            {
                "okta": {"domain": "test.okta.com", "token": "test_token"},
                "onelogin": {
                    "client_id": "test_id",
                    "client_secret": "test_secret",
                    "region": "us",
                },
            }
        )

        # Create manager with temp state file
        state_file = tmp_path / "migration_state.json"
        manager = MigrationManager(config, state_file=state_file)

        # Track atomic write calls
        atomic_write_calls = []

        original_atomic_write = _atomic_write

        def track_atomic_write(file_path, content):
            atomic_write_calls.append((file_path, content))
            return original_atomic_write(file_path, content)

        with patch("onelogin_migration_tool.core.manager._atomic_write", track_atomic_write):
            # Trigger state save
            with manager._state_lock:
                manager._save_state_locked()

        # Verify atomic write was called
        assert len(atomic_write_calls) == 1
        assert atomic_write_calls[0][0] == state_file

    def test_state_file_corruption_prevented(self, tmp_path):
        """Test that state file corruption is prevented by atomic write."""
        from onelogin_migration_core.core.manager import MigrationManager

        from onelogin_migration_core.config import MigrationSettings

        config = MigrationSettings.from_dict(
            {
                "okta": {"domain": "test.okta.com", "token": "test_token"},
                "onelogin": {
                    "client_id": "test_id",
                    "client_secret": "test_secret",
                    "region": "us",
                },
            }
        )

        state_file = tmp_path / "migration_state.json"

        # Write initial state
        manager = MigrationManager(config, state_file=state_file)
        with manager._state_lock:
            manager._state["test"] = "initial"
            manager._save_state_locked()

        initial_content = state_file.read_text()

        # Simulate write failure
        call_count = [0]

        original_replace = os.replace

        def fail_on_second_call(src, dst):
            call_count[0] += 1
            if call_count[0] == 2:
                raise OSError("Simulated failure")
            return original_replace(src, dst)

        with patch("onelogin_migration_tool.core.manager.os.replace", fail_on_second_call):
            manager._state["test"] = "modified"
            try:
                with manager._state_lock:
                    manager._save_state_locked()
            except OSError:
                pass  # Expected

        # Verify original state is preserved (not corrupted)
        assert state_file.exists()
        assert state_file.read_text() == initial_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
