"""Import utilities for OneLogin."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

from .progress import MigrationProgress
from .state_manager import StateManager
from .transformers import FieldTransformer

LOGGER = logging.getLogger(__name__)


class MigrationAborted(RuntimeError):
    """Raised when a migration run is cancelled mid-flight."""

    pass


class OneLoginImporter:
    """Handles importing data into OneLogin."""

    def __init__(
        self,
        onelogin_client: Any,
        state_manager: StateManager,
        progress: MigrationProgress,
        stop_event: threading.Event,
        dry_run: bool,
        threading_enabled: bool,
        max_workers: int,
    ) -> None:
        """Initialize the importer.

        Args:
            onelogin_client: OneLogin API client instance
            state_manager: State persistence manager
            progress: Progress tracker
            stop_event: Event to signal stop request
            dry_run: Whether this is a dry run
            threading_enabled: Whether to use concurrent processing
            max_workers: Maximum number of worker threads
        """
        self.onelogin = onelogin_client
        self.state = state_manager
        self.progress = progress
        self._stop_event = stop_event
        self._stopped = False
        self.dry_run = dry_run
        self._threading_enabled = threading_enabled
        self._max_workers = max_workers

    def import_into_onelogin(
        self,
        export: dict[str, Any],
        categories: dict[str, bool],
        connector_lookup: dict[str, dict[str | None, int]],
    ) -> None:
        """Import data into OneLogin.

        Args:
            export: Exported data from Okta
            categories: Dictionary of category toggles
            connector_lookup: Application connector mapping
        """
        LOGGER.info("Beginning import into OneLogin (dry_run=%s)", self.dry_run)
        self._check_for_stop()

        # Initialize group and user lookups
        role_lookup: dict[str, int] = self.state.get_lookup_ids("groups")
        existing_roles_by_name: dict[str, dict[str, Any]] = {}
        user_lookup: dict[str, int] = self.state.get_lookup_ids("users")
        role_lock = threading.Lock()
        role_condition = threading.Condition(role_lock)
        pending_role_names: set[str] = set()
        user_lock = threading.Lock()

        # Process groups (becomes roles in OneLogin)
        if categories.get("groups", True):
            existing_roles_by_name = self._prepare_one_login_roles()

            roles_created_count = {"count": 0}

            def group_identifier(item: Any) -> str | None:
                return self._item_identifier("groups", item)

            def handle_group(item: Any, identifier: str | None) -> bool | None:
                payload = FieldTransformer.transform_group(item)
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
                            self.state.update_lookup("groups", identifier, assigned_lookup_id)
                        return True
                self._check_for_stop()
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
                            with role_condition:
                                roles_created_count["count"] += 1
                                if normalized_name:
                                    existing_roles_by_name[normalized_name] = {
                                        "id": numeric_id,
                                        "name": role_name,
                                    }
                                    pending_role_names.discard(normalized_name)
                                    role_condition.notify_all()
                                if identifier:
                                    role_lookup[identifier] = numeric_id
                            if identifier:
                                self.state.update_lookup("groups", identifier, numeric_id)
                    else:
                        LOGGER.warning(
                            "OneLogin role creation response missing 'id' for group %s; skipping lookup update.",
                            identifier or payload.get("name"),
                        )
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
                "Role creation complete. Total new roles created: %d",
                roles_created_count["count"],
            )

        # Process users
        if categories.get("users", True):

            def user_identifier(item: Any) -> str | None:
                return self._item_identifier("users", item)

            def handle_user(item: Any, identifier: str | None) -> bool | None:
                payload = FieldTransformer.transform_user(item)
                if not payload:
                    return True
                custom_attributes = payload.get("custom_attributes")
                if isinstance(custom_attributes, dict) and custom_attributes:
                    try:
                        self.onelogin.ensure_custom_attribute_definitions(custom_attributes)
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
                            self.state.update_lookup("users", identifier, numeric_id)
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

        # Process memberships (group-user assignments)
        if categories.get("groups", True) and categories.get("users", True):
            self._process_memberships(export, role_lookup, user_lookup)

        # Process applications
        if categories.get("applications", True):

            def app_identifier(item: Any) -> str | None:
                return self._item_identifier("applications", item)

            def handle_application(item: Any, identifier: str | None) -> bool | None:
                payload = FieldTransformer.transform_application(item, connector_lookup)
                if not payload:
                    return True
                self._check_for_stop()
                response = self.onelogin.ensure_application(payload)
                if response and isinstance(response, dict):
                    self._assign_roles_to_application(item, response, role_lookup)
                return True

            self._process_items(
                "applications",
                export.get("applications", []),
                app_identifier,
                handle_application,
            )

        LOGGER.info("Import into OneLogin complete")

    def _prepare_one_login_roles(self) -> dict[str, dict[str, Any]]:
        """Return existing OneLogin roles keyed by normalized name."""
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
    def _normalize_role_name(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", " ", value).strip().lower()

    def _process_memberships(
        self,
        export: dict[str, Any],
        role_lookup: dict[str, int],
        user_lookup: dict[str, int],
    ) -> None:
        """Process group memberships (assign users to roles)."""
        assign_bulk = getattr(self.onelogin, "assign_users_to_role_bulk", None)
        if not callable(assign_bulk):
            LOGGER.debug(
                "OneLogin client does not support bulk role assignment; skipping membership sync"
            )
            return

        completed_memberships = self.state.get_completed_memberships()
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
                    self.state.mark_membership(membership_key)

    def _assign_roles_to_application(
        self,
        okta_app: dict[str, Any],
        onelogin_app: dict[str, Any],
        role_lookup: dict[str, int],
    ) -> None:
        """Assign roles to an application."""
        role_ids = self._roles_for_app(okta_app, role_lookup)
        app_id = onelogin_app.get("id")
        if not role_ids or not app_id:
            return
        for role_id in role_ids:
            try:
                self.onelogin.assign_role_to_app(int(app_id), role_id)
            except Exception as exc:  # pragma: no cover - best effort logging
                LOGGER.exception("Failed to assign role %s to app %s: %s", role_id, app_id, exc)

    @staticmethod
    def _roles_for_app(okta_app: dict[str, Any], role_lookup: dict[str, int]) -> Iterable[int]:
        """Extract role IDs for an application."""
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

    def _process_items(
        self,
        category: str,
        items: Iterable[Any],
        identifier_fn: Callable[[Any], str | None],
        handler: Callable[[Any, str | None], bool | None],
    ) -> None:
        """Process a list of items with optional concurrent processing.

        Args:
            category: Category name (users, groups, applications, etc.)
            items: Items to process
            identifier_fn: Function to extract identifier from item
            handler: Function to handle each item
        """
        sequence = list(items) if not isinstance(items, list) else items  # type: ignore[assignment]
        if not sequence:
            return
        prepared = [(item, identifier_fn(item)) for item in sequence]

        pending: list[tuple[Any, str | None]] = []
        for item, identifier in prepared:
            if identifier and self.state.is_completed(category, identifier):
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
        """Process a single item."""
        self._check_for_stop()
        result = handler(item, identifier)
        if result is not False:
            self.state.mark_completed(category, identifier)
        self.progress.increment(category)

    @staticmethod
    def _item_identifier(category: str, item: Any) -> str | None:
        """Extract a unique identifier for an item."""
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
        """Create a unique identifier for a membership."""
        return f"{group_id}:{user_id}"

    def _check_for_stop(self) -> None:
        """Check if a stop has been requested and raise MigrationAborted if so."""
        if self._stop_event.is_set():
            self._stopped = True
            raise MigrationAborted()

    def was_stopped(self) -> bool:
        """Check if the importer was stopped."""
        return self._stopped


__all__ = ["OneLoginImporter", "MigrationAborted"]
