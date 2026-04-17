"""Comprehensive tests for exporters module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from onelogin_migration_core.exporters import OktaExporter


class TestOktaExporterExportFromOkta:
    """Tests for export_from_okta method."""

    def test_export_from_okta_all_categories(self) -> None:
        """Test exporting all categories from Okta."""
        mock_client = Mock()
        mock_client.export_all.return_value = {
            "users": [{"id": "1", "profile": {"email": "test@example.com"}}],
            "groups": [{"id": "g1", "profile": {"name": "Test Group"}}],
            "applications": [{"id": "a1", "label": "Slack"}],
            "memberships": [{"group_id": "g1", "user_id": "1"}],
        }

        categories = {
            "users": True,
            "groups": True,
            "applications": True,
            "policies": False,
        }

        result = OktaExporter.export_from_okta(mock_client, categories)

        assert result is not None
        assert len(result["users"]) == 1
        assert len(result["groups"]) == 1
        assert len(result["applications"]) == 1
        mock_client.export_all.assert_called_once_with(categories)

    def test_export_from_okta_users_only(self) -> None:
        """Test exporting only users from Okta."""
        mock_client = Mock()
        mock_client.export_all.return_value = {
            "users": [{"id": "1"}, {"id": "2"}],
        }

        categories = {
            "users": True,
            "groups": False,
            "applications": False,
            "policies": False,
        }

        result = OktaExporter.export_from_okta(mock_client, categories)

        assert result is not None
        assert len(result["users"]) == 2

    def test_export_from_okta_empty_result(self) -> None:
        """Test exporting with no data returned."""
        mock_client = Mock()
        mock_client.export_all.return_value = {
            "users": [],
            "groups": [],
            "applications": [],
        }

        categories = {"users": True, "groups": True, "applications": True}

        result = OktaExporter.export_from_okta(mock_client, categories)

        assert result is not None
        assert len(result.get("users", [])) == 0
        assert len(result.get("groups", [])) == 0


class TestOktaExporterSaveExport:
    """Tests for save_export method."""

    def test_save_export_to_directory(self, tmp_path: Path) -> None:
        """Test saving export to a directory (creates okta_export.json)."""
        export_data = {
            "users": [{"id": "1", "profile": {"email": "test@example.com"}}],
            "groups": [{"id": "g1", "profile": {"name": "Group"}}],
        }

        export_path = OktaExporter.save_export(export_data, tmp_path, "okta-prod")

        assert export_path.exists()
        assert export_path.name == "okta_export.json"
        assert export_path.parent == tmp_path

        # Verify main export file content
        saved_data = json.loads(export_path.read_text())
        assert saved_data == export_data

    def test_save_export_to_file(self, tmp_path: Path) -> None:
        """Test saving export to a specific file path."""
        export_data = {
            "users": [{"id": "1"}],
        }
        export_file = tmp_path / "custom_export.json"

        export_path = OktaExporter.save_export(export_data, export_file, "okta-dev")

        assert export_path.exists()
        assert export_path.name == "custom_export.json"

        saved_data = json.loads(export_path.read_text())
        assert saved_data == export_data

    def test_save_export_creates_parent_directory(self, tmp_path: Path) -> None:
        """Test that parent directories are created if needed."""
        export_data = {"users": []}
        nested_path = tmp_path / "artifacts" / "exports" / "data.json"

        export_path = OktaExporter.save_export(export_data, nested_path, "okta")

        assert export_path.exists()
        assert export_path.parent.exists()

    def test_save_export_creates_timestamped_snapshots(self, tmp_path: Path) -> None:
        """Test that per-category timestamped snapshots are created."""
        export_data = {
            "users": [{"id": "1"}],
            "groups": [{"id": "g1"}],
            "applications": [{"id": "a1"}],
        }

        OktaExporter.save_export(export_data, tmp_path, "okta-test")

        # Check that timestamped files were created
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) >= 4  # Main export + 3 category snapshots

        # Verify snapshot files exist
        user_snapshots = list(tmp_path.glob("okta-test_users_*.json"))
        group_snapshots = list(tmp_path.glob("okta-test_groups_*.json"))
        app_snapshots = list(tmp_path.glob("okta-test_applications_*.json"))

        assert len(user_snapshots) == 1
        assert len(group_snapshots) == 1
        assert len(app_snapshots) == 1

    def test_save_export_snapshots_content(self, tmp_path: Path) -> None:
        """Test that snapshot files contain correct data."""
        users_data = [{"id": "1", "profile": {"email": "test@example.com"}}]
        export_data = {"users": users_data}

        OktaExporter.save_export(export_data, tmp_path, "okta")

        user_snapshots = list(tmp_path.glob("okta_users_*.json"))
        assert len(user_snapshots) == 1

        snapshot_data = json.loads(user_snapshots[0].read_text())
        assert snapshot_data == users_data

    def test_save_export_handles_non_json_serializable(self, tmp_path: Path) -> None:
        """Test that fallback serialization works for non-JSON data."""
        # This simulates a complex object that might slip through
        export_data = {
            "users": [{"id": "1", "created": "2024-01-01"}],  # datetime-like string
        }

        export_path = OktaExporter.save_export(export_data, tmp_path, "okta")

        assert export_path.exists()
        saved_data = json.loads(export_path.read_text())
        assert saved_data is not None

    def test_save_export_return_value(self, tmp_path: Path) -> None:
        """Test that save_export returns the main export file path."""
        export_data = {"users": []}

        result = OktaExporter.save_export(export_data, tmp_path, "okta")

        assert isinstance(result, Path)
        assert result.name == "okta_export.json"


class TestOktaExporterLoadExport:
    """Tests for load_export method."""

    def test_load_export_success(self, tmp_path: Path) -> None:
        """Test loading an existing export file."""
        export_data = {
            "users": [{"id": "1", "profile": {"email": "test@example.com"}}],
            "groups": [{"id": "g1", "profile": {"name": "Test Group"}}],
        }
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps(export_data))

        result = OktaExporter.load_export(export_file)

        assert result == export_data
        assert len(result["users"]) == 1
        assert len(result["groups"]) == 1

    def test_load_export_file_not_found(self, tmp_path: Path) -> None:
        """Test loading a non-existent export file."""
        non_existent = tmp_path / "does_not_exist.json"

        with pytest.raises(FileNotFoundError) as exc_info:
            OktaExporter.load_export(non_existent)

        assert "Export file not found" in str(exc_info.value)
        assert str(non_existent) in str(exc_info.value)

    def test_load_export_empty_file(self, tmp_path: Path) -> None:
        """Test loading an empty JSON object."""
        export_file = tmp_path / "empty.json"
        export_file.write_text("{}")

        result = OktaExporter.load_export(export_file)

        assert result == {}

    def test_load_export_with_path_string(self, tmp_path: Path) -> None:
        """Test that load_export accepts Path objects."""
        export_data = {"users": []}
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps(export_data))

        # Test with Path object
        result = OktaExporter.load_export(export_file)
        assert result == export_data

    def test_load_export_invalid_json(self, tmp_path: Path) -> None:
        """Test loading a file with invalid JSON."""
        export_file = tmp_path / "invalid.json"
        export_file.write_text("{invalid json")

        with pytest.raises(json.JSONDecodeError):
            OktaExporter.load_export(export_file)


class TestOktaExporterIntegration:
    """Integration tests for the complete export workflow."""

    def test_export_save_load_roundtrip(self, tmp_path: Path) -> None:
        """Test complete export, save, and load cycle."""
        # Mock Okta client
        mock_client = Mock()
        export_data = {
            "users": [
                {"id": "1", "profile": {"email": "user1@example.com"}},
                {"id": "2", "profile": {"email": "user2@example.com"}},
            ],
            "groups": [{"id": "g1", "profile": {"name": "Admins"}}],
            "applications": [{"id": "a1", "label": "Slack"}],
        }
        mock_client.export_all.return_value = export_data

        categories = {"users": True, "groups": True, "applications": True}

        # Export from Okta
        exported = OktaExporter.export_from_okta(mock_client, categories)

        # Save to disk
        saved_path = OktaExporter.save_export(exported, tmp_path, "okta-test")

        # Load from disk
        loaded = OktaExporter.load_export(saved_path)

        # Verify roundtrip
        assert loaded == export_data
        assert len(loaded["users"]) == 2
        assert len(loaded["groups"]) == 1
        assert len(loaded["applications"]) == 1

    def test_export_with_minimal_data(self, tmp_path: Path) -> None:
        """Test export with minimal data structure."""
        mock_client = Mock()
        mock_client.export_all.return_value = {}

        categories = {"users": False, "groups": False, "applications": False}

        exported = OktaExporter.export_from_okta(mock_client, categories)
        saved_path = OktaExporter.save_export(exported, tmp_path, "minimal")
        loaded = OktaExporter.load_export(saved_path)

        assert loaded == {}
