"""Tests for the module-level CLI entry point."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from onelogin_migration_core.cli import app
from pytest import MonkeyPatch
from typer.testing import CliRunner


def test_python_module_invocation_displays_help() -> None:
    """Running ``python -m onelogin_migration_tool`` should expose the Typer CLI."""

    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    src_path = str(repo_root / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing else f"{src_path}{os.pathsep}{existing}"

    result = subprocess.run(
        [sys.executable, "-m", "onelogin_migration_tool", "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "Okta to OneLogin migration automation tools" in result.stdout


class DummyPlanManager:
    def __init__(self, export_payload: dict[str, Any]) -> None:
        self.export_payload = export_payload
        self.saved_exports: list[dict[str, Any]] = []
        self.saved_destinations: list[Path | None] = []

    def export_from_okta(self) -> dict[str, Any]:
        return self.export_payload

    def save_export(self, export: dict[str, Any], destination: Path | None = None) -> Path:
        self.saved_exports.append(export)
        self.saved_destinations.append(destination)
        return destination or Path("artifacts/okta_export.json")


class DummyMigrateManager:
    def __init__(self, export_payload: dict[str, Any]) -> None:
        self.export_payload = export_payload
        self.run_calls: list[tuple[Path | None, bool]] = []
        self.last_bulk_export: Path | None = None

    def run(self, export_file: Path | None, force_import: bool = False) -> dict[str, Any]:
        self.run_calls.append((export_file, force_import))
        return self.export_payload


def test_cli_plan_handles_group_assignments(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("ok: true")
    output_path = tmp_path / "export.json"

    export_payload = {
        "users": [],
        "groups": [],
        "applications": [
            {
                "id": "app-1",
                "label": "Example",
                "_embedded": {"group": [{"id": "grp-1", "profile": {"name": "Admins"}}]},
            }
        ],
    }

    dummy_manager = DummyPlanManager(export_payload)

    def fake_build_manager(config: Path, *, dry_run: bool | None = None) -> DummyPlanManager:
        assert dry_run is True
        assert config == config_path
        return dummy_manager

    monkeypatch.setattr("onelogin_migration_tool.cli.build_manager", fake_build_manager)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["plan", "--config", str(config_path), "--output", str(output_path)],
    )

    assert result.exit_code == 0
    assert dummy_manager.saved_exports
    saved_app = dummy_manager.saved_exports[0]["applications"][0]
    assert saved_app["_embedded"]["group"][0]["id"] == "grp-1"


def test_cli_migrate_reports_processed_users(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("ok: true")

    export_payload = {
        "users": [{"id": "user-1"}],
        "applications": [
            {
                "id": "app-1",
                "label": "Example",
                "_embedded": {"group": [{"id": "grp-1"}]},
            }
        ],
    }

    dummy_manager = DummyMigrateManager(export_payload)

    def fake_build_manager(
        config: Path,
        *,
        dry_run: bool | None = None,
        bulk_user_upload: bool | None = None,
    ) -> DummyMigrateManager:
        assert dry_run is False
        assert bulk_user_upload is False
        assert config == config_path
        return dummy_manager

    monkeypatch.setattr("onelogin_migration_tool.cli.build_manager", fake_build_manager)

    runner = CliRunner()
    result = runner.invoke(app, ["migrate", "--config", str(config_path)])

    assert result.exit_code == 0
    assert dummy_manager.run_calls == [(None, True)]
    assert "Users processed: 1" in result.stdout


def test_cli_migrate_bulk_user_upload(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("ok: true")

    export_payload = {"users": []}
    dummy_manager = DummyMigrateManager(export_payload)

    def fake_build_manager(
        config: Path,
        *,
        dry_run: bool | None = None,
        bulk_user_upload: bool | None = None,
    ) -> DummyMigrateManager:
        assert dry_run is False
        assert bulk_user_upload is True
        assert config == config_path
        return dummy_manager

    monkeypatch.setattr("onelogin_migration_tool.cli.build_manager", fake_build_manager)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["migrate", "--config", str(config_path), "--bulk-user-upload"],
    )

    assert result.exit_code == 0
    assert "Bulk user upload CSV" in result.stdout
