"""Core orchestration logic for source-to-OneLogin migrations."""

from __future__ import annotations

import csv
import json
import logging
import re
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .clients import OneLoginClient, SourceClient, build_clients
from .config import MigrationSettings
from .csv_generator import BulkUserCSVGenerator
from .progress import MigrationProgress

LOGGER = logging.getLogger(__name__)

DEFAULT_APPLICATION_CONNECTORS: dict[str, dict[str | None, int]] = {}


class MigrationAborted(RuntimeError):
    """Raised when a migration run is cancelled mid-flight."""

    pass


class MigrationManager:
    """Coordinates export from the source provider and import into OneLogin."""

    def __init__(
        self,
        settings: MigrationSettings,
        source_client: SourceClient | None = None,
        onelogin_client: OneLoginClient | None = None,
        progress: MigrationProgress | None = None,
        dry_run: bool | None = None,
        okta_client: SourceClient | None = None,
    ) -> None:
        self.settings = settings
        source_client = source_client or okta_client
        clients = (
            build_clients(settings, dry_run=dry_run)
            if source_client is None or onelogin_client is None
            else None
        )
        self.source = source_client or clients["source"]  # type: ignore[index]
        self.okta = self.source
        self.onelogin = onelogin_client or clients["onelogin"]  # type: ignore[index]
        self.progress = progress or MigrationProgress()
        self._stop_event = threading.Event()
        self._stopped = False
        self._state_lock = threading.Lock()
        self._state_file = self.settings.ensure_export_directory() / "migration_state.json"
        self._state: dict[str, Any] = {}
        self._completed_ids: dict[str, set[str]] = {}
        self._lookup_state: dict[str, dict[str, int]] = {"groups": {}, "users": {}}
        self._state_loaded = False
        self._threading_enabled = bool(self.settings.concurrency_enabled)
        self._max_workers = max(1, int(self.settings.max_workers))
        self.last_bulk_export: Path | None = None
        initial_dry_run = (
            dry_run if dry_run is not None else getattr(self.onelogin, "dry_run", settings.dry_run)
        )
        self.set_dry_run(bool(initial_dry_run))
        self.set_threading(self._threading_enabled, self._max_workers)
        self.set_bulk_user_upload(self.settings.bulk_user_upload)

        # Initialize database for connector lookups
        from .db import (
            get_connector_refresh_service,
            get_default_connector_db,
            get_telemetry_manager,
            get_user_database,
        )

        self._connector_db = get_default_connector_db()
        self._user_db = get_user_database()  # Writable database for telemetry and refresh logs
        self._telemetry = get_telemetry_manager(self._user_db)

        # Refresh connectors if stale (background, non-blocking)
        # Use user database since refresh service needs to write logs
        refresh_service = get_connector_refresh_service(self._user_db)
        try:
            refresh_service.refresh_if_stale(self.onelogin)
        except Exception as e:
            LOGGER.warning("Connector refresh check failed (non-fatal): %s", e)

        # Build connector lookup (now uses database + fallback to static)
        self._application_connector_lookup = self._build_application_connector_lookup()

        # Generate migration run ID for telemetry
        import uuid

        self._migration_run_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Concurrency and state management
    # ------------------------------------------------------------------

    def set_threading(self, enabled: bool, max_workers: int | None = None) -> None:
        """Enable/disable multithreaded processing and update worker count."""

        self._threading_enabled = bool(enabled)
        if max_workers is not None:
            self._max_workers = max(1, int(max_workers))
        self.settings.concurrency_enabled = self._threading_enabled
        self.settings.max_workers = self._max_workers

    def set_bulk_user_upload(self, enabled: bool) -> None:
        """Configure whether to write a bulk upload CSV instead of user API calls."""

        self.settings.bulk_user_upload = bool(enabled)
        self.bulk_user_upload = bool(enabled)
        if not enabled:
            self.last_bulk_export = None

    def _load_state(self) -> None:
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

    def _save_state_locked(self) -> None:
        from datetime import datetime

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

        # Add metadata for stale state detection
        data["migration_run_id"] = self._migration_run_id
        data["last_updated"] = datetime.now().isoformat()
        # Status will be updated by run() method on completion/failure
        if "status" not in data:
            data["status"] = "in_progress"

        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(data, indent=2, sort_keys=True))

    def _reset_completion_state(self) -> None:
        with self._state_lock:
            self._completed_ids = {}
            self._lookup_state = {"groups": {}, "users": {}}
            self._state.pop("completed", None)
            self._state.pop("lookups", None)
            self._save_state_locked()

    def _clear_state(self) -> None:
        with self._state_lock:
            self._state = {}
            self._completed_ids = {}
            self._lookup_state = {"groups": {}, "users": {}}
            self._state_loaded = False
            try:
                self._state_file.unlink()
            except FileNotFoundError:
                pass

    def _record_export_path(self, export_path: Path) -> None:
        with self._state_lock:
            self._state["export_path"] = str(export_path)
            self._save_state_locked()

    def _state_export_path(self) -> Path | None:
        self._load_state()
        raw = self._state.get("export_path")
        return Path(raw) if isinstance(raw, str) else None

    def _is_completed(self, category: str, identifier: str | None) -> bool:
        if identifier is None:
            return False
        self._load_state()
        with self._state_lock:
            completed = self._completed_ids.setdefault(category, set())
            return identifier in completed

    def _mark_completed(self, category: str, identifier: str | None) -> None:
        if identifier is None:
            return
        with self._state_lock:
            bucket = self._completed_ids.setdefault(category, set())
            if identifier in bucket:
                return
            bucket.add(identifier)
            self._save_state_locked()

    def _update_lookup(self, category: str, source_id: str | None, target_id: int | None) -> None:
        if source_id is None or target_id is None:
            return
        if category not in {"groups", "users"}:
            return
        with self._state_lock:
            bucket = self._lookup_state.setdefault(category, {})
            if bucket.get(source_id) == int(target_id):
                return
            bucket[source_id] = int(target_id)
            self._save_state_locked()

    def _lookup_ids(self, category: str) -> dict[str, int]:
        self._load_state()
        return dict(self._lookup_state.get(category, {}))

    def _completed_memberships(self) -> set[str]:
        self._load_state()
        with self._state_lock:
            return set(self._completed_ids.get("memberships", set()))

    def _mark_membership(self, membership_id: str) -> None:
        self._mark_completed("memberships", membership_id)

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------
    def _filter_export_by_selections(self, export: dict[str, Any]) -> dict[str, Any]:
        """Filter exported data using inverse selection for scalability.

        Supports both include and exclude modes for each category:
        - inverse=True: IDs are EXCLUDED (all others included)
        - inverse=False: IDs are INCLUDED (all others excluded)

        Args:
            export: Full export data from Okta

        Returns:
            Filtered export containing only selected items
        """
        if not self.settings.selections:
            # No selections specified, return full export
            return export

        filtered_export = dict(export)

        # Helper function to filter a category
        def filter_category(
            category_name: str, items: list[dict[str, Any]], id_key: str = "id"
        ) -> list[dict[str, Any]]:
            selection_config = self.settings.selections.get(category_name)
            if not selection_config:
                return items  # No selection for this category

            ids = set(selection_config.get("ids", []))
            is_inverse = selection_config.get("inverse", True)

            if not ids:
                # Empty IDs list
                if is_inverse:
                    # Empty exclude list = include all
                    return items
                else:
                    # Empty include list = include none
                    return []

            # Filter based on mode
            if is_inverse:
                # Exclude mode: keep items NOT in the set
                filtered = [item for item in items if str(item.get(id_key, "")) not in ids]
                LOGGER.info(
                    f"Filtered {category_name} (EXCLUDE mode): {len(items)} → {len(filtered)} (excluded {len(ids)} IDs)"
                )
            else:
                # Include mode: keep items IN the set
                filtered = [item for item in items if str(item.get(id_key, "")) in ids]
                LOGGER.info(
                    f"Filtered {category_name} (INCLUDE mode): {len(items)} → {len(filtered)} (included {len(ids)} IDs)"
                )

            return filtered

        # Filter each category
        original_users = export.get("users", [])
        filtered_export["users"] = filter_category("users", original_users)

        original_groups = export.get("groups", [])
        filtered_export["groups"] = filter_category("groups", original_groups)

        original_apps = export.get("applications", [])
        filtered_export["applications"] = filter_category("applications", original_apps)

        # Note: memberships will be automatically filtered during import
        # since we only process users and groups that exist

        return filtered_export

    def export_from_source(self) -> dict[str, Any]:
        """Collect users, groups, and applications from the source provider."""

        self._check_for_stop()
        LOGGER.info("Starting export from %s", self.settings.source.provider_display_name)
        export = self.source.export_all(self.settings.categories)

        # Filter by selections if specified
        export = self._filter_export_by_selections(export)

        self._initialize_progress(export)
        self._check_for_stop()
        LOGGER.info(
            "Exported %s users, %s groups, %s applications",
            len(export.get("users", [])),
            len(export.get("groups", [])),
            len(export.get("applications", [])),
        )
        return export

    def export_from_okta(self) -> dict[str, Any]:
        """Backward-compatible alias for exporting from the source provider."""

        return self.export_from_source()

    def save_export(self, export: dict[str, Any], destination: Path | None = None) -> Path:
        """Persist source export data to disk with optional encryption."""

        if destination is None:
            export_path = self.settings.ensure_export_directory() / "source_export.json"
        else:
            destination = Path(destination)
            if destination.suffix:
                export_path = destination
            else:
                destination.mkdir(parents=True, exist_ok=True)
                export_path = destination / "source_export.json"
        export_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize to JSON
        json_data = json.dumps(export, indent=2, sort_keys=True)

        # Try to encrypt the main export file for security
        encrypted = False
        try:
            from .db import get_encryption_manager, is_encryption_available

            if is_encryption_available():
                encryption_mgr = get_encryption_manager()
                encrypted_data = encryption_mgr.encrypt(json_data.encode("utf-8"))
                export_path.write_bytes(encrypted_data)
                encrypted = True
                LOGGER.info("Saved encrypted source export to %s", export_path)
            else:
                export_path.write_text(json_data)
                LOGGER.debug("Encryption not available - saved plaintext export")
        except Exception as e:
            LOGGER.warning("Encryption failed (%s) - falling back to plaintext", e)
            export_path.write_text(json_data)

        # Set secure file permissions (user read/write only)
        try:
            export_path.chmod(0o600)
        except Exception as e:
            LOGGER.debug("Failed to set secure file permissions: %s", e)

        if not encrypted:
            LOGGER.info("Saved source export to %s", export_path)

        # Persist per-category snapshots for easier auditing (plaintext for debugging)
        export_directory = export_path.parent
        source_label = self._source_label()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for key, value in export.items():
            filename = f"{source_label}_{key}_{timestamp}.json"
            bucket_path = export_directory / filename
            try:
                bucket_path.write_text(json.dumps(value, indent=2, sort_keys=True))
                bucket_path.chmod(0o600)
                LOGGER.info("Saved %s export to %s", key, bucket_path)
            except TypeError:
                # Fallback to raw serialization if non-JSON data slips through
                bucket_path.write_text(json.dumps(value, default=str, indent=2, sort_keys=True))
                try:
                    bucket_path.chmod(0o600)
                except Exception:
                    pass
                LOGGER.info(
                    "Saved %s export to %s (with fallback serialization)",
                    key,
                    bucket_path,
                )
            except Exception as e:
                LOGGER.debug("Failed to set permissions on %s: %s", bucket_path, e)
        return export_path

    def load_export(self, path: Path | str) -> dict[str, Any]:
        """Load source export from disk, with automatic decryption if encrypted."""
        export_path = Path(path)
        if not export_path.exists():
            raise FileNotFoundError(f"Export file not found: {export_path}")

        # Try to decrypt first (handles encrypted files)
        try:
            from .db import get_encryption_manager, is_encryption_available

            if is_encryption_available():
                encrypted_data = export_path.read_bytes()
                encryption_mgr = get_encryption_manager()
                try:
                    decrypted_data = encryption_mgr.decrypt(encrypted_data)
                    json_str = decrypted_data.decode("utf-8")
                    LOGGER.debug("Successfully decrypted export from %s", export_path)
                    return json.loads(json_str)
                except Exception:
                    # Not encrypted or decryption failed, try plaintext
                    LOGGER.debug("File not encrypted, reading as plaintext")
                    pass
        except Exception as e:
            LOGGER.debug("Encryption not available, reading as plaintext: %s", e)

        # Fallback to plaintext
        return json.loads(export_path.read_text())

    # ------------------------------------------------------------------
    # Import helpers
    # ------------------------------------------------------------------
    def import_into_onelogin(self, export: dict[str, Any]) -> None:
        """Import data into OneLogin."""
        self._initialize_progress(export)
        LOGGER.info("Beginning import into OneLogin (dry_run=%s)", self.dry_run)
        self._check_for_stop()
        if self.bulk_user_upload:
            output_path = self._generate_bulk_user_upload(export)
            LOGGER.info("Bulk user upload CSV written to %s", output_path)
            return
        role_lookup: dict[str, int] = self._lookup_ids("groups")
        existing_roles_by_name: dict[str, dict[str, Any]] = {}
        user_lookup: dict[str, int] = self._lookup_ids("users")
        role_lock = threading.Lock()
        role_condition = threading.Condition(role_lock)
        pending_role_names: set[str] = set()
        user_lock = threading.Lock()

        if self.settings.categories.get("groups", True):
            existing_roles_by_name = self._prepare_one_login_roles()

            roles_created_count = {"count": 0}  # Mutable counter for thread-safe increments

            def group_identifier(item: Any) -> str | None:
                return self._item_identifier("groups", item)

            def handle_group(item: Any, identifier: str | None) -> bool | None:
                payload = self._transform_group(item)
                if not payload:
                    return True
                role_name = payload.get("name")
                normalized_name = self._normalize_role_name(role_name)
                pending_registered = False
                assigned_lookup_id: int | None = None
                if normalized_name:
                    reuse_existing = False
                    with role_condition:
                        while normalized_name in pending_role_names:
                            role_condition.wait()
                        existing_role = existing_roles_by_name.get(normalized_name)
                        if existing_role:
                            existing_id = existing_role.get("id")
                            LOGGER.info(
                                "Role '%s' already exists in OneLogin (id=%s); reusing.",
                                role_name,
                                existing_id,
                            )
                            if identifier and existing_id is not None:
                                try:
                                    numeric_id = int(existing_id)
                                except (TypeError, ValueError):
                                    LOGGER.warning(
                                        "Unable to coerce OneLogin role id %r for group %s; skipping lookup update.",
                                        existing_id,
                                        identifier,
                                    )
                                else:
                                    role_lookup[identifier] = numeric_id
                                    assigned_lookup_id = numeric_id
                            reuse_existing = True
                        else:
                            pending_role_names.add(normalized_name)
                            pending_registered = True
                    if reuse_existing:
                        if identifier and assigned_lookup_id is not None:
                            self._update_lookup("groups", identifier, assigned_lookup_id)
                        return True
                self._check_for_stop()
                display_name = role_name or "Unknown"
                LOGGER.info("Creating role: %s", display_name)
                try:
                    response = self.onelogin.ensure_role(payload)
                    if response and isinstance(response, dict):
                        role_id = response.get("id")
                        if role_id is not None:
                            try:
                                numeric_id = int(role_id)
                            except (TypeError, ValueError):
                                LOGGER.warning(
                                    "Unable to coerce OneLogin role id %r for group %s; response=%s",
                                    role_id,
                                    identifier or payload.get("name"),
                                    str(response)[:200],
                                )
                            else:
                                LOGGER.info(
                                    "✓ Created role '%s' with ID: %d",
                                    display_name,
                                    numeric_id,
                                )
                                with role_condition:
                                    roles_created_count["count"] += 1
                                    if normalized_name:
                                        existing_roles_by_name[normalized_name] = {
                                            "id": numeric_id,
                                            "name": display_name,
                                        }
                                        pending_role_names.discard(normalized_name)
                                        role_condition.notify_all()
                                    if identifier:
                                        role_lookup[identifier] = numeric_id
                                if identifier:
                                    self._update_lookup("groups", identifier, numeric_id)
                        else:
                            LOGGER.warning(
                                "OneLogin role creation response missing 'id' for group %s; skipping lookup update.",
                                identifier or payload.get("name"),
                            )
                finally:
                    if normalized_name and pending_registered:
                        with role_condition:
                            if normalized_name in pending_role_names:
                                pending_role_names.discard(normalized_name)
                                role_condition.notify_all()
                return True

            self._process_items(
                "groups",
                export.get("groups", []),
                group_identifier,
                handle_group,
            )

            LOGGER.info(
                "Role creation complete. Total roles created: %d",
                roles_created_count["count"],
            )

        if self.settings.categories.get("users", True):

            def user_identifier(item: Any) -> str | None:
                return self._item_identifier("users", item)

            def handle_user(item: Any, identifier: str | None) -> bool | None:
                payload = self._transform_user(item)
                if not payload:
                    return True
                custom_attributes = payload.get("custom_attributes")
                if isinstance(custom_attributes, dict) and custom_attributes:
                    try:
                        self.onelogin.ensure_custom_attribute_definitions(custom_attributes)  # type: ignore[attr-defined]
                    except AttributeError:
                        LOGGER.debug(
                            "OneLogin client does not support custom attribute provisioning; skipping definition sync",
                        )
                self._check_for_stop()
                response = self.onelogin.ensure_user(payload)
                if response and isinstance(response, dict):
                    user_id = response.get("id")
                    if user_id is not None and identifier:
                        try:
                            numeric_id = int(user_id)
                        except (TypeError, ValueError):
                            LOGGER.warning(
                                "Unable to coerce OneLogin user id %r for identifier %s; response=%s",
                                user_id,
                                identifier,
                                str(response)[:200],
                            )
                        else:
                            with user_lock:
                                user_lookup[identifier] = numeric_id
                            self._update_lookup("users", identifier, numeric_id)
                    elif identifier:
                        LOGGER.warning(
                            "OneLogin user response missing 'id' for identifier %s; skipping lookup update.",
                            identifier,
                        )
                return True

            self._process_items(
                "users",
                export.get("users", []),
                user_identifier,
                handle_user,
            )

        if self.settings.categories.get("groups", True) and self.settings.categories.get(
            "users", True
        ):
            assign_bulk = getattr(self.onelogin, "assign_users_to_role_bulk", None)
            if callable(assign_bulk):
                completed_memberships = self._completed_memberships()
                role_assignments: dict[int, dict[str, Any]] = {}
                for membership in export.get("memberships", []):
                    if not isinstance(membership, dict):
                        continue
                    group_id = membership.get("group_id") or membership.get("groupId")
                    user_id = membership.get("user_id") or membership.get("userId")
                    if group_id is None or user_id is None:
                        continue
                    membership_key = self._membership_identifier(group_id, user_id)
                    if membership_key in completed_memberships:
                        continue
                    role_id = role_lookup.get(str(group_id))
                    ol_user_id = user_lookup.get(str(user_id))
                    if role_id is None or ol_user_id is None:
                        continue
                    bucket = role_assignments.setdefault(int(role_id), {"keys": [], "users": set()})
                    bucket["keys"].append(membership_key)
                    bucket["users"].add(int(ol_user_id))

                for role_id, data in role_assignments.items():
                    user_ids = data["users"]
                    try:
                        assign_bulk(int(role_id), user_ids)
                    except Exception as exc:  # pragma: no cover - best effort logging
                        LOGGER.warning(
                            "Failed to assign users %s to role %s: %s",
                            sorted(user_ids),
                            role_id,
                            exc,
                        )
                    else:
                        for membership_key in data["keys"]:
                            self._mark_membership(membership_key)
            else:
                LOGGER.debug(
                    "OneLogin client does not support bulk role assignment; skipping membership sync"
                )

        if self.settings.categories.get("applications", True):

            def app_identifier(item: Any) -> str | None:
                return self._item_identifier("applications", item)

            def handle_application(item: Any, identifier: str | None) -> bool | None:
                payload = self._transform_application(item)
                if not payload:
                    return True
                self._check_for_stop()

                try:
                    response = self.onelogin.ensure_application(payload)
                    if response and isinstance(response, dict):
                        self._assign_roles_to_application(item, response, role_lookup)
                    return True
                except Exception as e:
                    app_name = payload.get("name", "unknown")
                    LOGGER.error(
                        "Failed to create or configure app '%s': %s",
                        app_name,
                        str(e),
                    )
                    LOGGER.warning(
                        "Continuing with remaining applications despite failure for '%s'",
                        app_name,
                    )
                    # Return True to indicate we handled the error and should continue
                    return True

            self._process_items(
                "applications",
                export.get("applications", []),
                app_identifier,
                handle_application,
            )

        LOGGER.info("Import into OneLogin complete")

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def run(self, export_file: Path | None = None, *, force_import: bool = False) -> dict[str, Any]:
        export: dict[str, Any] = {}
        self.reset_stop_request()
        self._state_loaded = False
        self._load_state()
        success = False
        self.last_bulk_export = None

        # Track migration timing for telemetry
        from datetime import datetime

        start_time = datetime.now()

        try:
            self._check_for_stop()
            export_path: Path | None
            if export_file is not None:
                export_path = Path(export_file)
                export = self.load_export(export_path)
                # Apply selection filtering after loading from file
                export = self._filter_export_by_selections(export)
                self._record_export_path(export_path)
                self._reset_completion_state()
            else:
                cached_path = self._state_export_path()
                if cached_path and cached_path.exists():
                    LOGGER.info("Reusing cached export from %s", cached_path)
                    export_path = cached_path
                    export = self.load_export(cached_path)
                    # Apply selection filtering after loading from cache
                    export = self._filter_export_by_selections(export)
                else:
                    if cached_path and not cached_path.exists():
                        LOGGER.info(
                            "Cached export %s missing; clearing saved state",
                            cached_path,
                        )
                        self._clear_state()
                        self._state_loaded = False
                        self._load_state()
                    export = self.export_from_source()
                    self._check_for_stop()
                    export_path = self.save_export(export)
                    self._record_export_path(export_path)
                    self._reset_completion_state()
            self._check_for_stop()
            if force_import or not self.dry_run:
                self.import_into_onelogin(export)
            else:
                LOGGER.info("Dry-run enabled; skipping import into OneLogin")
            success = True
        except MigrationAborted:
            LOGGER.info("Migration aborted by stop request")
            self._log_error_telemetry("MigrationAborted", "migration")
            # Mark state as cancelled
            with self._state_lock:
                self._state["status"] = "cancelled"
                self._save_state_locked()
        except Exception as e:
            # Log error pattern for telemetry (category only, no details)
            self._log_error_telemetry(type(e).__name__, "migration", e)
            # Mark state as failed before re-raising
            with self._state_lock:
                self._state["status"] = "failed"
                self._state["error_type"] = type(e).__name__
                self._state["error_message"] = str(e)[:500]  # Truncate long messages
                self._save_state_locked()
            raise
        finally:
            if success and not self.was_stopped():
                # Mark as completed before clearing
                with self._state_lock:
                    self._state["status"] = "completed"
                    self._save_state_locked()
                self._clear_state()

            # Log migration scenario telemetry
            if success:
                duration = (datetime.now() - start_time).total_seconds()
                self._log_migration_scenario_telemetry(export, duration, success=True)

        return export

    def set_dry_run(self, enabled: bool) -> None:
        """Toggle dry run mode for subsequent operations."""

        self.dry_run = bool(enabled)
        self.settings.dry_run = self.dry_run
        if hasattr(self.onelogin, "dry_run"):
            self.onelogin.dry_run = self.dry_run

    def request_stop(self) -> None:
        """Signal that the current migration run should stop as soon as possible."""

        self._stop_event.set()

    def reset_stop_request(self) -> None:
        """Clear any pending stop requests before starting a new run."""

        self._stop_event.clear()
        self._stopped = False

    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def was_stopped(self) -> bool:
        return self._stopped

    def update_settings(self, settings: MigrationSettings) -> None:
        """Replace runtime configuration and rebuild API clients."""

        self.settings = settings
        clients = build_clients(settings, dry_run=settings.dry_run)
        self.source = clients["source"]  # type: ignore[index]
        self.okta = self.source
        self.onelogin = clients["onelogin"]  # type: ignore[index]
        self.set_dry_run(settings.dry_run)
        self.set_threading(settings.concurrency_enabled, settings.max_workers)
        self.set_bulk_user_upload(settings.bulk_user_upload)
        self.last_bulk_export = None

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------
    def _process_items(
        self,
        category: str,
        items: Iterable[Any],
        identifier_fn: Callable[[Any], str | None],
        handler: Callable[[Any, str | None], bool | None],
    ) -> None:
        sequence = list(items) if not isinstance(items, list) else items  # type: ignore[assignment]
        if not sequence:
            return
        prepared = [(item, identifier_fn(item)) for item in sequence]

        pending: list[tuple[Any, str | None]] = []
        for item, identifier in prepared:
            if identifier and self._is_completed(category, identifier):
                self.progress.increment(category)
            else:
                pending.append((item, identifier))

        if not pending:
            return

        if not self._threading_enabled or self._max_workers <= 1 or len(pending) <= 1:
            for item, identifier in pending:
                self._process_single_item(category, item, identifier, handler)
            return

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures: list[Future[None]] = []
            for item, identifier in pending:
                futures.append(
                    executor.submit(self._process_single_item, category, item, identifier, handler)
                )
            try:
                for future in as_completed(futures):
                    future.result()
            except MigrationAborted:
                for future in futures:
                    future.cancel()
                raise
            except Exception:
                for future in futures:
                    future.cancel()
                raise

    def _process_single_item(
        self,
        category: str,
        item: Any,
        identifier: str | None,
        handler: Callable[[Any, str | None], bool | None],
    ) -> None:
        self._check_for_stop()

        # Log individual operation in verbose mode (DEBUG level)
        if identifier:
            LOGGER.debug("Processing %s: %s", category.rstrip("s"), identifier)

        result = handler(item, identifier)

        # Log result
        if result is not False:
            self._mark_completed(category, identifier)
            if identifier:
                LOGGER.debug("✓ Completed %s: %s", category.rstrip("s"), identifier)
        else:
            if identifier:
                LOGGER.debug("⚠ Skipped %s: %s", category.rstrip("s"), identifier)

        self.progress.increment(category)

    def _generate_bulk_user_upload(self, export: dict[str, Any]) -> Path:
        for category in ("groups", "applications", "policies"):
            self.progress.set_total(category, 0)
        users = export.get("users", [])
        rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        custom_attrs: set[str] = set()

        LOGGER.info("Starting bulk user CSV generation with %d users", len(users))
        skipped_count = 0

        def identifier_fn(item: Any) -> str | None:
            return self._item_identifier("users", item)

        def handler(item: Any, identifier: str | None) -> bool | None:
            nonlocal skipped_count
            payload = self._transform_user(item)
            if not payload:
                skipped_count += 1
                LOGGER.debug("Skipping user %s - empty payload after transformation", identifier)
                return True
            attributes = dict(payload.get("custom_attributes") or {})
            base_payload = {k: v for k, v in payload.items() if k != "custom_attributes"}
            if attributes:
                custom_attrs.update(attributes.keys())
            rows.append((base_payload, attributes))
            return True

        self._process_items("users", users, identifier_fn, handler)

        LOGGER.info(
            "Bulk user CSV: %d users processed, %d skipped, %d rows to write",
            len(users),
            skipped_count,
            len(rows),
        )

        template_headers = self._load_bulk_template_headers()
        custom_attr_list = sorted(custom_attrs)
        if custom_attr_list:
            self._ensure_bulk_custom_attributes(custom_attr_list)
        self.last_bulk_export = self._write_bulk_user_csv(
            rows,
            template_headers,
            custom_attr_list,
        )
        return self.last_bulk_export

    def _load_bulk_template_headers(self) -> list[str]:
        return BulkUserCSVGenerator.load_template_headers()

    def _write_bulk_user_csv(
        self,
        rows: list[tuple[dict[str, Any], dict[str, Any]]],
        template_headers: list[str],
        custom_attributes: list[str],
    ) -> Path:
        base_headers = [h for h in template_headers if not h.startswith("custom_attribute")]
        headers = base_headers + custom_attributes
        destination_dir = self.settings.ensure_export_directory()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = destination_dir / f"bulk_user_upload_{timestamp}.csv"

        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for payload, attrs in rows:
                record: dict[str, Any] = {}
                for key in headers:
                    if key in custom_attributes:
                        value = attrs.get(key)
                    else:
                        value = payload.get(key)
                    record[key] = self._csv_value(value)
                writer.writerow(record)

        return output_path

    @staticmethod
    def _csv_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _ensure_bulk_custom_attributes(self, attributes: list[str]) -> None:
        if not attributes:
            return
        helper = getattr(self.onelogin, "ensure_custom_attribute_definitions", None)
        if not callable(helper):
            LOGGER.debug(
                "OneLogin client does not support custom attribute provisioning; skipping CSV attribute setup"
            )
            return
        payload = dict.fromkeys(attributes, "")
        if self.dry_run:
            LOGGER.info(
                "[DRY-RUN] Would ensure the following custom attributes exist in OneLogin: %s",
                ", ".join(attributes),
            )
            return
        try:
            helper(payload)
        except Exception:  # pragma: no cover - best effort logging
            LOGGER.exception(
                "Failed to ensure custom attribute definitions for bulk upload: %s",
                ", ".join(attributes),
            )

    def _initialize_progress(self, export: dict[str, Any]) -> None:
        for category in ("users", "groups", "applications", "policies"):
            if not self.settings.categories.get(category, True):
                self.progress.set_total(category, 0)
                continue
            items = export.get(category, [])
            if isinstance(items, Iterable):
                try:
                    total = len(items)  # type: ignore[arg-type]
                except TypeError:
                    # Convert generator to list to count without exhausting
                    # Store the list back in export so later processing doesn't get empty generator
                    items_list = list(items)
                    export[category] = items_list
                    total = len(items_list)
                self.progress.set_total(category, total)

    def _check_for_stop(self) -> None:
        if self._stop_event.is_set():
            self._stopped = True
            raise MigrationAborted()

    @staticmethod
    def _item_identifier(category: str, item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        if category == "groups":
            group_id = item.get("id")
            if group_id is not None:
                return str(group_id)
            profile = item.get("profile")
            if isinstance(profile, dict):
                name = profile.get("name")
                if name:
                    return str(name)
            return None
        if category == "users":
            user_id = item.get("id")
            if user_id is not None:
                return str(user_id)
            profile = item.get("profile")
            if isinstance(profile, dict):
                for key in ("login", "email", "secondEmail"):
                    value = profile.get(key)
                    if value:
                        return str(value)
            return None
        if category == "applications":
            app_id = item.get("id")
            if app_id is not None:
                return str(app_id)
            label = item.get("label")
            if label:
                return str(label)
            return None
        return None

    @staticmethod
    def _membership_identifier(group_id: Any, user_id: Any) -> str:
        return f"{group_id}:{user_id}"

    def _transform_user(self, user: dict[str, Any]) -> dict[str, Any] | None:
        profile = user.get("profile") or {}
        credentials = user.get("credentials") or {}
        if not profile and not credentials:
            LOGGER.debug("User missing profile and credentials: %s", user.get("id"))
            return None

        def first_value(*candidates: Any) -> Any | None:
            for candidate in candidates:
                if isinstance(candidate, str):
                    if candidate.strip():
                        return candidate
                elif candidate:
                    return candidate
            return None

        def email_from_credentials() -> str | None:
            emails = credentials.get("emails")
            if isinstance(emails, list):
                for item in emails:
                    value = item.get("value") if isinstance(item, dict) else None
                    if isinstance(value, str) and value.strip():
                        return value
            return None

        known_profile_fields = {
            "firstName",
            "lastName",
            "email",
            "login",
            "secondEmail",
            "second_email",
            "mobilePhone",
            "mobile_phone",
            "primaryPhone",
            "phone",
            "workPhone",
            "company",
            "organization",
            "department",
            "title",
            "comment",
            "notes",
            "description",
            "preferredLocale",
            "locale",
            "preferredLanguage",
            "samAccountName",
            "samaccountname",
            "userPrincipalName",
            "userprincipalname",
            "streetAddress",
            "address",
            "postalAddress",
            "city",
            "state",
            "stateCode",
            "region",
            "zipCode",
            "postalCode",
            "zip",
            "country",
            "countryCode",
            "country_code",
            "displayName",
            "display_name",
            "employeeNumber",
            "employee_number",
        }

        # Standard identity and contact information supported by OneLogin's API
        email = first_value(
            profile.get("email"),
            email_from_credentials(),
            profile.get("secondEmail"),
            profile.get("login"),
        )
        username = first_value(profile.get("login"), email)

        login_value = profile.get("login")
        samaccountname = first_value(
            profile.get("samAccountName"),
            profile.get("samaccountname"),
            (
                login_value.split("@")[0]
                if isinstance(login_value, str) and "@" in login_value
                else login_value
            ),
        )
        userprincipalname = first_value(
            profile.get("userPrincipalName"),
            profile.get("userprincipalname"),
            email,
            login_value,
        )

        transformed: dict[str, Any] = {
            "firstname": profile.get("firstName"),
            "lastname": profile.get("lastName"),
            "email": email,
            "username": username,
            "mobile_phone": first_value(profile.get("mobilePhone"), profile.get("mobile_phone")),
            "phone": first_value(
                profile.get("primaryPhone"),
                profile.get("phone"),
                profile.get("workPhone"),
            ),
            "company": first_value(profile.get("company"), profile.get("organization")),
            "department": profile.get("department"),
            "title": profile.get("title"),
            "comment": first_value(
                profile.get("comment"),
                profile.get("notes"),
                profile.get("description"),
            ),
            "preferred_locale_code": first_value(
                profile.get("locale"),
                profile.get("preferredLocale"),
                profile.get("preferredLanguage"),
            ),
            "samaccountname": samaccountname,
            "userprincipalname": userprincipalname,
            # Account state: 1 active, 0 inactive in OneLogin
            "state": 1 if (user.get("status") or "").upper() == "ACTIVE" else 0,
            "status": 1 if (user.get("status") or "").upper() == "ACTIVE" else 0,
            "external_id": str(user.get("id")) if user.get("id") is not None else None,
        }

        custom_attributes: dict[str, Any] = {}

        def add_custom_attribute(name: str, *profile_keys: str) -> None:
            value = first_value(*(profile.get(key) for key in profile_keys))
            if value is None:
                return
            if isinstance(value, str) and value.strip() == "":
                return
            custom_attributes[name] = value
            known_profile_fields.update(profile_keys)

        add_custom_attribute("second_email", "secondEmail", "second_email")
        add_custom_attribute(
            "street_address",
            "streetAddress",
            "address",
            "postalAddress",
        )
        add_custom_attribute("city", "city")
        add_custom_attribute("state", "state", "stateCode", "region")
        add_custom_attribute("zip_code", "zipCode", "postalCode", "zip")
        add_custom_attribute("country", "country")
        add_custom_attribute("country_code", "countryCode", "country_code")
        add_custom_attribute("display_name", "displayName", "display_name")
        add_custom_attribute("employee_number", "employeeNumber", "employee_number")

        dynamic_custom_attributes: dict[str, Any] = {}
        for key, raw_value in profile.items():
            if key in known_profile_fields:
                continue
            if raw_value is None:
                continue
            if isinstance(raw_value, (dict, list)):
                continue
            if isinstance(raw_value, str):
                if raw_value.strip() == "":
                    continue
                value = raw_value
            elif isinstance(raw_value, (int, float, bool)):
                value = str(raw_value)
            else:
                value = str(raw_value).strip()
                if not value:
                    continue
            normalized_name = self._normalize_custom_attribute_name(key)
            if not normalized_name:
                continue
            if normalized_name in transformed or normalized_name in custom_attributes:
                continue
            dynamic_custom_attributes[normalized_name] = value

        if dynamic_custom_attributes:
            custom_attributes.update(dynamic_custom_attributes)

        if custom_attributes:
            transformed["custom_attributes"] = custom_attributes

        cleaned = self._clean_payload(transformed)
        if not cleaned:
            LOGGER.debug(
                "User %s resulted in empty payload after cleaning. Original had %d fields.",
                user.get("id"),
                len(transformed),
            )
        return cleaned

    def _transform_group(self, group: dict[str, Any]) -> dict[str, Any] | None:
        profile = group.get("profile") or {}
        name = profile.get("name") or group.get("label")
        if not name:
            return None

        # Ensure name is a string and trim whitespace
        name = str(name).strip()
        if not name:
            LOGGER.warning("Skipping group with empty name after trimming: %s", group)
            return None

        # OneLogin may have length limits; log if name is unusually long
        if len(name) > 255:
            LOGGER.warning(
                "Group name is very long (%d chars), may cause issues: %s",
                len(name),
                name[:100] + "...",
            )

        return {"name": name}

    def _transform_application(self, app: dict[str, Any]) -> dict[str, Any] | None:
        label = app.get("label") or app.get("name")
        if not label:
            return None
        settings = app.get("settings") or {}
        sign_on = app.get("signOnMode")
        connector_id = self._lookup_onelogin_connector_id(app)
        if connector_id is None:
            LOGGER.warning(
                "Skipping application %s; no OneLogin connector mapping for signOnMode=%s",
                label,
                sign_on,
            )
            return None
        configuration = self._build_application_configuration(settings)
        visible = self._coerce_bool(settings.get("appVisible"), default=True)
        payload: dict[str, Any] = {
            "name": label,
            "connector_id": connector_id,
            "description": settings.get("appNotes"),
            "visible": visible,
            "configuration": configuration,
        }
        if sign_on:
            payload["signon_mode"] = sign_on

        # Build and add parameters if configuration enables it
        if self.settings.pass_app_parameters:
            # Query connector DB to check if connector supports custom parameters
            allows_new_parameters = False
            try:
                connector_info = self._connector_db.get_onelogin_connector(connector_id)
                if connector_info:
                    allows_new_parameters = bool(connector_info.get("allows_new_parameters", False))
            except Exception as e:
                LOGGER.debug(
                    "Failed to check allows_new_parameters for connector %d: %s",
                    connector_id,
                    e,
                )

            # Build parameters from Okta app data
            parameters = self._build_application_parameters(app, sign_on, allows_new_parameters)
            if parameters:
                payload["parameters"] = parameters
                LOGGER.info(
                    "Built %d parameters for app '%s' (connector_id=%d, allows_new_parameters=%s)",
                    len(parameters),
                    label,
                    connector_id,
                    allows_new_parameters,
                )
        # Legacy: preserve existing parameters if present in app object
        elif "parameters" in app:
            payload["parameters"] = app["parameters"]

        return self._clean_payload(payload)

    def _build_application_connector_lookup(self) -> dict[str, dict[str | None, int]]:
        mapping: dict[str, dict[str | None, int]] = {}

        def merge(source: dict[str, Any]) -> None:
            for raw_label, connector_data in source.items():
                label = self._normalize_app_label(raw_label)
                if not label:
                    continue
                target = mapping.setdefault(label, {})
                if isinstance(connector_data, dict):
                    for raw_mode, connector_id in connector_data.items():
                        mode = self._normalize_signon_mode(raw_mode)
                        if connector_id is None:
                            continue
                        try:
                            target[mode] = int(connector_id)
                        except (TypeError, ValueError):
                            continue
                elif connector_data is not None:
                    try:
                        target[None] = int(connector_data)
                    except (TypeError, ValueError):
                        continue

        merge(DEFAULT_APPLICATION_CONNECTORS)
        metadata_connectors = self.settings.metadata.get("application_connectors")
        if isinstance(metadata_connectors, dict):
            merge(metadata_connectors)
        return mapping

    def _lookup_onelogin_connector_id(self, app: dict[str, Any]) -> int | None:
        """Look up OneLogin connector ID for an Okta application.

        Priority order:
        1. User-approved overrides from database (user_connector_overrides table)
        2. Current session selection from analysis (app["_migration"]["selection"])
        3. Database automatic matching with confidence scores
        4. Static configuration fallback

        Args:
            app: Okta application object

        Returns:
            OneLogin connector ID or None if no mapping found
        """
        sign_on = self._normalize_signon_mode(app.get("signOnMode"))
        labels: list[str] = []
        for key in ("label", "name"):
            candidate = self._normalize_app_label(app.get(key))
            if candidate:
                labels.append(candidate)
        settings = app.get("settings")
        if isinstance(settings, dict):
            for key in ("appName", "displayName", "name"):
                candidate = self._normalize_app_label(settings.get(key))
                if candidate:
                    labels.append(candidate)

        # PRIORITY 1: Check user-approved overrides from database
        for label in labels:
            try:
                user_override = self._user_db.get_user_override(label)
                if user_override:
                    connector_id = user_override["preferred_onelogin_id"]
                    LOGGER.info(
                        "Using user-approved connector override for '%s': %d",
                        label,
                        connector_id,
                    )
                    # Log connector decision with user_override match type
                    self._telemetry.log_connector_decision(
                        migration_run_id=self._migration_run_id,
                        okta_connector_name=label,
                        suggested_onelogin_id=connector_id,
                        actual_onelogin_id=connector_id,
                        confidence_score=100.0,  # User-approved = 100% confidence
                        match_type="user_override",
                    )
                    return connector_id
            except Exception as e:
                LOGGER.debug(
                    "Failed to check user override for '%s': %s",
                    label,
                    e,
                )

        # PRIORITY 2: Check current session selection from analysis
        migration_meta = app.get("_migration") or {}
        selection = migration_meta.get("selection") or {}
        if selection.get("type") == "connector":
            connector_id = selection.get("id")
            if connector_id:
                LOGGER.info(
                    "Using connector from current session selection: %d (name: %s)",
                    connector_id,
                    selection.get("name", "Unknown"),
                )
                # Log connector decision
                self._telemetry.log_connector_decision(
                    migration_run_id=self._migration_run_id,
                    okta_connector_name=labels[0] if labels else "unknown",
                    suggested_onelogin_id=connector_id,
                    actual_onelogin_id=connector_id,
                    confidence_score=migration_meta.get("confidence_score", 100.0),
                    match_type="session_selection",
                )
                return connector_id

        # PRIORITY 3: Try database lookup (intelligent matching with confidence scores)
        for label in labels:
            try:
                mapping = self._connector_db.get_best_mapping(label)
                if mapping:
                    connector_id = mapping["onelogin_id"]
                    confidence = mapping["confidence_score"]
                    match_type = mapping["match_type"]

                    # Log connector decision for telemetry
                    self._telemetry.log_connector_decision(
                        migration_run_id=self._migration_run_id,
                        okta_connector_name=label,
                        suggested_onelogin_id=connector_id,
                        actual_onelogin_id=connector_id,  # User accepted suggestion
                        confidence_score=confidence,
                        match_type=match_type,
                    )

                    # Warn on fuzzy matches
                    if confidence < 90:
                        LOGGER.warning(
                            "Fuzzy connector match for '%s': %s (%.1f%% confidence)",
                            label,
                            mapping.get("onelogin_name"),
                            confidence,
                        )
                    else:
                        LOGGER.debug(
                            "Connector match for '%s': %s (%s, %.1f%% confidence)",
                            label,
                            mapping.get("onelogin_name"),
                            match_type,
                            confidence,
                        )

                    return connector_id
            except Exception as e:
                # Database lookup failed, fall back to static
                LOGGER.debug(
                    "Database connector lookup failed for '%s', using fallback: %s",
                    label,
                    e,
                )

        # PRIORITY 4: Fallback to static configuration (legacy compatibility)
        for label in labels:
            connectors = self._application_connector_lookup.get(label)
            if not connectors:
                continue
            if sign_on in connectors:
                return connectors[sign_on]
            if None in connectors:
                return connectors[None]

        return None

    @staticmethod
    def _build_application_configuration(settings: dict[str, Any]) -> dict[str, Any]:
        configuration: dict[str, Any] = {}
        if not isinstance(settings, dict):
            return configuration

        # Okta-specific SAML fields that OneLogin doesn't accept
        OKTA_SPECIFIC_FIELDS = {
            "attributeStatements",
            "configuredAttributeStatements",
            "audienceOverride",
            "destinationOverride",
            "recipientOverride",
            "ssoAcsUrlOverride",
            "honorForceAuthn",
            "defaultRelayState",
        }

        for key in ("appSettingsJson", "settingsJson", "signOn"):
            value = settings.get(key)
            if isinstance(value, dict):
                # Filter out Okta-specific fields and null values
                filtered = {
                    k: v
                    for k, v in value.items()
                    if k not in OKTA_SPECIFIC_FIELDS and v is not None
                }
                configuration.update(filtered)
        url = settings.get("appUrl") or settings.get("url")
        if isinstance(url, str) and url.strip() and "url" not in configuration:
            configuration["url"] = url
        return configuration

    @staticmethod
    def _build_application_parameters(
        app: dict[str, Any],
        sign_on_mode: str | None,
        allows_new_parameters: bool,
    ) -> dict[str, Any]:
        """Build application parameters for OneLogin from Okta app data.

        Extracts relevant configuration parameters based on app type (SAML, OIDC, etc.)
        and filters out provider-specific (Okta-specific) fields that won't work on OneLogin.

        Args:
            app: Okta application object
            sign_on_mode: Normalized signOnMode (e.g., "SAML_2_0", "OPENID_CONNECT")
            allows_new_parameters: Whether the OneLogin connector supports custom parameters

        Returns:
            Dictionary of parameters to pass to OneLogin app creation API
        """
        if not allows_new_parameters:
            # Connector doesn't support custom parameters - return empty dict
            return {}

        parameters: dict[str, Any] = {}
        settings = app.get("settings") or {}

        # Normalize sign_on_mode for comparison
        sign_on_upper = (sign_on_mode or "").upper()

        # ============================================================
        # SAML Parameter Extraction
        # ============================================================
        if "SAML" in sign_on_upper:
            # Extract from settings.signOn (SAML configuration)
            sign_on_config = settings.get("signOn") or {}

            # ACS URL (Assertion Consumer Service)
            acs_url = sign_on_config.get("acsUrl") or sign_on_config.get(
                "assertionConsumerServiceUrl"
            )
            if acs_url:
                parameters["acs_url"] = acs_url

            # Entity ID (SP Entity ID)
            entity_id = (
                sign_on_config.get("audienceUri")
                or sign_on_config.get("audience")
                or sign_on_config.get("entityId")
            )
            if entity_id:
                parameters["entity_id"] = entity_id

            # NameID Format
            name_id_format = sign_on_config.get("defaultRelayState") or sign_on_config.get(
                "subjectNameIdFormat"
            )
            if name_id_format:
                parameters["name_id_format"] = name_id_format

            # Single Logout URL
            slo_url = sign_on_config.get("sloUrl") or sign_on_config.get("singleLogoutUrl")
            if slo_url:
                parameters["slo_url"] = slo_url

            # Signature Algorithm
            signature_algorithm = sign_on_config.get("signatureAlgorithm")
            if signature_algorithm:
                parameters["signature_algorithm"] = signature_algorithm

            # Attribute Statements (SAML attributes)
            attribute_statements = sign_on_config.get("attributeStatements")
            if isinstance(attribute_statements, list) and attribute_statements:
                # Convert Okta attribute statements to OneLogin format
                saml_attributes = []
                for stmt in attribute_statements:
                    if isinstance(stmt, dict):
                        attr_name = stmt.get("name")
                        attr_values = stmt.get("values")
                        if attr_name:
                            saml_attributes.append(
                                {
                                    "name": attr_name,
                                    "values": (
                                        attr_values
                                        if isinstance(attr_values, list)
                                        else [attr_values]
                                    ),
                                }
                            )
                if saml_attributes:
                    parameters["saml_attributes"] = saml_attributes

        # ============================================================
        # OIDC/OAuth Parameter Extraction
        # ============================================================
        elif (
            "OPENID_CONNECT" in sign_on_upper or "OIDC" in sign_on_upper or "OAUTH" in sign_on_upper
        ):
            # Extract from settings.oauthClient (OIDC configuration)
            oauth_config = settings.get("oauthClient") or {}

            # Redirect URIs
            redirect_uris = oauth_config.get("redirect_uris") or oauth_config.get("redirectUris")
            if isinstance(redirect_uris, list) and redirect_uris:
                parameters["redirect_uris"] = redirect_uris
            elif isinstance(redirect_uris, str):
                parameters["redirect_uris"] = [redirect_uris]

            # Post Logout Redirect URIs
            post_logout_uris = oauth_config.get("post_logout_redirect_uris") or oauth_config.get(
                "postLogoutRedirectUris"
            )
            if isinstance(post_logout_uris, list) and post_logout_uris:
                parameters["post_logout_redirect_uris"] = post_logout_uris
            elif isinstance(post_logout_uris, str):
                parameters["post_logout_redirect_uris"] = [post_logout_uris]

            # Grant Types
            grant_types = oauth_config.get("grant_types") or oauth_config.get("grantTypes")
            if isinstance(grant_types, list) and grant_types:
                parameters["grant_types"] = grant_types
            elif isinstance(grant_types, str):
                parameters["grant_types"] = [grant_types]

            # Response Types
            response_types = oauth_config.get("response_types") or oauth_config.get("responseTypes")
            if isinstance(response_types, list) and response_types:
                parameters["response_types"] = response_types
            elif isinstance(response_types, str):
                parameters["response_types"] = [response_types]

            # Application Type (web, native, spa)
            application_type = oauth_config.get("application_type") or oauth_config.get(
                "applicationType"
            )
            if application_type:
                parameters["application_type"] = application_type

            # Token Endpoint Auth Method
            token_endpoint_auth = oauth_config.get(
                "token_endpoint_auth_method"
            ) or oauth_config.get("tokenEndpointAuthMethod")
            if token_endpoint_auth:
                parameters["token_endpoint_auth_method"] = token_endpoint_auth

        # ============================================================
        # Generic App Metadata (All App Types)
        # ============================================================

        # Login URL
        login_url = settings.get("loginUrl") or settings.get("appUrl") or settings.get("url")
        if login_url and "url" not in parameters:
            parameters["login_url"] = login_url

        # Icon/Logo URL
        icon_url = app.get("logo")
        if not icon_url:
            # Try to extract from _links (handle both dict and other types)
            links = app.get("_links")
            if isinstance(links, dict):
                logo_link = links.get("logo")
                if isinstance(logo_link, dict):
                    icon_url = logo_link.get("href")
        if icon_url:
            parameters["icon_url"] = icon_url

        # Help/Documentation URL
        help_url = settings.get("helpUrl") or settings.get("manualUpdateUrl")
        if help_url:
            parameters["help_url"] = help_url

        # Notes (additional description)
        notes = settings.get("notes") or settings.get("appNotes")
        if notes:
            parameters["notes"] = notes

        # ============================================================
        # User Attribute Mappings
        # ============================================================

        # Extract profile mappings if available
        profile = app.get("profile")
        if isinstance(profile, dict) and profile:
            # Common user attribute mappings
            user_mappings = {}

            # Map common attributes
            common_mappings = {
                "email": "email",
                "firstName": "first_name",
                "lastName": "last_name",
                "login": "username",
                "displayName": "display_name",
                "phoneNumber": "phone",
                "mobilePhone": "mobile_phone",
                "streetAddress": "street_address",
                "city": "city",
                "state": "state",
                "zipCode": "zip_code",
                "countryCode": "country",
                "department": "department",
                "title": "title",
                "employeeNumber": "employee_id",
                "manager": "manager",
            }

            for okta_key, onelogin_key in common_mappings.items():
                value = profile.get(okta_key)
                if value is not None:
                    user_mappings[onelogin_key] = value

            # Add custom profile attributes (exclude Okta-specific ones)
            for key, value in profile.items():
                if key not in common_mappings and not key.startswith("okta_"):
                    # Custom attribute - include it
                    user_mappings[f"custom_{key}"] = value

            if user_mappings:
                parameters["user_mappings"] = user_mappings

        # ============================================================
        # Filter Out Okta-Specific Provider Fields
        # ============================================================

        # Blacklist of Okta-specific fields that won't work on OneLogin
        okta_specific_keys = {
            "oktaInstanceUrl",
            "oktaApplicationUsersUrl",
            "oktaDomain",
            "oktaGroupsUrl",
            "oktaLogoUrl",
            "oktaWidgetVersion",
            "oktaAuthenticationPolicy",
            "oktaIdpId",
            "oktaSignOnPolicyId",
            "oktaPasswordPolicy",
            "okta_sign_on_policy",
            "okta_mfa_policy",
        }

        # Remove any Okta-specific keys
        parameters = {
            k: v
            for k, v in parameters.items()
            if not any(okta_key.lower() in k.lower() for okta_key in okta_specific_keys)
        }

        # Remove empty values to keep payload clean
        parameters = {k: v for k, v in parameters.items() if v not in (None, "", [], {})}

        return parameters

    @staticmethod
    def _coerce_bool(value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
            return default
        return bool(value)

    @staticmethod
    def _normalize_app_label(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        normalized = re.sub(r"\s+", " ", value).strip().lower()
        return normalized

    @staticmethod
    def _normalize_signon_mode(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        normalized = str(value).strip().lower()
        return normalized or None

    @staticmethod
    def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Recursively remove keys with None or empty-string values to avoid 422 validation errors."""
        cleaned: dict[str, Any] = {}
        for k, v in payload.items():
            if v is None:
                continue
            if isinstance(v, str) and v.strip() == "":
                continue
            # Recursively clean nested dictionaries
            if isinstance(v, dict):
                cleaned_nested = MigrationManager._clean_payload(v)
                # Only include if the cleaned dict is not empty
                if cleaned_nested:
                    cleaned[k] = cleaned_nested
            # Recursively clean lists containing dictionaries
            elif isinstance(v, list):
                cleaned_list = []
                for item in v:
                    if isinstance(item, dict):
                        cleaned_item = MigrationManager._clean_payload(item)
                        if cleaned_item:
                            cleaned_list.append(cleaned_item)
                    elif item is not None:
                        cleaned_list.append(item)
                # Only include if the cleaned list is not empty
                if cleaned_list:
                    cleaned[k] = cleaned_list
            else:
                cleaned[k] = v
        return cleaned

    def _source_label(self) -> str:
        return getattr(self.settings.source, "source_label", "source")

    def _prepare_one_login_roles(self) -> dict[str, dict[str, Any]]:
        """Load existing OneLogin roles keyed by normalized name."""
        if self.dry_run:
            LOGGER.info("Dry-run enabled; skipping OneLogin role fetch.")
            return {}
        try:
            existing_roles = self.onelogin.list_roles()
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.warning("Unable to enumerate existing OneLogin roles: %s", exc)
            return {}

        role_map: dict[str, dict[str, Any]] = {}
        for role in existing_roles:
            if not isinstance(role, dict):
                continue
            name = role.get("name")
            normalized = self._normalize_role_name(name)
            role_id = role.get("id")
            if not normalized or role_id is None:
                continue
            role_map[normalized] = role
        LOGGER.info("Loaded %d existing OneLogin roles for reuse.", len(role_map))
        return role_map

    @staticmethod
    def _normalize_custom_attribute_name(source_key: str) -> str:
        if not isinstance(source_key, str):
            return ""
        name = source_key.strip()
        if not name:
            return ""
        name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
        name = re.sub(r"[^0-9A-Za-z]+", "_", name)
        name = name.strip("_").lower()
        if not name:
            return ""
        if name[0].isdigit():
            name = f"_{name}"
        return name[:64]

    @staticmethod
    def _normalize_role_name(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", " ", value).strip().lower()

    def _assign_roles_to_application(
        self,
        okta_app: dict[str, Any],
        onelogin_app: dict[str, Any],
        role_lookup: dict[str, int],
    ) -> None:
        role_ids = self._roles_for_app(okta_app, role_lookup)
        app_id = onelogin_app.get("id")
        if not role_ids or not app_id:
            return
        for role_id in role_ids:
            try:
                self.onelogin.assign_role_to_app(int(app_id), role_id)
            except Exception as exc:  # pragma: no cover - best effort logging
                LOGGER.exception("Failed to assign role %s to app %s: %s", role_id, app_id, exc)

    def _roles_for_app(
        self, okta_app: dict[str, Any], role_lookup: dict[str, int]
    ) -> Iterable[int]:
        assignments = okta_app.get("_embedded", {}).get("group", [])
        seen: set[str] = set()
        for group in assignments or []:
            okta_identifier = group.get("id") or group.get("groupId")
            if okta_identifier is None:
                continue
            okta_id = str(okta_identifier)
            if okta_id in seen:
                continue
            seen.add(okta_id)
            role_id = role_lookup.get(okta_id)
            if role_id:
                yield role_id

    # ------------------------------------------------------------------
    # Custom attribute discovery and provisioning
    # ------------------------------------------------------------------
    def discover_custom_attributes(self, users: list[dict[str, Any]]) -> set[str]:
        """Analyze Okta users and discover all custom attributes that would be created.

        Returns a set of normalized custom attribute names that would be
        created in OneLogin during migration.
        """
        attributes: set[str] = set()

        # Known fields that map to standard OneLogin fields (not custom attributes)
        known_standard_fields = {
            "firstName",
            "lastName",
            "email",
            "login",
            "primaryPhone",
            "phone",
            "workPhone",
            "company",
            "organization",
            "department",
            "title",
            "comment",
            "notes",
            "description",
            "preferredLocale",
            "locale",
            "preferredLanguage",
            "samAccountName",
            "samaccountname",
            "userPrincipalName",
            "userprincipalname",
            "mobilePhone",
            "mobile_phone",
        }

        # Fields that become custom attributes (handled explicitly)
        explicit_custom_fields = {
            "secondEmail",
            "second_email",
            "streetAddress",
            "address",
            "postalAddress",
            "city",
            "state",
            "stateCode",
            "region",
            "zipCode",
            "postalCode",
            "zip",
            "country",
            "countryCode",
            "country_code",
            "displayName",
            "display_name",
            "employeeNumber",
            "employee_number",
        }

        for user in users:
            if not isinstance(user, dict):
                continue

            profile = user.get("profile")
            if not isinstance(profile, dict):
                continue

            # Process explicit custom attributes
            for field in explicit_custom_fields:
                value = profile.get(field)
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue

                # Normalize the field name
                if field == "secondEmail" or field == "second_email":
                    attributes.add("second_email")
                elif field in ("streetAddress", "address", "postalAddress"):
                    attributes.add("street_address")
                elif field == "city":
                    attributes.add("city")
                elif field in ("state", "stateCode", "region"):
                    attributes.add("state")
                elif field in ("zipCode", "postalCode", "zip"):
                    attributes.add("zip_code")
                elif field == "country":
                    attributes.add("country")
                elif field in ("countryCode", "country_code"):
                    attributes.add("country_code")
                elif field in ("displayName", "display_name"):
                    attributes.add("display_name")
                elif field in ("employeeNumber", "employee_number"):
                    attributes.add("employee_number")

            # Process dynamic custom attributes (fields not in known sets)
            for key, value in profile.items():
                # Skip known standard fields
                if key in known_standard_fields:
                    continue

                # Skip explicit custom fields (already handled above)
                if key in explicit_custom_fields:
                    continue

                # Skip empty/null values
                if value is None:
                    continue

                # Skip complex types
                if isinstance(value, (dict, list)):
                    continue

                # Skip empty strings
                if isinstance(value, str) and not value.strip():
                    continue

                # Normalize the field name
                normalized = self._normalize_custom_attribute_name(key)
                if normalized:
                    attributes.add(normalized)

        return attributes

    def provision_custom_attributes(self, attributes: set[str]) -> dict[str, Any]:
        """Provision custom attributes in OneLogin.

        Args:
            attributes: Set of normalized attribute names to create

        Returns:
            Dictionary with lists of created, existing, and failed attributes:
            {
                "created": ["attr1", "attr2"],
                "existing": ["attr3"],
                "failed": {"attr4": "error message"}
            }
        """
        result = {
            "created": [],
            "existing": [],
            "failed": {},
        }

        if not attributes:
            return result

        # Load existing attributes from cache
        try:
            self.onelogin._load_custom_attribute_cache()
        except Exception as exc:
            LOGGER.warning("Unable to load existing custom attributes: %s", exc)

        for attr_name in sorted(attributes):
            # Check if already exists
            if attr_name in self.onelogin._custom_attribute_cache:
                result["existing"].append(attr_name)
                LOGGER.info("Custom attribute '%s' already exists", attr_name)
                continue

            # Create the attribute
            try:
                self.onelogin._create_custom_attribute(attr_name)
                result["created"].append(attr_name)
                LOGGER.info("Created custom attribute '%s'", attr_name)
            except Exception as exc:
                error_msg = str(exc)
                result["failed"][attr_name] = error_msg
                LOGGER.error("Failed to create custom attribute '%s': %s", attr_name, error_msg)

        return result

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------

    def _log_error_telemetry(
        self, error_category: str, component: str, exception: Exception | None = None
    ) -> None:
        """Log error pattern for telemetry (anonymized).

        Args:
            error_category: Exception class name (e.g., 'HTTPError', 'ValueError')
            component: Component where error occurred (e.g., 'user_migration', 'app_migration')
            exception: Optional exception object to extract HTTP status
        """
        try:
            http_status = None
            if exception and hasattr(exception, "response"):
                response = getattr(exception, "response", None)
                if response and hasattr(response, "status_code"):
                    http_status = response.status_code

            self._telemetry.log_error_pattern(
                migration_run_id=self._migration_run_id,
                error_category=error_category,
                component=component,
                http_status=http_status,
                retry_count=0,
                resolved=False,
            )
        except Exception as e:
            # Telemetry failures should never break migrations
            LOGGER.debug("Failed to log error telemetry (non-fatal): %s", e)

    def _log_migration_scenario_telemetry(
        self, export: dict[str, Any], duration_seconds: float, success: bool
    ) -> None:
        """Log migration scenario telemetry (anonymized, bucketed counts).

        Args:
            export: Export data with users, groups, apps
            duration_seconds: Migration duration in seconds
            success: Whether migration completed successfully
        """
        try:
            user_count = len(export.get("users", []))
            group_count = len(export.get("groups", []))
            app_count = len(export.get("applications", []))

            # Calculate success rate (simplified - assumes all succeeded if success=True)
            success_rate = 100.0 if success else 0.0

            self._telemetry.log_migration_scenario(
                migration_run_id=self._migration_run_id,
                user_count=user_count,
                group_count=group_count,
                app_count=app_count,
                duration_seconds=int(duration_seconds),
                success_rate=success_rate,
                dry_run=self.dry_run,
                concurrency_enabled=self._threading_enabled,
            )

            LOGGER.debug(
                "Logged migration scenario: users=%d, groups=%d, apps=%d, duration=%.1fs, success=%s",
                user_count,
                group_count,
                app_count,
                duration_seconds,
                success,
            )
        except Exception as e:
            # Telemetry failures should never break migrations
            LOGGER.debug("Failed to log scenario telemetry (non-fatal): %s", e)


__all__ = ["MigrationManager"]
