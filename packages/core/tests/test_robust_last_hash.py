"""Tests for robust last audit hash reading.

Tests edge cases:
- Incomplete lines (interrupted writes)
- UTF-8 decoding errors
- Corrupted JSON entries
- Very long lines
- Empty/whitespace-only files
"""

import json
import tempfile
from pathlib import Path

from onelogin_migration_core.credentials import TamperEvidentAuditLogger


class TestRobustLastHashReading:
    """Test robust last hash reading implementation."""

    def test_normal_operation(self):
        """Test that normal log reading still works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Log some events
            logger.log_store("service1", "key1", True)
            logger.log_store("service2", "key2", True)

            # Create new logger - should load last hash correctly
            logger2 = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have loaded the hash from last entry
            assert logger2._prev_hash != ""

            # Log another event - should chain correctly
            logger2.log_retrieve("service1", "key1", True)

            # Verify log integrity
            is_valid, errors = logger2.verify_log()
            assert is_valid
            assert len(errors) == 0

    def test_incomplete_last_line(self):
        """Test handling of incomplete last line (interrupted write)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Log an event
            logger.log_store("service1", "key1", True)

            # Append incomplete JSON to file (simulating interrupted write)
            with open(audit_file, "a") as f:
                f.write('{"event": {"event_type": "credenti')  # Incomplete

            # Create new logger - should skip incomplete line and use previous hash
            logger2 = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have loaded hash from the complete entry, not the incomplete one
            # The prev_hash should be from the first (complete) entry
            assert logger2._prev_hash != ""

    def test_corrupted_json_in_last_lines(self):
        """Test handling of corrupted JSON in last few lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Log valid events
            logger.log_store("service1", "key1", True)
            logger.log_store("service2", "key2", True)

            # Append corrupted lines
            with open(audit_file, "a") as f:
                f.write("invalid json line\n")
                f.write('{"malformed": json}\n')
                f.write('{"missing": "current_hash"}\n')

            # Create new logger - should find last valid entry
            logger2 = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have hash from last valid entry (service2)
            assert logger2._prev_hash != ""

            # Log new event - should work
            logger2.log_delete("service1", "key1", True)

    def test_empty_file(self):
        """Test handling of empty audit log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Create empty file
            audit_file.touch()

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have empty prev_hash
            assert logger._prev_hash == ""

            # Should be able to log event
            logger.log_store("service1", "key1", True)

    def test_whitespace_only_file(self):
        """Test handling of file with only whitespace/newlines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Create file with only whitespace
            with open(audit_file, "w") as f:
                f.write("\n\n   \n\t\n\n")

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have empty prev_hash
            assert logger._prev_hash == ""

            # Should be able to log event
            logger.log_store("service1", "key1", True)

    def test_very_long_last_line(self):
        """Test handling of very long last line (requires buffer expansion)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Log event with very large metadata (forces long line)
            large_metadata = {"data": "x" * 10000}  # 10KB of data
            event = {
                "timestamp": "2024-01-01T00:00:00",
                "event_type": "test_event",
                "metadata": large_metadata,
            }

            # Write entry manually with large data
            logger._write_event(event)

            # Create new logger - should handle long line
            logger2 = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have loaded hash
            assert logger2._prev_hash != ""

    def test_utf8_decoding_error_recovery(self):
        """Test recovery from UTF-8 decoding errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Log valid event
            logger.log_store("service1", "key1", True)

            # Append invalid UTF-8 bytes (simulating corruption)
            with open(audit_file, "ab") as f:
                f.write(b"\n\xff\xfe invalid utf8 \n")

            # Create new logger - should handle UTF-8 error
            logger2 = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have loaded hash from valid entry before corruption
            # (or empty if corruption makes the file unreadable)
            # The key is it shouldn't crash
            assert isinstance(logger2._prev_hash, str)

    def test_multiple_corrupted_lines_at_end(self):
        """Test handling multiple corrupted lines at end of file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Log valid events
            logger.log_store("service1", "key1", True)
            logger.log_store("service2", "key2", True)
            logger.log_store("service3", "key3", True)

            # Append multiple corrupted lines
            with open(audit_file, "a") as f:
                for i in range(5):
                    f.write(f"corrupted line {i}\n")

            # Create new logger - should find last valid entry
            logger2 = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have hash from last valid entry
            assert logger2._prev_hash != ""

            # Logging should still work
            logger2.log_delete("service1", "key1", True)

    def test_buffer_expansion_for_long_line(self):
        """Test that buffer expands correctly for lines longer than initial buffer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Create a line that's longer than 4KB (initial buffer size)
            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Create event with 8KB of data (exceeds initial 4KB buffer)
            large_data = "x" * 8192
            event = {
                "timestamp": "2024-01-01T00:00:00",
                "event_type": "large_event",
                "data": large_data,
            }

            logger._write_event(event)

            # Create new logger - should expand buffer and read successfully
            logger2 = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have loaded hash from large entry
            assert logger2._prev_hash != ""

            # Should be able to log new event
            logger2.log_store("service1", "key1", True)

    def test_nonexistent_file(self):
        """Test handling of nonexistent log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "nonexistent.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have empty prev_hash
            assert logger._prev_hash == ""

            # Should be able to create file and log
            logger.log_store("service1", "key1", True)

            # File should now exist
            assert audit_file.exists()

    def test_mixed_valid_and_invalid_entries(self):
        """Test file with mix of valid and invalid entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Log valid event
            logger.log_store("service1", "key1", True)

            # Manually write mixed content
            with open(audit_file, "a") as f:
                f.write("invalid line 1\n")

                # Write another valid entry manually
                valid_entry = {
                    "event": {"event_type": "test", "timestamp": "2024-01-01"},
                    "prev_hash": logger._prev_hash,
                    "current_hash": "abcdef123456",
                }
                f.write(json.dumps(valid_entry) + "\n")

                f.write("invalid line 2\n")
                f.write('{"incomplete": \n')

            # Create new logger - should find last valid entry
            logger2 = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            # Should have hash from the manually written valid entry
            assert logger2._prev_hash == "abcdef123456"
