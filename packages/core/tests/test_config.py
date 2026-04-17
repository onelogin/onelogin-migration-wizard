from pathlib import Path

import pytest
import yaml

from onelogin_migration_core.config import (
    MigrationSettings,
    ensure_config_file,
    read_config_text,
    save_config_text,
)


def test_load_settings_from_file(tmp_path: Path) -> None:
    data = {
        "dry_run": True,
        "okta": {
            "domain": "example.okta.com",
            "token": "token",
            "rate_limit_per_minute": 100,
            "page_size": 200,
        },
        "onelogin": {
            "client_id": "client",
            "client_secret": "secret",
            "region": "us",
            "subdomain": "example",
        },
        "metadata": {"env": "test"},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(data))

    settings = MigrationSettings.from_file(config_path)

    assert settings.okta.domain == "example.okta.com"
    assert settings.onelogin.client_id == "client"
    assert settings.metadata["env"] == "test"
    assert settings.export_directory.name == "artifacts"


def test_ensure_config_file_creates_from_template(tmp_path: Path) -> None:
    template = tmp_path / "migration.template.yaml"
    template.write_text(
        "dry_run: true\nokta: {domain: example.okta.com, token: token}\nonelogin: {client_id: id, client_secret: secret}\n"
    )
    destination = tmp_path / "migration.yaml"

    created = ensure_config_file(destination, template)

    assert created == destination
    assert destination.exists()
    assert destination.read_text() == template.read_text()


def test_save_config_text_validates_and_persists(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "migration.yaml"
    payload = """
dry_run: false
okta:
  domain: example.okta.com
  token: api-token
onelogin:
  client_id: client
  client_secret: secret
""".strip()

    settings = save_config_text(config_path, payload)

    assert settings.dry_run is False
    assert config_path.exists()
    assert read_config_text(config_path).startswith("dry_run: false")


def test_save_config_text_rejects_invalid_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "migration.yaml"

    with pytest.raises(ValueError):
        save_config_text(config_path, "dry_run: [unclosed")
