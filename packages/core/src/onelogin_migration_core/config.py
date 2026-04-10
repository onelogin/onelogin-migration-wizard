"""Configuration utilities for the migration toolkit."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)


def _recommended_max_workers(
    source_rate_limit_per_minute: int, onelogin_rate_limit_per_hour: int
) -> int:
    source_based = max(1, source_rate_limit_per_minute // 150)
    onelogin_per_minute = max(1, onelogin_rate_limit_per_hour // 60)
    onelogin_based = max(1, onelogin_per_minute // 30)
    return max(1, min(16, source_based, onelogin_based))


@dataclass(slots=True)
class SourceApiSettings:
    """Holds configuration required to interact with the source IdP API."""

    domain: str
    token: str
    rate_limit_per_minute: int = 600
    page_size: int = 200
    provider: str = "okta"

    def __post_init__(self) -> None:
        if not self.provider:
            object.__setattr__(self, "provider", "okta")

    @property
    def provider_slug(self) -> str:
        """Return the normalized provider identifier."""

        return (self.provider or "okta").strip().lower() or "okta"

    @property
    def provider_display_name(self) -> str:
        """Return a human-readable provider label."""

        return self.provider_slug.replace("_", " ").title()

    @property
    def source_label(self) -> str:
        """Return a short label for export filenames and logging."""
        import re
        domain = self.domain or ""
        normalized = domain.replace("https://", "").replace("http://", "")
        normalized = normalized.split("/")[0]
        slug = self.provider_slug
        normalized = normalized.replace(f".{slug}.com", "")
        if "." in normalized:
            normalized = normalized.split(".")[0]
        normalized = re.sub(r"[^0-9A-Za-z_-]+", "_", normalized.strip().lower())
        return normalized or slug or "source"

    def validate(self) -> None:
        """Raise ValueError if required fields are missing."""
        if not self.domain or not self.domain.strip():
            raise ValueError(f"{self.provider_display_name} domain is required")
        if not self.token or not self.token.strip():
            raise ValueError(f"{self.provider_display_name} API token is required")

    def api_base_url(self) -> str:
        """Return the full base URL for source API calls."""

        sanitized = self.domain.rstrip("/")
        if sanitized.startswith("http"):
            return sanitized
        return f"https://{sanitized}"


OktaApiSettings = SourceApiSettings


@dataclass(slots=True)
class OneLoginApiSettings:
    """Stores client credentials and metadata for the OneLogin API."""

    client_id: str
    client_secret: str
    region: str = "us"
    subdomain: str | None = None
    rate_limit_per_hour: int = 5000

    def api_base_url(self) -> str:
        """Return the tenant-specific base URL for OneLogin's REST API."""

        subdomain = (self.subdomain or "").strip()
        if not subdomain:
            raise ValueError("OneLogin subdomain must be configured (onelogin.subdomain).")
        return f"https://{subdomain}.onelogin.com"

    def token_url(self) -> str:
        """Return the OAuth token endpoint for the configured region."""

        region = (self.region or "us").strip().lower().replace(" ", "")
        return f"https://api.{region}.onelogin.com/auth/oauth2/v2/token"


@dataclass(slots=True)
class MigrationSettings:
    """Aggregates configuration for the source-to-OneLogin migration."""

    source: SourceApiSettings
    onelogin: OneLoginApiSettings
    export_directory: Path = Path("artifacts")
    chunk_size: int = 200
    dry_run: bool = True
    concurrency_enabled: bool = False
    max_workers: int = 4
    bulk_user_upload: bool = False
    pass_app_parameters: bool = True
    # Migration category toggles
    categories: dict[str, bool] = field(
        default_factory=lambda: {
            "users": True,
            "groups": True,
            "applications": True,
            "policies": False,
        }
    )
    # Selective migration: uses inverse selection for scalability
    # Format: {"users": {"ids": [...], "inverse": bool}}
    # - inverse=True: ids are EXCLUDED (all others included)
    # - inverse=False: ids are INCLUDED (all others excluded)
    selections: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def okta(self) -> SourceApiSettings:
        """Backward-compatible alias for the configured source provider."""

        return self.source

    def ensure_export_directory(self) -> Path:
        """Create the export directory if it does not yet exist.

        If the configured directory cannot be created (e.g., read-only filesystem),
        falls back to creating an 'artifacts' directory in the user's home directory.

        Returns:
            Resolved absolute path to export directory

        Raises:
            OSError: If neither the configured directory nor the fallback can be created
        """
        # Resolve to absolute path (handles relative paths like "artifacts")
        resolved_path = self.export_directory.resolve()

        try:
            resolved_path.mkdir(parents=True, exist_ok=True)
            return resolved_path
        except OSError as e:
            # If we can't create in the configured location, try fallback
            is_readonly = e.errno == 30  # Read-only file system
            is_permission_denied = e.errno == 13  # Permission denied

            if is_readonly or is_permission_denied:
                # Fallback to user's home directory
                fallback_path = Path.home() / "onelogin-migration" / "artifacts"
                LOGGER.warning(
                    f"Cannot create export directory at '{resolved_path}': {e}. "
                    f"Using fallback location: {fallback_path}"
                )

                try:
                    fallback_path.mkdir(parents=True, exist_ok=True)
                    # Update the setting so subsequent calls use the fallback
                    self.export_directory = fallback_path
                    return fallback_path
                except OSError as fallback_error:
                    raise OSError(
                        f"Cannot create export directory at '{resolved_path}' or fallback '{fallback_path}'. "
                        f"Original error: {e}. Fallback error: {fallback_error}. "
                        f"Please specify a writable directory using the 'export_directory' setting."
                    ) from fallback_error
            else:
                # Other OSError - just raise with helpful message
                raise OSError(f"Cannot create export directory '{resolved_path}': {e}") from e

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MigrationSettings:
        """Create :class:`MigrationSettings` from a raw dictionary."""

        source_raw = data.get("source")
        if source_raw is None:
            source_raw = data.get("okta")
            if source_raw is None:
                raise ValueError(
                    "Config must contain a 'source' or 'okta' section"
                )
            if not isinstance(source_raw, dict):
                raise TypeError("Legacy 'okta' configuration must be a mapping")
            source_raw = {**source_raw, "provider": source_raw.get("provider", "okta")}
        if not isinstance(source_raw, dict):
            raise TypeError("'source' configuration must be a mapping")

        source_cfg = SourceApiSettings(**source_raw)
        onelogin_cfg = OneLoginApiSettings(**data["onelogin"])
        export_directory = Path(data.get("export_directory", "artifacts"))
        chunk_size = int(data.get("chunk_size", 200))
        dry_run = bool(data.get("dry_run", True))
        concurrency_enabled = bool(
            data.get("concurrency_enabled", data.get("enable_threading", False))
        )
        provided_max_workers = data.get("max_workers", data.get("worker_threads"))
        recommended_workers = _recommended_max_workers(
            source_cfg.rate_limit_per_minute, onelogin_cfg.rate_limit_per_hour
        )
        if provided_max_workers is None:
            max_workers = recommended_workers
            LOGGER.info(
                "Auto-configured max_workers=%s based on rate limits (source=%s/min, OneLogin=%s/hr)",
                max_workers,
                source_cfg.rate_limit_per_minute,
                onelogin_cfg.rate_limit_per_hour,
            )
        else:
            max_workers = int(provided_max_workers)
            if max_workers > recommended_workers:
                LOGGER.warning(
                    "Configured max_workers=%s exceeds recommended=%s for the current rate limits; using %s instead.",
                    max_workers,
                    recommended_workers,
                    recommended_workers,
                )
                max_workers = recommended_workers
        bulk_user_upload = bool(data.get("bulk_user_upload", False))
        pass_app_parameters = bool(data.get("pass_app_parameters", True))
        categories = data.get("categories") or {}
        # Build defaults and overlay provided values
        default_categories = {
            "users": True,
            "groups": True,
            "applications": True,
            "policies": False,
        }
        for key, value in (categories or {}).items():
            if isinstance(value, bool) and key in default_categories:
                default_categories[key] = value
        metadata = data.get("metadata", {}) or {}
        selections = data.get("selections", {}) or {}
        return cls(
            source=source_cfg,
            onelogin=onelogin_cfg,
            export_directory=export_directory,
            chunk_size=chunk_size,
            dry_run=dry_run,
            concurrency_enabled=concurrency_enabled,
            max_workers=max(1, max_workers),
            bulk_user_upload=bulk_user_upload,
            pass_app_parameters=pass_app_parameters,
            categories=default_categories,
            selections=selections,
            metadata=metadata,
        )

    @classmethod
    def from_file(cls, path: Path | str) -> MigrationSettings:
        """Load settings from a YAML configuration file."""

        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        raw = yaml.safe_load(config_path.read_text())
        if not isinstance(raw, dict):
            raise ValueError("Configuration file must contain a top-level mapping")
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration for debugging or persistence."""

        return {
            "source": {
                "provider": self.source.provider_slug,
                "domain": self.source.domain,
                "token": "***redacted***",
                "rate_limit_per_minute": self.source.rate_limit_per_minute,
                "page_size": self.source.page_size,
            },
            "onelogin": {
                "client_id": "***redacted***",
                "client_secret": "***redacted***",
                "region": self.onelogin.region,
                "subdomain": self.onelogin.subdomain,
                "rate_limit_per_hour": self.onelogin.rate_limit_per_hour,
            },
            "export_directory": str(self.export_directory),
            "chunk_size": self.chunk_size,
            "dry_run": self.dry_run,
            "concurrency_enabled": self.concurrency_enabled,
            "max_workers": self.max_workers,
            "bulk_user_upload": self.bulk_user_upload,
            "pass_app_parameters": self.pass_app_parameters,
            "categories": dict(self.categories),
            "metadata": self.metadata,
        }


def load_settings(path: Path | str) -> MigrationSettings:
    """Convenience wrapper to load :class:`MigrationSettings` from disk."""

    return MigrationSettings.from_file(path)


def ensure_config_file(config_path: Path | str, template_path: Path | str | None = None) -> Path:
    """Ensure a configuration file exists, optionally bootstrapping from a template."""

    path = Path(config_path)
    if path.exists():
        return path
    if template_path is None:
        raise FileNotFoundError(f"Configuration file not found and no template provided: {path}")
    template = Path(template_path)
    if not template.exists():
        raise FileNotFoundError(f"Template configuration file not found: {template}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.read_text())
    return path


def read_config_text(path: Path | str) -> str:
    """Return the raw text contents of a configuration file."""

    return Path(path).read_text()


def parse_config_text(text: str) -> MigrationSettings:
    """Validate configuration text and produce :class:`MigrationSettings`."""

    try:
        data = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Configuration file must contain a top-level mapping")
    try:
        return MigrationSettings.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid configuration structure: {exc}") from exc


def save_config_text(path: Path | str, text: str) -> MigrationSettings:
    """Persist configuration YAML to disk after validation."""

    settings = parse_config_text(text)
    normalized = text if text.endswith("\n") else f"{text}\n"
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(normalized)
    return settings


__all__ = [
    "SourceApiSettings",
    "OktaApiSettings",
    "OneLoginApiSettings",
    "MigrationSettings",
    "load_settings",
    "ensure_config_file",
    "read_config_text",
    "parse_config_text",
    "save_config_text",
]
