"""
Tests for SessionKeyManager automatic rotation scheduler.

This module tests the background rotation scheduling system:
- Auto-rotation triggers at the correct time
- Rotation callback is invoked properly
- Graceful shutdown works correctly
- Timer cancellation works
- Exception handling during rotation
- Context manager support
"""

import time
from datetime import timedelta
from unittest import mock

import pytest

# Import from layered_credentials
try:
    from layered_credentials.core import SessionKeyManager
except ImportError:
    # Fallback for tests run before installation
    import sys
    from pathlib import Path

    layered_creds_src = Path(__file__).resolve().parents[2] / "layered_credentials" / "src"
    sys.path.insert(0, str(layered_creds_src))

    from layered_credentials.core import SessionKeyManager


class TestSessionKeyManagerAutoRotation:
    """Test automatic rotation scheduling."""

    def test_auto_rotate_disabled_by_default(self):
        """Test that auto-rotation is disabled by default."""
        manager = SessionKeyManager()

        # Auto-rotation should be disabled
        assert not manager._auto_rotate
        assert manager._rotation_timer is None

        # Clean up
        manager.shutdown()

    def test_auto_rotate_enabled(self):
        """Test that auto-rotation can be enabled."""
        rotation_called = []

        def rotation_callback(mgr):
            rotation_called.append(True)

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            rotation_callback=rotation_callback,
        )

        try:
            # Timer should be scheduled
            assert manager._auto_rotate
            assert manager._rotation_timer is not None
            assert manager._rotation_timer.is_alive()

            # Wait for rotation to trigger
            time.sleep(0.3)

            # Callback should have been called
            assert len(rotation_called) > 0

        finally:
            manager.shutdown()

    def test_rotation_callback_receives_manager(self):
        """Test that rotation callback receives the manager instance."""
        received_manager = []

        def rotation_callback(mgr):
            received_manager.append(mgr)

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            rotation_callback=rotation_callback,
        )

        try:
            # Wait for rotation
            time.sleep(0.3)

            # Callback should have received the manager
            assert len(received_manager) == 1
            assert received_manager[0] is manager

        finally:
            manager.shutdown()

    def test_rotation_without_callback_logs_warning(self, caplog):
        """Test that rotation without callback logs a warning."""
        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            # No callback provided
        )

        try:
            # Wait for rotation
            time.sleep(0.3)

            # Should have logged warning about missing callback
            assert any("without credential store callback" in record.message for record in caplog.records)

        finally:
            manager.shutdown()

    def test_multiple_rotations(self):
        """Test that rotation reschedules for multiple cycles."""
        rotation_count = []
        credential_store = {}

        def rotation_callback(mgr):
            rotation_count.append(True)
            # Actually perform rotation
            mgr.rotate_session_with_reencryption(credential_store)

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            rotation_callback=rotation_callback,
        )

        try:
            # Wait for multiple rotations
            time.sleep(0.5)

            # Should have rotated multiple times
            assert len(rotation_count) >= 2

        finally:
            manager.shutdown()

    def test_rotation_updates_session_id(self):
        """Test that rotation updates session_id and master_key."""
        rotation_sessions = []
        credential_store = {}

        def rotation_callback(mgr):
            rotation_sessions.append(mgr.session_id.hex())
            # Actually perform rotation
            mgr.rotate_session_with_reencryption(credential_store)

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            rotation_callback=rotation_callback,
        )

        original_session = manager.session_id.hex()

        try:
            # Wait for rotation
            time.sleep(0.3)

            # Session ID should have changed
            assert manager.session_id.hex() != original_session
            assert len(rotation_sessions) > 0

        finally:
            manager.shutdown()

    def test_rotation_increments_count(self):
        """Test that rotation increments the rotation counter."""
        credential_store = {}

        def rotation_callback(mgr):
            # Actually perform rotation
            mgr.rotate_session_with_reencryption(credential_store)

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            rotation_callback=rotation_callback,
        )

        initial_count = manager.get_rotation_count()

        try:
            # Wait for rotation
            time.sleep(0.3)

            # Count should have increased
            assert manager.get_rotation_count() > initial_count

        finally:
            manager.shutdown()

    def test_exception_in_callback_is_handled(self, caplog):
        """Test that exceptions in rotation callback are handled gracefully."""

        def failing_callback(mgr):
            raise RuntimeError("Test error in rotation callback")

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            rotation_callback=failing_callback,
        )

        try:
            # Wait for rotation attempt
            time.sleep(0.3)

            # Error should be logged
            assert any("Automatic rotation failed" in record.message for record in caplog.records)

            # Manager should still be alive (not crashed)
            assert manager.session_id is not None

        finally:
            manager.shutdown()

    def test_exception_in_callback_stops_rescheduling(self):
        """Test that exception in callback stops automatic rescheduling."""
        call_count = []

        def failing_callback(mgr):
            call_count.append(True)
            raise RuntimeError("Test error")

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            rotation_callback=failing_callback,
        )

        try:
            # Wait for multiple rotation cycles
            time.sleep(0.5)

            # Callback should only be called once (then stop due to error)
            assert len(call_count) == 1

        finally:
            manager.shutdown()


class TestSessionKeyManagerShutdown:
    """Test graceful shutdown of automatic rotation."""

    def test_shutdown_stops_timer(self):
        """Test that shutdown stops the rotation timer."""

        def rotation_callback(mgr):
            pass

        manager = SessionKeyManager(
            max_age=timedelta(hours=1),  # Long delay
            auto_rotate=True,
            rotation_callback=rotation_callback,
        )

        # Timer should be running
        assert manager._rotation_timer is not None
        assert manager._rotation_timer.is_alive()

        # Shutdown
        manager.shutdown()

        # Timer should be stopped
        time.sleep(0.1)
        assert not manager._rotation_timer.is_alive()

    def test_shutdown_sets_shutdown_event(self):
        """Test that shutdown sets the shutdown event."""
        manager = SessionKeyManager(auto_rotate=False)

        # Event should not be set initially
        assert not manager._shutdown_event.is_set()

        # Shutdown
        manager.shutdown()

        # Event should be set
        assert manager._shutdown_event.is_set()

    def test_shutdown_waits_for_timer(self):
        """Test that shutdown waits for timer to complete."""

        def slow_callback(mgr):
            time.sleep(0.2)

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.05),
            auto_rotate=True,
            rotation_callback=slow_callback,
        )

        # Wait for rotation to start
        time.sleep(0.1)

        # Shutdown with timeout
        start_time = time.time()
        manager.shutdown(timeout=1.0)
        elapsed = time.time() - start_time

        # Should have waited for callback to complete
        assert elapsed >= 0.1

    def test_shutdown_timeout_warning(self, caplog):
        """Test that shutdown logs warning on timeout."""

        def very_slow_callback(mgr):
            time.sleep(10)  # Very slow

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.05),
            auto_rotate=True,
            rotation_callback=very_slow_callback,
        )

        # Wait for rotation to start
        time.sleep(0.1)

        # Shutdown with short timeout
        manager.shutdown(timeout=0.1)

        # Should have logged timeout warning
        assert any("did not stop within" in record.message for record in caplog.records)

    def test_shutdown_can_be_called_multiple_times(self):
        """Test that shutdown is idempotent."""
        manager = SessionKeyManager(auto_rotate=False)

        # Multiple shutdowns should not crash
        manager.shutdown()
        manager.shutdown()
        manager.shutdown()

    def test_shutdown_prevents_rescheduling(self):
        """Test that shutdown prevents rotation rescheduling."""
        call_count = []

        def rotation_callback(mgr):
            call_count.append(True)

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            rotation_callback=rotation_callback,
        )

        # Wait for first rotation
        time.sleep(0.15)
        initial_count = len(call_count)

        # Shutdown
        manager.shutdown()

        # Wait for what would be another rotation cycle
        time.sleep(0.3)

        # Should not have rotated again after shutdown
        assert len(call_count) == initial_count


class TestSessionKeyManagerContextManager:
    """Test context manager support."""

    def test_context_manager_basic(self):
        """Test basic context manager usage."""

        def rotation_callback(mgr):
            pass

        with SessionKeyManager(
            max_age=timedelta(hours=1),
            auto_rotate=True,
            rotation_callback=rotation_callback,
        ) as manager:
            # Manager should be alive
            assert manager.session_id is not None
            assert manager._rotation_timer is not None

        # After exiting context, shutdown should be called
        assert manager._shutdown_event.is_set()
        time.sleep(0.1)
        assert not manager._rotation_timer.is_alive()

    def test_context_manager_with_exception(self):
        """Test that context manager shuts down even with exceptions."""

        def rotation_callback(mgr):
            pass

        try:
            with SessionKeyManager(
                max_age=timedelta(hours=1),
                auto_rotate=True,
                rotation_callback=rotation_callback,
            ) as manager:
                # Raise an exception
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Manager should still be shut down
        assert manager._shutdown_event.is_set()

    def test_context_manager_returns_self(self):
        """Test that context manager __enter__ returns self."""
        manager = SessionKeyManager()

        with manager as returned:
            assert returned is manager

        manager.shutdown()


class TestSessionKeyManagerIntegration:
    """Integration tests with rotation and re-encryption."""

    def test_auto_rotation_with_reencryption(self):
        """Test automatic rotation with credential re-encryption."""
        credential_store = {}
        rotation_results = []

        def rotation_callback(mgr):
            # Simulate re-encryption
            success, failed, errors = mgr.rotate_session_with_reencryption(
                credential_store,
                on_failure="skip",
            )
            rotation_results.append((success, failed, errors))

        manager = SessionKeyManager(
            max_age=timedelta(seconds=0.1),
            auto_rotate=True,
            rotation_callback=rotation_callback,
        )

        try:
            # Wait for rotation
            time.sleep(0.3)

            # Rotation should have been attempted
            assert len(rotation_results) > 0

            # Should have succeeded (even with empty store)
            success, failed, errors = rotation_results[0]
            assert failed == 0
            assert len(errors) == 0

        finally:
            manager.shutdown()

    def test_session_info_includes_auto_rotate_status(self):
        """Test that get_session_info includes auto_rotate status."""
        manager = SessionKeyManager(
            max_age=timedelta(hours=1),
            auto_rotate=True,
        )

        try:
            info = manager.get_session_info()

            # Should include auto_rotate status
            assert "auto_rotate_enabled" in info
            assert info["auto_rotate_enabled"] is True

        finally:
            manager.shutdown()

    def test_manual_rotation_coexists_with_auto_rotation(self):
        """Test that manual rotation works alongside auto-rotation."""
        rotation_count_before = []

        def rotation_callback(mgr):
            pass

        manager = SessionKeyManager(
            max_age=timedelta(hours=1),  # Long interval for auto
            auto_rotate=True,
            rotation_callback=rotation_callback,
        )

        try:
            # Manual rotation
            manager._rotate_session()
            manual_count = manager.get_rotation_count()

            # Should have rotated
            assert manual_count > 0

            # Auto-rotation timer should still be running
            assert manager._rotation_timer is not None
            assert manager._rotation_timer.is_alive()

        finally:
            manager.shutdown()
