"""Comprehensive tests for telemetry CLI commands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from onelogin_migration_cli.telemetry import app

runner = CliRunner()


@pytest.fixture
def mock_db(tmp_path: Path):
    """Create a mock database with telemetry schema."""
    db_path = tmp_path / "test_telemetry.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Create tables
    conn.execute("""
        CREATE TABLE telemetry_settings (
            enabled INTEGER DEFAULT 1,
            user_consent_date TEXT,
            installation_id TEXT,
            anonymized INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE connector_telemetry (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            onelogin_connector_id INTEGER,
            confidence REAL
        )
    """)

    conn.execute("""
        CREATE TABLE error_telemetry (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            error_category TEXT,
            component TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE migration_scenario_telemetry (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            migration_run_id TEXT,
            user_count INTEGER
        )
    """)

    # Create summary views
    conn.execute("""
        CREATE VIEW connector_telemetry_summary AS
        SELECT
            onelogin_connector_id,
            COUNT(*) as decision_count,
            SUM(CASE WHEN confidence > 80 THEN 1 ELSE 0 END) as accepted_count,
            AVG(confidence) as avg_confidence,
            'exact' as match_type
        FROM connector_telemetry
        GROUP BY onelogin_connector_id
    """)

    conn.execute("""
        CREATE VIEW error_pattern_summary AS
        SELECT
            error_category,
            component,
            COUNT(*) as occurrence_count,
            NULL as http_status
        FROM error_telemetry
        GROUP BY error_category, component
    """)

    conn.execute("""
        CREATE VIEW scenario_effectiveness AS
        SELECT
            CASE
                WHEN user_count < 100 THEN '<100'
                WHEN user_count < 1000 THEN '100-1000'
                ELSE '1000+'
            END as user_count_bucket,
            COUNT(*) as scenario_count,
            95.5 as avg_success_rate,
            120.0 as avg_duration_seconds
        FROM migration_scenario_telemetry
        GROUP BY user_count_bucket
    """)

    conn.commit()

    # Create mock database object
    mock_db_obj = Mock()
    mock_db_obj.connect.return_value = conn
    mock_db_obj.db_path = db_path

    return mock_db_obj, conn


class TestTelemetryStatus:
    """Tests for telemetry status command."""

    def test_status_not_configured(self):
        """Test status when telemetry not configured."""
        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_db = Mock()
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_cursor.fetchone.return_value = None
            mock_conn.execute.return_value = mock_cursor
            mock_db.connect.return_value = mock_conn
            mock_get_db.return_value = mock_db

            with patch("onelogin_migration_cli.telemetry.get_telemetry_manager"):
                result = runner.invoke(app, ["status"])

                assert result.exit_code == 0
                assert "not configured" in result.stdout.lower()

    def test_status_enabled(self, mock_db):
        """Test status when telemetry is enabled."""
        db_obj, conn = mock_db

        # Insert settings
        conn.execute("""
            INSERT INTO telemetry_settings (enabled, user_consent_date, installation_id, anonymized)
            VALUES (1, '2025-01-01', 'test-install-123', 1)
        """)

        # Insert some sample data
        conn.execute("INSERT INTO connector_telemetry (timestamp, onelogin_connector_id, confidence) VALUES ('2025-01-15', 123, 95.0)")
        conn.execute("INSERT INTO error_telemetry (timestamp, error_category, component) VALUES ('2025-01-15', 'API', 'OneLogin')")
        conn.execute("INSERT INTO migration_scenario_telemetry (timestamp, migration_run_id, user_count) VALUES ('2025-01-15', 'run-1', 500)")
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            with patch("onelogin_migration_cli.telemetry.get_telemetry_manager"):
                result = runner.invoke(app, ["status"])

                assert result.exit_code == 0
                assert "Enabled" in result.stdout
                assert "test-install-123" in result.stdout
                assert "SHA-256" in result.stdout

    def test_status_disabled(self, mock_db):
        """Test status when telemetry is disabled."""
        db_obj, conn = mock_db

        conn.execute("""
            INSERT INTO telemetry_settings (enabled, user_consent_date, installation_id)
            VALUES (0, '2025-01-01', 'test-install-456')
        """)
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            with patch("onelogin_migration_cli.telemetry.get_telemetry_manager"):
                result = runner.invoke(app, ["status"])

                assert result.exit_code == 0
                assert "Disabled" in result.stdout


class TestTelemetryExport:
    """Tests for telemetry export command."""

    def test_export_summary_only(self, mock_db, tmp_path):
        """Test export with summary statistics only."""
        db_obj, conn = mock_db

        conn.execute("""
            INSERT INTO telemetry_settings (enabled, user_consent_date, installation_id)
            VALUES (1, '2025-01-01', 'test-install-789')
        """)
        conn.execute("INSERT INTO connector_telemetry (timestamp, onelogin_connector_id, confidence) VALUES ('2025-01-15', 100, 90.0)")
        conn.commit()

        output_file = tmp_path / "export.json"

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["export", str(output_file)])

            assert result.exit_code == 0
            assert output_file.exists()

            # Verify export structure
            data = json.loads(output_file.read_text())
            assert "export_timestamp" in data
            assert "settings" in data
            assert "summary" in data
            assert data["raw_data"] is None

    def test_export_with_raw_data(self, mock_db, tmp_path):
        """Test export with raw telemetry data."""
        db_obj, conn = mock_db

        conn.execute("""
            INSERT INTO telemetry_settings (enabled, installation_id)
            VALUES (1, 'test-install-raw')
        """)
        conn.execute("INSERT INTO connector_telemetry (timestamp, onelogin_connector_id, confidence) VALUES ('2025-01-15', 200, 85.0)")
        conn.commit()

        output_file = tmp_path / "export_raw.json"

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["export", str(output_file), "--include-raw"])

            assert result.exit_code == 0
            assert output_file.exists()

            data = json.loads(output_file.read_text())
            assert data["raw_data"] is not None
            assert "connector_telemetry" in data["raw_data"]

    def test_export_no_data(self, mock_db, tmp_path):
        """Test export when no telemetry data exists."""
        db_obj, conn = mock_db

        output_file = tmp_path / "empty_export.json"

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["export", str(output_file)])

            assert result.exit_code == 0
            assert "No telemetry data" in result.stdout


class TestTelemetryDisable:
    """Tests for telemetry disable command."""

    def test_disable_enabled_telemetry(self, mock_db):
        """Test disabling when telemetry is enabled."""
        db_obj, conn = mock_db

        conn.execute("""
            INSERT INTO telemetry_settings (enabled)
            VALUES (1)
        """)
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            # Auto-confirm
            result = runner.invoke(app, ["disable"], input="y\n")

            assert result.exit_code == 0
            assert "disabled" in result.stdout.lower()

            # Verify database was updated
            cursor = conn.execute("SELECT enabled FROM telemetry_settings")
            assert cursor.fetchone()["enabled"] == 0

    def test_disable_already_disabled(self, mock_db):
        """Test disabling when already disabled."""
        db_obj, conn = mock_db

        conn.execute("""
            INSERT INTO telemetry_settings (enabled)
            VALUES (0)
        """)
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["disable"])

            assert result.exit_code == 0
            assert "already disabled" in result.stdout.lower()

    def test_disable_cancelled(self, mock_db):
        """Test cancelling disable operation."""
        db_obj, conn = mock_db

        conn.execute("""
            INSERT INTO telemetry_settings (enabled)
            VALUES (1)
        """)
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["disable"], input="n\n")

            assert result.exit_code == 0
            assert "Cancelled" in result.stdout


class TestTelemetryEnable:
    """Tests for telemetry enable command."""

    def test_enable_disabled_telemetry(self, mock_db):
        """Test enabling when telemetry is disabled."""
        db_obj, conn = mock_db

        conn.execute("""
            INSERT INTO telemetry_settings (enabled)
            VALUES (0)
        """)
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["enable"])

            assert result.exit_code == 0
            assert "enabled" in result.stdout.lower()

            # Verify database was updated
            cursor = conn.execute("SELECT enabled FROM telemetry_settings")
            assert cursor.fetchone()["enabled"] == 1

    def test_enable_already_enabled(self, mock_db):
        """Test enabling when already enabled."""
        db_obj, conn = mock_db

        conn.execute("""
            INSERT INTO telemetry_settings (enabled)
            VALUES (1)
        """)
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["enable"])

            assert result.exit_code == 0
            assert "already enabled" in result.stdout.lower()

    def test_enable_not_configured(self, mock_db):
        """Test enabling when telemetry not configured."""
        db_obj, conn = mock_db

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["enable"])

            assert result.exit_code == 0
            assert "not configured" in result.stdout.lower()


class TestTelemetryClear:
    """Tests for telemetry clear command."""

    def test_clear_with_data(self, mock_db):
        """Test clearing telemetry data."""
        db_obj, conn = mock_db

        # Insert sample data
        conn.execute("INSERT INTO connector_telemetry (timestamp, onelogin_connector_id, confidence) VALUES ('2025-01-15', 100, 90.0)")
        conn.execute("INSERT INTO connector_telemetry (timestamp, onelogin_connector_id, confidence) VALUES ('2025-01-15', 101, 85.0)")
        conn.execute("INSERT INTO error_telemetry (timestamp, error_category, component) VALUES ('2025-01-15', 'API', 'Test')")
        conn.execute("INSERT INTO migration_scenario_telemetry (timestamp, migration_run_id, user_count) VALUES ('2025-01-15', 'run-1', 100)")
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            # Auto-confirm with --yes flag
            result = runner.invoke(app, ["clear", "--yes"])

            assert result.exit_code == 0
            assert "Cleared" in result.stdout

            # Verify data was deleted
            cursor = conn.execute("SELECT COUNT(*) as count FROM connector_telemetry")
            assert cursor.fetchone()["count"] == 0

    def test_clear_no_data(self, mock_db):
        """Test clearing when no data exists."""
        db_obj, conn = mock_db

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["clear", "--yes"])

            assert result.exit_code == 0
            assert "No telemetry data" in result.stdout

    def test_clear_cancelled(self, mock_db):
        """Test cancelling clear operation."""
        db_obj, conn = mock_db

        conn.execute("INSERT INTO connector_telemetry (timestamp, onelogin_connector_id, confidence) VALUES ('2025-01-15', 100, 90.0)")
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["clear"], input="n\n")

            assert result.exit_code == 0
            assert "Cancelled" in result.stdout

            # Verify data was NOT deleted
            cursor = conn.execute("SELECT COUNT(*) as count FROM connector_telemetry")
            assert cursor.fetchone()["count"] == 1


class TestTelemetryViewSummary:
    """Tests for telemetry view-summary command."""

    def test_view_summary_with_data(self, mock_db):
        """Test viewing summary with data."""
        db_obj, conn = mock_db

        # Insert sample data
        conn.execute("INSERT INTO connector_telemetry (timestamp, onelogin_connector_id, confidence) VALUES ('2025-01-15', 100, 95.0)")
        conn.execute("INSERT INTO error_telemetry (timestamp, error_category, component) VALUES ('2025-01-15', 'Network', 'API')")
        conn.execute("INSERT INTO migration_scenario_telemetry (timestamp, migration_run_id, user_count) VALUES ('2025-01-15', 'run-1', 500)")
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["view-summary"])

            assert result.exit_code == 0
            assert "Connector Decision Summary" in result.stdout
            assert "Error Pattern Summary" in result.stdout
            assert "Migration Scenario Effectiveness" in result.stdout

    def test_view_summary_no_data(self, mock_db):
        """Test viewing summary with no data."""
        db_obj, conn = mock_db

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj
            result = runner.invoke(app, ["view-summary"])

            assert result.exit_code == 0
            assert "No connector decisions" in result.stdout or "No errors recorded" in result.stdout


class TestTelemetryIntegration:
    """Integration tests for telemetry command workflows."""

    def test_enable_export_disable_workflow(self, mock_db, tmp_path):
        """Test complete workflow: enable -> export -> disable."""
        db_obj, conn = mock_db

        # Start with disabled telemetry
        conn.execute("""
            INSERT INTO telemetry_settings (enabled, installation_id)
            VALUES (0, 'workflow-test')
        """)
        conn.execute("INSERT INTO connector_telemetry (timestamp, onelogin_connector_id, confidence) VALUES ('2025-01-15', 100, 90.0)")
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj

            # Enable
            result = runner.invoke(app, ["enable"])
            assert result.exit_code == 0
            assert "enabled" in result.stdout.lower()

            # Export
            output_file = tmp_path / "workflow_export.json"
            result = runner.invoke(app, ["export", str(output_file)])
            assert result.exit_code == 0
            assert output_file.exists()

            # Disable
            result = runner.invoke(app, ["disable"], input="y\n")
            assert result.exit_code == 0
            assert "disabled" in result.stdout.lower()

    def test_clear_and_verify_workflow(self, mock_db):
        """Test clearing data and verifying it's gone."""
        db_obj, conn = mock_db

        # Insert data
        conn.execute("INSERT INTO connector_telemetry (timestamp, onelogin_connector_id, confidence) VALUES ('2025-01-15', 100, 90.0)")
        conn.execute("INSERT INTO telemetry_settings (enabled) VALUES (1)")
        conn.commit()

        with patch("onelogin_migration_cli.telemetry.get_default_connector_db") as mock_get_db:
            mock_get_db.return_value = db_obj

            # Clear with confirmation
            result = runner.invoke(app, ["clear", "--yes"])
            assert result.exit_code == 0

            # Verify with status
            result = runner.invoke(app, ["status"])
            assert result.exit_code == 0
            # Should show 0 records
            assert "0" in result.stdout or "Enabled" in result.stdout
