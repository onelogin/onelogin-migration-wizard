"""Analysis page for pre-migration environment inspection - REDESIGNED with tabs."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .. import WizardState

from onelogin_migration_core.clients import OktaClient, OneLoginClient
from onelogin_migration_core.config import OktaApiSettings, OneLoginApiSettings
from onelogin_migration_core.constants import KNOWN_STANDARD_FIELDS
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..dialogs import AnalysisDetailDialog
from ..styles.button_styles import ACTION_BUTTON_STYLE, DESTRUCTIVE_BUTTON_STYLE
from .base import BasePage

LOGGER = logging.getLogger(__name__)


class AnalysisWorker(QThread):
    """Background thread for running Okta environment analysis."""

    # Signals
    progress_update = Signal(str)  # Status message
    analysis_complete = Signal(dict)  # Analysis results
    analysis_error = Signal(str)  # Error message

    def __init__(self, okta_client: OktaClient, onelogin_client: OneLoginClient | None = None):
        super().__init__()
        self.okta_client = okta_client
        self.onelogin_client = onelogin_client
        self._cancelled = False

    def request_cancel(self):
        """Request cancellation of the analysis."""
        self._cancelled = True

    def run(self):
        """Run analysis in background thread."""
        try:
            if self._cancelled:
                return
            # Step 1: Connect to Okta
            self.progress_update.emit("Connecting to Okta...")

            # Step 2: Extract users
            self.progress_update.emit("Extracting users from Okta...")
            users = self.okta_client.list_users()

            # Step 3: Extract groups
            self.progress_update.emit("Extracting groups from Okta...")
            groups = self.okta_client.list_groups()

            # Step 4: Extract group memberships
            self.progress_update.emit("Extracting group memberships...")
            memberships = self.okta_client.list_group_memberships(groups)

            # Step 5: Extract applications
            self.progress_update.emit("Extracting applications from Okta...")
            applications = self.okta_client.list_applications()

            # Step 6: Extract policies
            self.progress_update.emit("Extracting policies from Okta...")
            policies = self.okta_client.list_policies()

            # Step 7: Extract MFA authenticators
            self.progress_update.emit("Extracting MFA configuration...")
            authenticators = self.okta_client.list_authenticators()

            # Step 8: Extract identity providers (directories)
            self.progress_update.emit("Extracting directory integrations...")
            identity_providers = self.okta_client.list_identity_providers()

            # Step 9: Extract group rules
            self.progress_update.emit("Extracting group rules...")
            group_rules = self.okta_client.list_group_rules()

            # Load OneLogin connectors from database (faster and offline-capable)
            connectors: list[dict[str, Any]] = []
            connector_error: str | None = None
            connector_stats: dict[str, int] = {"total": 0, "from_db": 0, "from_api": 0}

            try:
                from onelogin_migration_core.db import get_default_connector_db

                db = get_default_connector_db()

                self.progress_update.emit("Loading OneLogin connector catalog from database...")
                db_connectors = db.get_all_onelogin_connectors()

                if db_connectors:
                    # Use database connectors (preferred - fast and offline)
                    connectors = db_connectors
                    connector_stats["from_db"] = len(connectors)
                    connector_stats["total"] = len(connectors)
                    LOGGER.info(f"Loaded {len(connectors)} connectors from database")
                elif self.onelogin_client:
                    # Fallback to API if database is empty
                    self.progress_update.emit("Fetching OneLogin connector catalog from API...")
                    connectors = self.onelogin_client.list_connectors()
                    connector_stats["from_api"] = len(connectors)
                    connector_stats["total"] = len(connectors)
                    LOGGER.info(
                        f"Fetched {len(connectors)} connectors from API (database was empty)"
                    )
                else:
                    connector_error = "Provide OneLogin credentials on the Target Settings step to compare against the OneLogin connector catalog."
            except Exception as exc:
                connector_error = f"Failed to load connector catalog: {exc}"
                LOGGER.exception("Failed to load connectors from database or API")

            # Compile export data
            export = {
                "users": users,
                "groups": groups,
                "memberships": memberships,
                "applications": applications,
                "policies": policies,
                "authenticators": authenticators,
                "identity_providers": identity_providers,
                "group_rules": group_rules,
                "onelogin_connectors": connectors,
            }

            # Step 10: Analyze users
            self.progress_update.emit("Analyzing user data...")
            users_analysis = self._analyze_users(export.get("users", []))

            # Step 11: Analyze user security details
            self.progress_update.emit("Analyzing user security details...")
            user_security_analysis = self._analyze_user_security(export.get("users", []))

            # Step 12: Analyze groups
            self.progress_update.emit("Analyzing group data...")
            groups_analysis = self._analyze_groups(
                export.get("groups", []), export.get("memberships", [])
            )

            # Step 13: Analyze group assignments and rules
            self.progress_update.emit("Analyzing group assignments...")
            group_details_analysis = self._analyze_group_details(
                export.get("groups", []),
                export.get("applications", []),
                export.get("group_rules", []),
            )

            # Step 14: Analyze applications
            self.progress_update.emit("Categorizing applications...")
            apps_analysis = self._analyze_applications(
                export.get("applications", []),
                connectors,
            )

            # Step 15: Categorize application types
            self.progress_update.emit("Categorizing application types...")
            app_details_analysis = self._analyze_app_details(export.get("applications", []))

            # Step 16: Analyze policies
            self.progress_update.emit("Analyzing policies...")
            policy_analysis = self._analyze_policies(export.get("policies", []))

            # Step 17: Analyze MFA configuration
            self.progress_update.emit("Analyzing MFA configuration...")
            mfa_analysis = self._analyze_mfa(export.get("authenticators", []))

            # Step 18: Analyze directories
            self.progress_update.emit("Analyzing directories...")
            directory_analysis = self._analyze_directories(export.get("identity_providers", []))

            # Step 19: Compile results
            self.progress_update.emit("Finalizing analysis...")

            # Build discovery summary data
            discovery_data = {
                "summary": {
                    "users": len(users),
                    "admins": user_security_analysis.get("admins", 0),
                    "apps": len(applications),
                    "groups": len(groups),
                    "user_policies": policy_analysis.get("user_policies", {}).get("total", 0),
                    "app_policies": policy_analysis.get("app_policies", {}).get("total", 0),
                    "mfa": len(authenticators),
                    "directories": len(identity_providers),
                    "custom_attributes": len(users_analysis.get("custom_attributes", [])),
                },
                "users": user_security_analysis,
                "groups": group_details_analysis,
                "applications": app_details_analysis,
                "user_policies": policy_analysis.get("user_policies", {}),
                "app_policies": policy_analysis.get("app_policies", {}),
                "mfa": mfa_analysis,
                "directories": directory_analysis,
                "custom_attributes": {
                    "total": len(users_analysis.get("custom_attributes", [])),
                    "used": len(
                        users_analysis.get("custom_attributes", [])
                    ),  # All detected attrs are "used"
                    "unused": 0,
                },
            }

            results = {
                "timestamp": datetime.now().isoformat(),
                "source": self.okta_client.settings.domain,
                "users": users_analysis,
                "groups": groups_analysis,
                "applications": apps_analysis,
                "discovery": discovery_data,
                "raw_export": export,  # Save for later use
                "connectors": {
                    "total": connector_stats["total"],
                    "from_db": connector_stats["from_db"],
                    "from_api": connector_stats["from_api"],
                    "error": connector_error,
                },
            }
            if connectors:
                # Provide a small subset for quick display while keeping full list in raw export
                preview = [
                    {
                        "id": connector.get("id"),
                        "name": connector.get("name"),
                        "auth_method": connector.get("auth_method"),
                    }
                    for connector in connectors[:25]
                ]
                results["connectors"]["preview"] = preview

            self.progress_update.emit("Analysis complete!")
            self.analysis_complete.emit(results)

        except Exception as exc:
            LOGGER.exception("Analysis failed")
            self.analysis_error.emit(str(exc))
        finally:
            # Clean up HTTP session
            try:
                if hasattr(self.okta_client, "session"):
                    self.okta_client.session.close()
                if self.onelogin_client and hasattr(self.onelogin_client, "session"):
                    self.onelogin_client.session.close()
            except Exception:
                pass  # Best effort cleanup

    def _analyze_users(self, users: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze user data."""
        if not users:
            return {"total": 0, "active": 0, "suspended": 0, "custom_attributes": []}

        active = sum(1 for u in users if u.get("status") == "ACTIVE")
        suspended = sum(1 for u in users if u.get("status") == "SUSPENDED")

        # Detect custom attributes
        custom_attrs: set[str] = set()
        all_fields: set[str] = set()

        for user in users[:100]:
            profile = user.get("profile", {})
            for key in profile.keys():
                all_fields.add(key)
                if key not in KNOWN_STANDARD_FIELDS:
                    custom_attrs.add(key)

        LOGGER.info(f"Found {len(all_fields)} total profile fields")
        LOGGER.info(f"Detected {len(custom_attrs)} custom attributes")

        return {
            "total": len(users),
            "active": active,
            "suspended": suspended,
            "deprovisioned": len(users) - active - suspended,
            "custom_attributes": sorted(custom_attrs),
        }

    def _analyze_groups(
        self, groups: list[dict[str, Any]], memberships: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Analyze group data."""
        if not groups:
            return {"total": 0, "total_memberships": 0, "top_groups": []}

        # Count memberships per group
        membership_counts: dict[str, int] = {}
        for membership in memberships:
            group_id = membership.get("group_id") or membership.get("groupId")
            if group_id is None:
                continue
            key = str(group_id)
            membership_counts[key] = membership_counts.get(key, 0) + 1

        # Build top groups list
        groups_with_counts = []
        for group in groups:
            group_id = group.get("id")
            name = group.get("profile", {}).get("name", "Unknown")
            count = membership_counts.get(str(group_id), 0)
            groups_with_counts.append({"name": name, "members": count, "id": group_id})

        groups_with_counts.sort(key=lambda g: g["members"], reverse=True)

        return {
            "total": len(groups),
            "total_memberships": len(memberships),
            "top_groups": groups_with_counts[:10],
        }

    def _analyze_applications(
        self,
        applications: list[dict[str, Any]],
        connectors: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Analyze applications and categorize migration readiness."""
        if not applications:
            return {
                "total": 0,
                "can_migrate": [],
                "need_review": [],
                "cannot_migrate": [],
                "breakdown": {
                    "connector_matches": 0,
                    "custom_sso": 0,
                    "unsupported": 0,
                    "needs_review": 0,
                },
                "mapping_quality": {
                    "exact_matches": 0,
                    "fuzzy_matches": 0,
                    "no_matches": 0,
                },
            }

        # Build fallback lookup from API/DB connectors
        connector_lookup = self._build_connector_lookup(connectors or [])

        # Initialize database for intelligent matching
        try:
            from onelogin_migration_core.db import get_default_connector_db

            db = get_default_connector_db()
            use_db_matching = True
        except Exception as exc:
            LOGGER.warning(f"Database unavailable for matching, using fallback: {exc}")
            db = None
            use_db_matching = False

        can_migrate: list[dict[str, Any]] = []
        need_review: list[dict[str, Any]] = []
        cannot_migrate: list[dict[str, Any]] = []

        connector_matches = 0
        custom_sso = 0

        # Track mapping quality statistics
        exact_matches = 0
        fuzzy_matches = 0
        no_matches = 0

        for idx, app in enumerate(applications):
            label = app.get("label", "Unknown")
            sign_on = (app.get("signOnMode") or "").upper()
            status = app.get("status", "ACTIVE")

            app_info: dict[str, Any] = {
                "name": label,
                "sign_on_mode": sign_on,
                "status": status,
            }

            # Custom SAML/OIDC is available unless the app type explicitly doesn't support SSO
            # (e.g., bookmarks, password vaults, or truly unsupported modes)
            unsupported_for_custom_sso = sign_on in {
                "SECURE_PASSWORD_STORE",
                "BOOKMARK",
                None,
                "",  # Unknown or missing sign-on mode
            }
            supports_custom_sso = not unsupported_for_custom_sso

            migration_meta: dict[str, Any] = {
                "app_index": idx,
                "supports_custom_sso": supports_custom_sso,
                "matches": [],  # Will be populated with 90%+ confidence matches
            }

            confidence_score = 0.0
            match_type = "none"
            best_db_match: dict[str, Any] | None = None
            high_confidence_matches: list[dict[str, Any]] = []
            mapping_quality_bucket = "none"

            if use_db_matching and db:
                best_db_match, high_confidence_matches, _ = self._lookup_db_matches(db, app, label)
                if best_db_match:
                    confidence_score = best_db_match.get("confidence_score", 0.0) or 0.0
                    match_type = best_db_match.get("match_type", "unknown")
                    if confidence_score >= 99.5:
                        mapping_quality_bucket = "exact"
                    elif confidence_score >= 90.0:
                        mapping_quality_bucket = "fuzzy"
            else:
                best_db_match = None
                high_confidence_matches = []

            if mapping_quality_bucket == "exact":
                exact_matches += 1
            elif mapping_quality_bucket == "fuzzy":
                fuzzy_matches += 1
            else:
                no_matches += 1

            matches_list: list[dict[str, Any]] = []
            for match in high_confidence_matches:
                match_score = match.get("confidence_score", 0.0)
                connector_payload = {
                    "id": match.get("onelogin_id"),
                    "name": match.get("onelogin_name", "OneLogin Connector"),
                    "auth_method": match.get("auth_method"),
                }
                matches_list.append(
                    {
                        "connector": connector_payload,
                        "match_reason": "exact" if match_score >= 99.5 else "partial",
                        "confidence_score": match_score,
                    }
                )

            migration_meta["matches"] = matches_list

            has_connector_match = False
            if best_db_match and confidence_score >= 90.0:
                connector_id = best_db_match.get("onelogin_id")
                connector_name = best_db_match.get("onelogin_name", "OneLogin Connector")

                if confidence_score >= 99.5:
                    reason = f"Native OneLogin connector: {connector_name} (100% match)"
                else:
                    reason = (
                        f"OneLogin connector: {connector_name} "
                        f"({confidence_score:.0f}% similarity - review before migrating)"
                    )

                migration_meta.update(
                    {
                        "category": "connector",
                        "reason": reason,
                        "match_type": match_type,
                        "confidence_score": confidence_score,
                        "connector": {
                            "id": connector_id,
                            "name": connector_name,
                            "auth_method": best_db_match.get("auth_method"),
                        },
                        "matches": matches_list,
                    }
                )
            elif best_db_match:
                connector_name = best_db_match.get("onelogin_name", "OneLogin Connector")
                reason = (
                    f"Potential connector: {connector_name} "
                    f"({confidence_score:.0f}% confidence - manual validation recommended)"
                )
                migration_meta.update(
                    {
                        "category": "needs_review",
                        "reason": reason,
                        "match_type": match_type,
                        "confidence_score": confidence_score,
                        "matches": matches_list,
                    }
                )

            if best_db_match and confidence_score >= 90.0:
                connector_name = best_db_match.get("onelogin_name", "OneLogin Connector")
                app_info.update(
                    {
                        "reason": migration_meta.get("reason"),
                        "category": "connector",
                        "connector_name": connector_name,
                        "match_type": match_type,
                        "confidence_score": confidence_score,
                    }
                )

                connector_matches += 1
                has_connector_match = True
                if confidence_score >= 99.5:
                    can_migrate.append(app_info)
                else:
                    need_review.append(app_info)

            # Handle apps with no connector match but native SAML/OIDC support
            # Only include apps with true SAML_2_0 or OPENID_CONNECT sign-on modes
            if not has_connector_match and sign_on in {"SAML_2_0", "OPENID_CONNECT"}:
                settings = app.get("settings", {}) or {}
                app_settings = settings.get("appSettingsJson", {})
                assigned_groups = app.get("_embedded", {}).get("group", []) or []
                has_complex_config = (
                    isinstance(app_settings, dict) and len(app_settings) > 5
                ) or len(assigned_groups) > 10

                if has_complex_config:
                    reason = "Complex SAML/OpenID configuration detected"
                    migration_meta.update(
                        {
                            "category": "needs_review",
                            "reason": reason,
                        }
                    )
                    app_info.update(
                        {
                            "reason": reason,
                            "category": "needs_review",
                        }
                    )
                    need_review.append(app_info)
                else:
                    reason = "Use a custom SAML/OpenID connector in OneLogin"
                    migration_meta.update(
                        {
                            "category": "custom_saml",
                            "reason": reason,
                        }
                    )
                    app_info.update(
                        {
                            "reason": reason,
                            "category": "custom_saml",
                        }
                    )
                    can_migrate.append(app_info)
                    custom_sso += 1

            # Handle unsupported app types (only if no connector match)
            if not has_connector_match and sign_on in {"SECURE_PASSWORD_STORE", "BOOKMARK"}:
                reason = "Password-store or bookmark apps must be recreated manually"
                migration_meta.update(
                    {
                        "category": "unsupported",
                        "reason": reason,
                    }
                )
                app_info.update(
                    {
                        "reason": reason,
                        "category": "unsupported",
                    }
                )
                cannot_migrate.append(app_info)

            # Handle apps needing review (only if no connector match)
            if not has_connector_match and sign_on in {"AUTO_LOGIN", "BROWSER_PLUGIN"}:
                reason = "Auto-login workflows require manual validation"
                migration_meta.update(
                    {
                        "category": "needs_review",
                        "reason": reason,
                    }
                )
                app_info.update(
                    {
                        "reason": reason,
                        "category": "needs_review",
                    }
                )
                need_review.append(app_info)

            # Handle other sign-on modes that weren't already categorized
            # This catches modes like SWA, OAUTH, WS_FEDERATION, None, etc. that don't have native SAML/OIDC
            categorized_modes = {
                "SECURE_PASSWORD_STORE",
                "BOOKMARK",
                "AUTO_LOGIN",
                "BROWSER_PLUGIN",
                "SAML_2_0",
                "OPENID_CONNECT",
            }
            if not has_connector_match and sign_on not in categorized_modes:
                if sign_on in {None, ""}:
                    reason = "Unknown sign-on mode - manual migration required"
                else:
                    reason = f"Sign-on mode '{sign_on}' - manual migration required"
                migration_meta.update(
                    {
                        "category": "unsupported",
                        "reason": reason,
                    }
                )
                app_info.update(
                    {
                        "reason": reason,
                        "category": "unsupported",
                    }
                )
                cannot_migrate.append(app_info)

            if migration_meta:
                app["_migration"] = migration_meta

        # Mark duplicate applications that use the same connector
        self._mark_duplicate_apps(applications)

        breakdown = {
            "connector_matches": connector_matches,
            "custom_sso": custom_sso,
            "unsupported": len(cannot_migrate),
            "needs_review": len(need_review),
        }

        mapping_quality = {
            "exact_matches": exact_matches,
            "fuzzy_matches": fuzzy_matches,
            "no_matches": no_matches,
        }

        return {
            "total": len(applications),
            "can_migrate": can_migrate,
            "need_review": need_review,
            "cannot_migrate": cannot_migrate,
            "breakdown": breakdown,
            "mapping_quality": mapping_quality,
        }

    def _mark_duplicate_apps(self, applications: list[dict[str, Any]]) -> None:
        """
        Identify and mark applications that use the same connector.
        Duplicates are marked with metadata for UI display and selection logic.
        """
        # Group apps by connector ID
        connector_groups: dict[str, list[dict[str, Any]]] = {}

        for app in applications:
            migration_meta = app.get("_migration", {})

            # Only consider apps with a connector match
            if migration_meta.get("category") != "connector":
                continue

            connector = migration_meta.get("connector", {})
            connector_id = connector.get("id")

            if connector_id:
                connector_groups.setdefault(connector_id, []).append(app)

        # Process each group to identify duplicates
        for connector_id, apps_in_group in connector_groups.items():
            if len(apps_in_group) < 2:
                # Not a duplicate if only one app uses this connector
                continue

            # Count assigned groups as a proxy for active users
            # The app with more assigned groups is likely serving more users
            app_scores: list[tuple[dict[str, Any], int]] = []

            for app in apps_in_group:
                # Count assigned groups from _embedded.group
                embedded = app.get("_embedded", {}) or {}
                assigned_groups = embedded.get("group", []) or []
                group_count = len(assigned_groups) if isinstance(assigned_groups, list) else 0

                app_scores.append((app, group_count))

            # Sort by group count (descending) to find the most "popular" app
            app_scores.sort(key=lambda x: x[1], reverse=True)

            # Generate a unique group ID for this set of duplicates
            duplicate_group_id = f"dup_{connector_id}"

            # Mark each app in the duplicate group
            for idx, (app, group_count) in enumerate(app_scores):
                migration_meta = app.get("_migration", {})

                # The first app (highest group count) is preferred
                is_preferred = (idx == 0)

                migration_meta["is_duplicate"] = True
                migration_meta["duplicate_group_id"] = duplicate_group_id
                migration_meta["preferred_in_group"] = is_preferred
                migration_meta["assigned_groups_count"] = group_count

                LOGGER.info(
                    "Marked app '%s' (ID: %s) as duplicate in group '%s' (preferred: %s, groups: %d)",
                    app.get("label", "Unknown"),
                    app.get("id", "?"),
                    duplicate_group_id,
                    is_preferred,
                    group_count,
                )

    @staticmethod
    def _normalize_app_name(value: str) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def _generate_name_variants(self, value: str | None) -> set[str]:
        variants: set[str] = set()
        if not value or not isinstance(value, str):
            return variants

        candidates = {value}
        cleaned = value.replace("®", " ").replace("™", " ")
        candidates.add(cleaned)

        if "(" in cleaned:
            candidates.add(cleaned.split("(")[0])
        if " - " in cleaned:
            parts = cleaned.split(" - ")
            candidates.update(parts)
        if " | " in cleaned:
            candidates.update(cleaned.split(" | "))

        for candidate in candidates:
            normalized = self._normalize_app_name(candidate.strip())
            if normalized:
                variants.add(normalized)
        return variants

    def _build_connector_lookup(
        self, connectors: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        lookup: dict[str, list[dict[str, Any]]] = {}
        for connector in connectors:
            names: set[str] = set()
            for key in ("name", "display_name", "description"):
                names.update(self._generate_name_variants(connector.get(key)))
            for alias in names:
                lookup.setdefault(alias, []).append(connector)
        return lookup

    def _collect_db_lookup_keys(self, app: dict[str, Any]) -> list[str]:
        """Gather potential lookup keys for connector database matching."""
        candidates: list[str] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            if not value or not isinstance(value, str):
                return
            raw = value.strip()
            if not raw:
                return
            for variant in {raw, raw.lower()}:
                if not variant or variant in seen:
                    continue
                seen.add(variant)
                candidates.append(variant)

        add(app.get("name"))
        add(app.get("label"))

        settings = app.get("settings", {}) or {}
        if isinstance(settings, dict):
            add(settings.get("appName"))
            add(settings.get("name"))
            add(settings.get("label"))
            app_settings = settings.get("appSettingsJson", {})
            if isinstance(app_settings, dict):
                add(app_settings.get("appName"))
                add(app_settings.get("label"))

        profile = app.get("profile") or {}
        if isinstance(profile, dict):
            add(profile.get("name"))

        # Include normalized variants without special characters for internal connector names
        normalized_candidates = list(candidates)
        for candidate in normalized_candidates:
            normalized = self._normalize_app_name(candidate)
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)

        return candidates

    @staticmethod
    def _normalize_db_match(match: dict[str, Any]) -> dict[str, Any]:
        """Return a sanitized copy of a connector DB match with numeric confidence."""
        result = dict(match)
        score = result.get("confidence_score", 0.0)
        try:
            result["confidence_score"] = float(score)
        except (TypeError, ValueError):
            result["confidence_score"] = 0.0
        return result

    def _lookup_db_matches(
        self,
        db: Any,
        app: dict[str, Any],
        label: str,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
        """Return the best connector match along with high-confidence options."""
        if db is None:
            return None, [], []

        lookup_keys = self._collect_db_lookup_keys(app)
        matches: list[dict[str, Any]] = []
        seen_internal: set[str] = set()

        for key in lookup_keys:
            if not key:
                continue
            try:
                key_matches = db.get_all_mappings(key)
            except Exception as exc:  # pragma: no cover - defensive logging
                LOGGER.debug(f"Connector DB lookup failed for '{label}' via key '{key}': {exc}")
                continue
            if not key_matches:
                continue
            seen_internal.add(key)
            for match in key_matches:
                matches.append(self._normalize_db_match(match))

        if not matches:
            search_terms: set[str] = set()
            for candidate in lookup_keys:
                if candidate:
                    search_terms.add(candidate)
            if label:
                search_terms.add(label)

            settings = app.get("settings", {}) or {}
            if isinstance(settings, dict):
                display_name = settings.get("displayName")
                if display_name:
                    search_terms.add(display_name)

            for term in list(search_terms):
                term_str = term.strip()
                if not term_str:
                    continue
                try:
                    rows = db.search_okta_connectors(term_str, limit=5)
                except Exception as exc:  # pragma: no cover - defensive logging
                    LOGGER.debug(f"Connector catalog search failed for '{term_str}': {exc}")
                    continue
                for row in rows:
                    row_dict = dict(row)
                    internal_name = row_dict.get("internal_name")
                    if not internal_name or internal_name in seen_internal:
                        continue
                    seen_internal.add(internal_name)
                    try:
                        mapped = db.get_all_mappings_for_app(internal_name)
                    except Exception as exc:  # pragma: no cover - defensive logging
                        LOGGER.debug(f"Connector mapping fetch failed for '{internal_name}': {exc}")
                        continue
                    for match in mapped:
                        matches.append(self._normalize_db_match(match))

        if not matches:
            return None, [], []

        matches.sort(key=lambda m: m.get("confidence_score", 0.0), reverse=True)

        dedup: dict[Any, dict[str, Any]] = {}
        for match in matches:
            connector_id = match.get("onelogin_id")
            if connector_id is None:
                continue
            current = dedup.get(connector_id)
            if current is None or match.get("confidence_score", 0.0) > current.get(
                "confidence_score", 0.0
            ):
                dedup[connector_id] = match

        dedup_matches = sorted(
            dedup.values(), key=lambda m: m.get("confidence_score", 0.0), reverse=True
        )
        best_match = dedup_matches[0] if dedup_matches else None
        high_confidence = [
            match for match in dedup_matches if match.get("confidence_score", 0.0) >= 90.0
        ]

        return best_match, high_confidence, dedup_matches

    def _match_connectors(
        self,
        app: dict[str, Any],
        lookup: dict[str, list[dict[str, Any]]],
        connectors: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates: set[str] = set()
        for key in ("label", "name", "appName"):
            candidates.update(self._generate_name_variants(app.get(key)))
        profile = app.get("profile") or {}
        candidates.update(self._generate_name_variants(profile.get("name")))
        matched: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for variant in candidates:
            matches = lookup.get(variant)
            if not matches:
                continue
            for connector in matches:
                connector_id = str(connector.get("id")) if connector.get("id") is not None else None
                if connector_id and connector_id in seen_ids:
                    continue
                matched.append(
                    {
                        "connector": connector,
                        "match_reason": "exact",
                    }
                )
                if connector_id:
                    seen_ids.add(connector_id)
        if matched:
            return matched

        # Fallback to partial substring matching for similar names
        if not candidates:
            return matched
        for connector in connectors:
            connector_variants: set[str] = set()
            for key in ("name", "display_name", "description"):
                connector_variants.update(self._generate_name_variants(connector.get(key)))
            if not connector_variants:
                continue
            for variant in candidates:
                for conn_variant in connector_variants:
                    if (
                        variant
                        and conn_variant
                        and (variant in conn_variant or conn_variant in variant)
                    ):
                        connector_id = (
                            str(connector.get("id")) if connector.get("id") is not None else None
                        )
                        if connector_id and connector_id in seen_ids:
                            continue
                        matched.append(
                            {
                                "connector": connector,
                                "match_reason": "partial",
                            }
                        )
                        if connector_id:
                            seen_ids.add(connector_id)
                        break
        return matched

    def _analyze_user_security(self, users: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze user security details (locked, expired passwords, stale logins, admins)."""
        if not users:
            return {
                "active": 0,
                "inactive": 0,
                "stale_90_days": 0,
                "locked": 0,
                "password_expired": 0,
                "suspended": 0,
                "admins": 0,
            }

        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        ninety_days_ago = now - timedelta(days=90)

        active = 0
        inactive = 0
        stale_90_days = 0
        locked = 0
        password_expired = 0
        suspended = 0
        admins = 0

        for user in users:
            status = user.get("status", "").upper()

            # Count by status
            if status == "ACTIVE":
                active += 1
            elif status in ("DEPROVISIONED", "SUSPENDED"):
                inactive += 1
                if status == "SUSPENDED":
                    suspended += 1
            elif status == "LOCKED_OUT":
                locked += 1
                inactive += 1
            elif status == "PASSWORD_EXPIRED":
                password_expired += 1
                inactive += 1

            # Check for stale logins (90+ days)
            last_login = user.get("lastLogin")
            if last_login:
                try:
                    last_login_dt = datetime.fromisoformat(last_login.replace("Z", "+00:00"))
                    if last_login_dt < ninety_days_ago:
                        stale_90_days += 1
                except (ValueError, AttributeError):
                    pass

            # Check for admin users (users with admin roles)
            user_type = user.get("type", {})
            if isinstance(user_type, dict):
                type_id = user_type.get("id", "").lower()
                if "admin" in type_id or "superadmin" in type_id:
                    admins += 1

        return {
            "active": active,
            "inactive": inactive,
            "stale_90_days": stale_90_days,
            "locked": locked,
            "password_expired": password_expired,
            "suspended": suspended,
            "admins": admins,
        }

    def _analyze_group_details(
        self,
        groups: list[dict[str, Any]],
        applications: list[dict[str, Any]],
        group_rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Analyze group details (nested, assigned to apps, unassigned, rules)."""
        if not groups:
            return {"total": 0, "nested": 0, "assigned": 0, "unassigned": 0, "rules": 0}

        nested = 0
        assigned_group_ids: set[str] = set()

        # Check for nested groups (groups with type "GROUP" or objectClass "okta:user_group")
        for group in groups:
            group_type = group.get("type", "").upper()
            if group_type in ("APP_GROUP", "BUILT_IN"):
                nested += 1

        # Check which groups are assigned to applications
        for app in applications:
            embedded = app.get("_embedded", {})
            app_groups = embedded.get("group", [])
            for app_group in app_groups:
                group_id = app_group.get("id")
                if group_id:
                    assigned_group_ids.add(str(group_id))

        assigned = len(assigned_group_ids)
        unassigned = len(groups) - assigned
        rules_count = len(group_rules)

        return {
            "total": len(groups),
            "nested": nested,
            "assigned": assigned,
            "unassigned": max(0, unassigned),
            "rules": rules_count,
        }

    def _analyze_app_details(self, applications: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze application details (SAML, OIDC, OAuth, SWA, provisioning, active/inactive)."""
        if not applications:
            return {
                "saml": 0,
                "oidc": 0,
                "oauth": 0,
                "swa": 0,
                "other": 0,
                "provisioning": 0,
                "active": 0,
                "inactive": 0,
            }

        saml = 0
        oidc = 0
        oauth = 0
        swa = 0
        other = 0
        provisioning = 0
        active = 0
        inactive = 0

        for app in applications:
            sign_on_mode = (app.get("signOnMode") or "").upper()
            status = (app.get("status") or "ACTIVE").upper()

            # Categorize by sign-on mode
            if "SAML" in sign_on_mode:
                saml += 1
            elif "OPENID_CONNECT" in sign_on_mode or "OIDC" in sign_on_mode:
                oidc += 1
            elif "OAUTH" in sign_on_mode:
                oauth += 1
            elif "SWA" in sign_on_mode or "SECURE_PASSWORD_STORE" in sign_on_mode:
                swa += 1
            else:
                other += 1

            # Check for provisioning
            features = app.get("features", [])
            if features and any("PROVISIONING" in str(f).upper() for f in features):
                provisioning += 1

            # Count active/inactive
            if status == "ACTIVE":
                active += 1
            else:
                inactive += 1

        return {
            "saml": saml,
            "oidc": oidc,
            "oauth": oauth,
            "swa": swa,
            "other": other,
            "provisioning": provisioning,
            "active": active,
            "inactive": inactive,
        }

    def _analyze_policies(self, policies: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze policies (categorize by type: user vs app)."""
        if not policies:
            return {
                "user_policies": {"total": 0, "assigned": 0, "unassigned": 0},
                "app_policies": {"total": 0, "assigned": 0, "unassigned": 0},
            }

        user_policies = []
        app_policies = []

        for policy in policies:
            policy_type = (policy.get("type") or "").upper()

            # Categorize by type
            if "SIGN" in policy_type or "PASSWORD" in policy_type or "MFA" in policy_type:
                user_policies.append(policy)
            elif "APP" in policy_type or "OAUTH" in policy_type:
                app_policies.append(policy)
            else:
                # Default to user policies
                user_policies.append(policy)

        return {
            "user_policies": {
                "total": len(user_policies),
                "assigned": len(user_policies),  # Okta policies are implicitly assigned
                "unassigned": 0,
            },
            "app_policies": {
                "total": len(app_policies),
                "assigned": len(app_policies),
                "unassigned": 0,
            },
        }

    def _analyze_mfa(self, authenticators: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze MFA authenticators (assigned vs unassigned)."""
        if not authenticators:
            return {"total": 0, "assigned": 0, "unassigned": 0}

        assigned = 0
        for authenticator in authenticators:
            status = (authenticator.get("status") or "").upper()
            if status == "ACTIVE":
                assigned += 1

        return {
            "total": len(authenticators),
            "assigned": assigned,
            "unassigned": max(0, len(authenticators) - assigned),
        }

    def _analyze_directories(self, identity_providers: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze directory integrations (active vs inactive)."""
        if not identity_providers:
            return {"total": 0, "active": 0, "inactive": 0}

        active = 0
        for idp in identity_providers:
            status = (idp.get("status") or "").upper()
            if status == "ACTIVE":
                active += 1

        return {
            "total": len(identity_providers),
            "active": active,
            "inactive": max(0, len(identity_providers) - active),
        }


class AnalysisPage(BasePage):
    """Pre-migration analysis page with tabbed interface."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Step 5 – Environment Analysis")
        self.analysis_results: dict[str, Any] | None = None
        self.worker: AnalysisWorker | None = None
        self.auto_analyze = True

        # Store tab widget reference
        self.tab_widget: QTabWidget | None = None

        self.setup_ui()

    def setup_ui(self):
        """Set up the UI components with tabbed layout."""
        self.body_layout.setSpacing(10)

        # Header - store reference to update dynamically
        self.header_label = QLabel("Environment Analysis")
        header_font = QFont()
        header_font.setPointSize(16)
        header_font.setBold(True)
        self.header_label.setFont(header_font)
        self.body_layout.addWidget(self.header_label)

        # Description - store reference to update dynamically
        self.desc_label = QLabel(
            "Analyzing your environment to provide a comprehensive overview "
            "of what will be migrated to OneLogin."
        )
        self.desc_label.setWordWrap(True)

        def update_desc_style():
            self.desc_label.setStyleSheet(
                f"color: {self.theme_manager.get_color('text_secondary')}; margin-bottom: 10px;"
            )

        update_desc_style()
        self.theme_manager.theme_changed.connect(update_desc_style)
        self.body_layout.addWidget(self.desc_label)

        # Loading state container
        self.loading_container = QWidget()
        loading_layout = QVBoxLayout(self.loading_container)
        loading_layout.setContentsMargins(50, 30, 50, 30)
        loading_layout.setSpacing(15)

        self.status_label = QLabel("Preparing to analyze...")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setMinimumHeight(20)
        loading_layout.addWidget(self.progress_bar)
        loading_layout.addStretch()
        self._update_loading_styles()

        # Results container (will be shown after analysis)
        self.results_container = QWidget()
        results_layout = QVBoxLayout(self.results_container)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(10)

        # Top bar with Refresh button and View Detailed Report button
        top_bar_layout = QHBoxLayout()

        self.analyze_button = QPushButton("↻ Refresh Analysis")
        self.analyze_button.clicked.connect(self.run_analysis)
        top_bar_layout.addWidget(self.analyze_button)

        top_bar_layout.addStretch()

        # View Detailed Report button - positioned at top right
        self.detail_report_button = QPushButton("View Detailed Report")
        self.detail_report_button.clicked.connect(self.open_detailed_report)
        top_bar_layout.addWidget(self.detail_report_button)
        self._update_action_button_styles()

        results_layout.addLayout(top_bar_layout)

        # Completion timestamp label
        self.completion_label = QLabel("")
        self.completion_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        results_layout.addWidget(self.completion_label)
        # Initial styling will be applied when results are displayed

        # Tab widget for different analysis sections
        self.tab_widget = QTabWidget()
        self._update_tab_widget_style()
        results_layout.addWidget(self.tab_widget, 1)

        # Connect theme changes to update tab styling
        self.theme_manager.theme_changed.connect(self._on_theme_changed)

        # Initially hide results container
        self.results_container.setVisible(False)

        # Add loading container to body layout
        self.body_layout.addWidget(self.loading_container, 1)

    def _update_loading_styles(self) -> None:
        """Refresh the loading indicator styles from the active theme."""
        primary = self.theme_manager.get_color("primary")
        text_primary = self.theme_manager.get_color("text_primary")
        surface = self.theme_manager.get_color("surface")
        padding = self.theme_manager.get_spacing("sm")

        self.status_label.setStyleSheet(
            f"""
            color: {primary};
            font-size: 16px;
            font-weight: bold;
            padding: {padding}px;
        """
        )

        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: 2px solid {primary};
                border-radius: 5px;
                text-align: center;
                background-color: {surface};
                color: {text_primary};
            }}
            QProgressBar::chunk {{
                background-color: {primary};
            }}
        """
        )

    def _update_action_button_styles(self) -> None:
        """Apply the current theme styling to action buttons."""
        if hasattr(self, "analyze_button"):
            self.analyze_button.setStyleSheet(ACTION_BUTTON_STYLE())
        if hasattr(self, "detail_report_button"):
            self.detail_report_button.setStyleSheet(ACTION_BUTTON_STYLE())

    def _update_completion_label_style(self) -> None:
        """Update completion label styling based on current theme."""
        success = self.theme_manager.get_color("success")
        success_light = self.theme_manager.get_color("success_light")
        text_color = self.theme_manager.get_color("text_primary")
        padding_v = self.theme_manager.get_spacing("sm") + self.theme_manager.get_spacing("xs")
        padding_h = self.theme_manager.get_spacing("lg")

        self.completion_label.setStyleSheet(
            f"""
            color: {text_color};
            font-size: 13px;
            font-weight: 600;
            padding: {padding_v}px {padding_h}px;
            background-color: {success_light};
            border-left: 4px solid {success};
            margin-top: {self.theme_manager.get_spacing('sm')}px;
            margin-bottom: {self.theme_manager.get_spacing('sm')}px;
        """
        )

    def _update_tab_widget_style(self) -> None:
        """Update tab widget styling based on current theme."""
        border_color = self.theme_manager.get_color("border")
        surface = self.theme_manager.get_color("surface")
        surface_elevated = self.theme_manager.get_color("surface_elevated")
        text_secondary = self.theme_manager.get_color("text_secondary")
        text_primary = self.theme_manager.get_color("text_primary")
        primary_color = self.theme_manager.get_color("primary")

        self.tab_widget.setStyleSheet(
            f"""
            QTabWidget::pane {{
                border: 1px solid {border_color};
                border-radius: 4px;
                background-color: {surface_elevated};
                padding: 15px;
            }}
            QTabBar::tab {{
                background-color: {surface};
                color: {text_secondary};
                border: 1px solid {border_color};
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-size: 13px;
                font-weight: 600;
            }}
            QTabBar::tab:selected {{
                background-color: {surface_elevated};
                border-bottom: none;
                color: {primary_color};
            }}
            QTabBar::tab:hover {{
                background-color: {surface_elevated};
                color: {text_primary};
            }}
        """
        )

    def _on_theme_changed(self) -> None:
        """Handle theme changes by updating all styled elements."""
        # Update tab widget style
        self._update_tab_widget_style()

        # Update completion label style
        self._update_completion_label_style()
        self._update_loading_styles()
        self._update_action_button_styles()

        # Refresh tabs if analysis results exist
        if self.analysis_results:
            current_index = self.tab_widget.currentIndex()
            scroll_positions = []
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if widget:
                    scroll = widget.findChild(QScrollArea)
                    scroll_positions.append(scroll.verticalScrollBar().value() if scroll else 0)
                else:
                    scroll_positions.append(0)
            self.display_results(self.analysis_results)
            if current_index != -1:
                restored_index = min(current_index, self.tab_widget.count() - 1)
                if restored_index >= 0:
                    self.tab_widget.setCurrentIndex(restored_index)
                    widget = self.tab_widget.widget(restored_index)
                    if widget:
                        scroll = widget.findChild(QScrollArea)
                        if scroll:
                            scroll.verticalScrollBar().setValue(scroll_positions[restored_index])

    def on_enter(self, state: WizardState) -> None:
        """Handle page entry - auto-run analysis if configured."""
        super().on_enter(state)

        # Update header and description based on source settings
        if self._state and self._state.source_settings:
            source_name = self._state.source_settings.get("name", "Okta")
            self.header_label.setText(f"{source_name} Environment Analysis")
            self.desc_label.setText(
                f"Analyzing your {source_name} environment to provide a comprehensive overview "
                "of what will be migrated to OneLogin."
            )

        if self.auto_analyze and not self.analysis_results:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(100, self.run_analysis)

    def run_analysis(self):
        """Start the analysis in a background thread."""
        if not self._state:
            QMessageBox.warning(self, "Configuration Missing", "Wizard state not initialized.")
            return

        source_settings = self._state.source_settings
        if not source_settings:
            QMessageBox.warning(
                self, "Configuration Missing", "Please configure Okta settings first."
            )
            return

        try:
            subdomain = source_settings.get("subdomain", "").strip()
            token = source_settings.get("token", "").strip()

            if not subdomain or not token:
                QMessageBox.warning(
                    self, "Configuration Missing", "Okta subdomain and API token are required."
                )
                return

            domain = f"{subdomain}.okta.com"
            rate_limit = int(source_settings.get("rate_limit_per_minute", 600))

            okta_settings = OktaApiSettings(
                domain=domain, token=token, rate_limit_per_minute=rate_limit, page_size=200
            )
        except (ValueError, TypeError) as e:
            QMessageBox.warning(self, "Configuration Error", f"Invalid Okta settings: {e}")
            return

        onelogin_client: OneLoginClient | None = None
        if self._state and self._state.target_settings:
            target_settings = self._state.target_settings
            try:
                client_id = (target_settings.get("client_id") or "").strip()
                client_secret = (target_settings.get("client_secret") or "").strip()
                region = (target_settings.get("region") or "us").strip() or "us"
                subdomain_target = (target_settings.get("subdomain") or "").strip()
                rate_limit_per_hour = int(target_settings.get("rate_limit_per_hour", 5000) or 5000)

                if client_id and client_secret and subdomain_target:
                    onelogin_settings = OneLoginApiSettings(
                        client_id=client_id,
                        client_secret=client_secret,
                        region=region,
                        subdomain=subdomain_target,
                        rate_limit_per_hour=rate_limit_per_hour,
                    )
                    onelogin_client = OneLoginClient(onelogin_settings)
                else:
                    LOGGER.info(
                        "OneLogin credentials incomplete; skipping connector catalog lookup."
                    )
            except (ValueError, TypeError) as exc:
                LOGGER.warning(
                    "Skipping OneLogin connector lookup due to configuration error: %s", exc
                )

        # Show loading state
        self.loading_container.setVisible(True)
        self.results_container.setVisible(False)
        self.status_label.setText("Connecting to Okta...")

        # Create and start worker
        okta_client = OktaClient(okta_settings)
        self.worker = AnalysisWorker(okta_client, onelogin_client)
        self.worker.progress_update.connect(self.on_progress_update)
        self.worker.analysis_complete.connect(self.on_analysis_complete)
        self.worker.analysis_error.connect(self.on_analysis_error)
        self.worker.start()

    def on_progress_update(self, message: str):
        """Handle progress updates from worker thread."""
        self.status_label.setText(message)

    def on_analysis_complete(self, results: dict[str, Any]):
        """Handle successful analysis completion."""
        self.analysis_results = results
        if self._state:
            self._state.raw_export = results.get("raw_export")

        # Display results in tabs
        self.display_results(results)

        # Switch to results view
        self.loading_container.setVisible(False)
        if self.results_container.parent() is None:
            self.body_layout.addWidget(self.results_container, 1)
        self.results_container.setVisible(True)

        LOGGER.info(f"Analysis complete. Results set: {self.analysis_results is not None}")
        self.completeChanged.emit()

    def on_analysis_error(self, error_message: str):
        """Handle analysis errors."""
        self.display_error(error_message)
        self.loading_container.setVisible(False)
        if self.results_container.parent() is None:
            self.body_layout.addWidget(self.results_container, 1)
        self.results_container.setVisible(True)

    def display_error(self, error_message: str):
        """Display error message in the UI."""
        self.tab_widget.clear()

        error_widget = QWidget()
        error_layout = QVBoxLayout(error_widget)

        error_label = QLabel(f"<b>⚠️ Analysis Failed</b><br/><br/>{error_message}")
        error_label.setWordWrap(True)
        error_color = self.theme_manager.get_color("error")
        error_bg = self.theme_manager.get_color("surface_elevated")
        text_color = self.theme_manager.get_color("text_primary")
        padding = self.theme_manager.get_spacing("md")
        error_label.setStyleSheet(
            f"color: {text_color}; padding: {padding}px; font-size: 14px; "
            f"background-color: {error_bg}; border-left: 4px solid {error_color};"
        )
        error_layout.addWidget(error_label)

        retry_button = QPushButton("🔄 Retry Analysis")
        retry_button.clicked.connect(self.run_analysis)
        retry_button.setStyleSheet(DESTRUCTIVE_BUTTON_STYLE())
        error_layout.addWidget(retry_button)
        error_layout.addStretch()

        self.tab_widget.addTab(error_widget, "Error")

    def display_results(self, results: dict[str, Any]):
        """Display analysis results in tabbed interface."""
        self._update_action_button_styles()

        # Update completion timestamp
        timestamp = datetime.fromisoformat(results["timestamp"]).strftime("%B %d, %Y at %I:%M %p")
        self.completion_label.setText(f"Analysis completed on {timestamp}")

        # Update completion label styling for current theme
        self._update_completion_label_style()

        # Clear existing tabs
        self.tab_widget.clear()

        # Create tabs
        overview_tab = self.create_overview_tab(results)
        users_tab = self.create_users_tab(results["users"])
        groups_tab = self.create_groups_tab(results["groups"])
        apps_tab = self.create_apps_tab(results["applications"])
        custom_attrs_tab = self.create_custom_attributes_tab(results["users"])

        # Add tabs to widget
        self.tab_widget.addTab(overview_tab, "Overview")
        self.tab_widget.addTab(users_tab, "Users")
        self.tab_widget.addTab(groups_tab, "Groups")
        self.tab_widget.addTab(apps_tab, "Apps")
        self.tab_widget.addTab(custom_attrs_tab, "Custom Attributes")

    def create_overview_tab(self, results: dict[str, Any]) -> QWidget:
        """Create the Analysis Overview tab."""
        widget = QWidget()
        widget.setStyleSheet(f"background-color: {self.theme_manager.get_color('background')};")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Source information
        source_label = QLabel(
            f"<span style='color: {self.theme_manager.get_color('text_secondary')}; font-size: 13px;'>Source Environment:</span> "
            f"<span style='color: {self.theme_manager.get_color('text_primary')}; font-size: 13px; font-weight: 600;'>{results['source']}</span>"
        )
        layout.addWidget(source_label)

        layout.addSpacing(20)

        # Stats grid with large numbers
        stats_widget = QWidget()
        stats_layout = QGridLayout(stats_widget)
        stats_layout.setSpacing(30)
        stats_layout.setContentsMargins(0, 0, 0, 0)

        users_total = results["users"]["total"]
        groups_total = results["groups"]["total"]
        apps_total = results["applications"]["total"]

        # Helper to create stat display
        def create_stat(number: int, label: str) -> QWidget:
            stat_widget = QWidget()
            stat_layout = QVBoxLayout(stat_widget)
            stat_layout.setContentsMargins(0, 0, 0, 0)
            stat_layout.setSpacing(8)

            num_label = QLabel(f"{number:,}")
            num_label.setStyleSheet(
                f"font-size: 48px; font-weight: 700; color: {self.theme_manager.get_color('primary')};"
            )
            num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            text_label = QLabel(label)
            text_label.setStyleSheet(
                f"font-size: 13px; color: {self.theme_manager.get_color('text_secondary')}; font-weight: 600; text-transform: uppercase;"
            )
            text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            stat_layout.addWidget(num_label)
            stat_layout.addWidget(text_label)
            return stat_widget

        stats_layout.addWidget(create_stat(users_total, "Users"), 0, 0)
        stats_layout.addWidget(create_stat(groups_total, "Groups"), 0, 1)
        stats_layout.addWidget(create_stat(apps_total, "Applications"), 0, 2)

        layout.addWidget(stats_widget)
        layout.addSpacing(20)

        # Status indicator
        status_label = QLabel("✓ Ready to proceed with migration")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        success_color = self.theme_manager.get_color("success")
        status_label.setStyleSheet(
            f"""
            color: {success_color};
            font-size: 14px;
            font-weight: 600;
            padding: 12px;
            background-color: {self.theme_manager.get_color('surface_elevated')};
            border-radius: 4px;
            border: 2px solid {success_color};
        """
        )
        layout.addWidget(status_label)

        layout.addStretch()
        return widget

    def create_users_tab(self, users_data: dict[str, Any]) -> QWidget:
        """Create the Users tab."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        border_color = self.theme_manager.get_color("border")
        scroll.setStyleSheet(
            f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {self.theme_manager.get_color('surface')};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {border_color};
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self.theme_manager.get_color('surface_elevated')};
            }}
        """
        )

        content_widget = QWidget()
        content_widget.setStyleSheet(
            f"background-color: {self.theme_manager.get_color('background')};"
        )
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        total = users_data.get("total", 0)
        active = users_data.get("active", 0)
        suspended = users_data.get("suspended", 0)

        # Total count (large)
        total_label = QLabel(
            f"<span style='font-size: 32px; font-weight: 700; color: {self.theme_manager.get_color('primary')};'>{total:,}</span> "
            f"<span style='font-size: 16px; color: {self.theme_manager.get_color('text_secondary')};'>users to migrate</span>"
        )
        layout.addWidget(total_label)

        layout.addSpacing(10)

        # Status breakdown
        status_html = f"""
        <div style='line-height: 1.5; font-size: 14px;'>
            <div style='padding: 6px 0;'>
                <span style='color: {self.theme_manager.get_color('text_secondary')};'>├─</span>
                <span style='color: {self.theme_manager.get_color('success')}; font-weight: 600; font-size: 15px;'>{active:,}</span>
                <span style='color: {self.theme_manager.get_color('text_secondary')};'> Active users</span>
            </div>
            <div style='padding: 6px 0;'>
                <span style='color: {self.theme_manager.get_color('text_secondary')};'>└─</span>
                <span style='color: {self.theme_manager.get_color('warning')}; font-weight: 600; font-size: 15px;'>{suspended:,}</span>
                <span style='color: {self.theme_manager.get_color('text_secondary')};'> Suspended users</span>
            </div>
        </div>
        """
        status_label = QLabel(status_html)
        status_label.setWordWrap(True)
        layout.addWidget(status_label)

        layout.addStretch()

        scroll.setWidget(content_widget)

        wrapper_layout = QVBoxLayout(widget)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(scroll)

        return widget

    def create_groups_tab(self, groups_data: dict[str, Any]) -> QWidget:
        """Create the Groups tab."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        border_color = self.theme_manager.get_color("border")
        scroll.setStyleSheet(
            f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {self.theme_manager.get_color('surface')};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {border_color};
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self.theme_manager.get_color('surface_elevated')};
            }}
        """
        )

        content_widget = QWidget()
        content_widget.setStyleSheet(
            f"background-color: {self.theme_manager.get_color('background')};"
        )
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        total = groups_data.get("total", 0)
        memberships = groups_data.get("total_memberships", 0)

        # Total count
        total_label = QLabel(
            f"<span style='font-size: 32px; font-weight: 700; color: {self.theme_manager.get_color('primary')};'>{total}</span> "
            f"<span style='font-size: 16px; color: {self.theme_manager.get_color('text_secondary')};'>groups to migrate</span>"
        )
        layout.addWidget(total_label)

        layout.addSpacing(10)

        # Memberships
        membership_label = QLabel(
            f"<span style='font-size: 14px; color: {self.theme_manager.get_color('text_secondary')};'>Total memberships: </span>"
            f"<span style='font-size: 14px; font-weight: 600; color: {self.theme_manager.get_color('text_primary')};'>{memberships:,}</span>"
        )
        layout.addWidget(membership_label)

        layout.addSpacing(10)

        # Conversion note
        note_label = QLabel("→ Groups will become OneLogin Roles")
        info_color = self.theme_manager.get_color("info")
        note_label.setStyleSheet(
            f"""
            font-size: 13px;
            color: {info_color};
            font-style: italic;
            font-weight: 600;
            padding: 10px 15px;
            background-color: {self.theme_manager.get_color('surface_elevated')};
            border-radius: 4px;
            border-left: 3px solid {info_color};
        """
        )
        layout.addWidget(note_label)

        layout.addSpacing(20)

        # Top groups
        top_groups = groups_data.get("top_groups", [])
        if top_groups:
            top_label = QLabel(
                f"<span style='font-size: 16px; font-weight: 600; color: {self.theme_manager.get_color('text_primary')};'>Top Groups by Size</span>"
            )
            layout.addWidget(top_label)

            layout.addSpacing(10)

            text_primary = self.theme_manager.get_color("text_primary")
            text_secondary = self.theme_manager.get_color("text_secondary")

            groups_list_layout = QVBoxLayout()
            groups_list_layout.setContentsMargins(0, 0, 0, 0)
            groups_list_layout.setSpacing(6)

            for i, group in enumerate(top_groups[:10], 1):
                row_layout = QHBoxLayout()
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)

                index_label = QLabel(f"{i}.")
                index_label.setStyleSheet(
                    f"color: {text_secondary}; font-weight: 600; font-size: 14px;"
                )
                row_layout.addWidget(index_label, 0, Qt.AlignmentFlag.AlignLeft)

                name_label = QLabel(group["name"])
                name_label.setStyleSheet(
                    f"color: {text_primary}; font-weight: 600; font-size: 14px;"
                )
                row_layout.addWidget(name_label, 0, Qt.AlignmentFlag.AlignLeft)

                members_label = QLabel(f"— {group['members']} members")
                members_label.setStyleSheet(f"color: {text_secondary}; font-size: 14px;")
                row_layout.addWidget(members_label, 0, Qt.AlignmentFlag.AlignLeft)

                row_layout.addStretch()
                groups_list_layout.addLayout(row_layout)

            layout.addLayout(groups_list_layout)

        layout.addStretch()

        scroll.setWidget(content_widget)

        wrapper_layout = QVBoxLayout(widget)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(scroll)

        return widget

    def create_apps_tab(self, apps_data: dict[str, Any]) -> QWidget:
        """Create the Apps tab."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        border_color = self.theme_manager.get_color("border")
        scroll.setStyleSheet(
            f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {self.theme_manager.get_color('surface')};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {border_color};
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self.theme_manager.get_color('surface_elevated')};
            }}
        """
        )

        content_widget = QWidget()
        content_widget.setStyleSheet(
            f"background-color: {self.theme_manager.get_color('background')};"
        )
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        connectors_info = (self.analysis_results or {}).get("connectors", {})
        connector_error = connectors_info.get("error")
        if connector_error:
            banner = QLabel(f"⚠︎ {connector_error}")
            banner.setWordWrap(True)
            banner.setStyleSheet(
                f"color: {self.theme_manager.get_color('warning')};"
                f"background-color: {self.theme_manager.get_color('surface_elevated')};"
                f"border-left: 4px solid {self.theme_manager.get_color('warning')};"
                f"padding: 10px; font-size: 12px;"
            )
            layout.addWidget(banner)

        total = apps_data.get("total", 0)
        can_migrate = len(apps_data.get("can_migrate", []))
        need_review = len(apps_data.get("need_review", []))
        cannot_migrate = len(apps_data.get("cannot_migrate", []))
        breakdown = apps_data.get("breakdown", {})
        connector_matches = breakdown.get("connector_matches", 0)
        custom_sso = breakdown.get("custom_sso", 0)

        # Total count
        total_label = QLabel(
            f"<span style='font-size: 32px; font-weight: 700; color: {self.theme_manager.get_color('primary')};'>{total}</span> "
            f"<span style='font-size: 16px; color: {self.theme_manager.get_color('text_secondary')};'>applications to migrate</span>"
        )
        layout.addWidget(total_label)

        layout.addSpacing(20)

        # Status breakdown
        success_color = self.theme_manager.get_color("success")
        warning_color = self.theme_manager.get_color("warning")
        error_color = self.theme_manager.get_color("error")
        text_primary = self.theme_manager.get_color("text_primary")
        text_secondary = self.theme_manager.get_color("text_secondary")

        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(12)

        def add_status(symbol: str, color: str, count: int, label_text: str, subtitle: str):
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            symbol_label = QLabel(symbol)
            symbol_label.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: 700;")
            row_layout.addWidget(symbol_label, 0, Qt.AlignmentFlag.AlignLeft)

            count_label = QLabel(f"{count}")
            count_label.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: 600;")
            row_layout.addWidget(count_label, 0, Qt.AlignmentFlag.AlignLeft)

            desc_label = QLabel(label_text)
            desc_label.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: 600;")
            row_layout.addWidget(desc_label, 0, Qt.AlignmentFlag.AlignLeft)

            row_layout.addStretch()
            status_layout.addLayout(row_layout)

            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet(f"color: {text_secondary}; font-size: 12px;")
            subtitle_container = QHBoxLayout()
            subtitle_container.setContentsMargins(32, 0, 0, 0)
            subtitle_container.setSpacing(0)
            subtitle_container.addWidget(subtitle_label, 0, Qt.AlignmentFlag.AlignLeft)
            subtitle_container.addStretch()
            status_layout.addLayout(subtitle_container)

        if can_migrate > 0:
            add_status(
                "✓", success_color, can_migrate, "Can Auto-Migrate", "Ready for automated migration"
            )

        if need_review > 0:
            add_status(
                "⚠",
                warning_color,
                need_review,
                "Need Manual Review",
                "Complex configurations require validation",
            )

        if cannot_migrate > 0:
            add_status(
                "✗",
                error_color,
                cannot_migrate,
                "Cannot Auto-Migrate",
                "Unsupported sign-on methods",
            )

        if status_layout.count() > 0:
            layout.addLayout(status_layout)

        if total > 0:
            # Mapping quality statistics
            mapping_quality = apps_data.get("mapping_quality", {})
            exact_count = mapping_quality.get("exact_matches", 0)
            fuzzy_count = mapping_quality.get("fuzzy_matches", 0)
            no_match_count = mapping_quality.get("no_matches", 0)

            # Build breakdown text with mapping quality
            breakdown_parts = []
            if connector_matches > 0:
                breakdown_parts.append(f"{connector_matches} apps matched OneLogin connectors")
            if custom_sso > 0:
                breakdown_parts.append(f"{custom_sso} rely on custom SAML/OpenID")

            breakdown_label = QLabel(
                f"<span style='color: {self.theme_manager.get_color('text_secondary')};'>"
                f"{' • '.join(breakdown_parts)}"
                f"</span>"
            )
            breakdown_label.setWordWrap(True)
            layout.addWidget(breakdown_label)

            # Mapping quality indicator (if we have mapping data)
            if exact_count > 0 or fuzzy_count > 0:
                layout.addSpacing(15)

                quality_title = QLabel("Connector Mapping Quality:")
                quality_title.setStyleSheet(
                    f"color: {text_secondary}; font-size: 13px; font-weight: 600;"
                )
                layout.addWidget(quality_title)

                quality_layout = QVBoxLayout()
                quality_layout.setContentsMargins(0, 0, 0, 0)
                quality_layout.setSpacing(6)

                def add_quality(symbol: str, color: str, count: int, description: str):
                    row_layout = QHBoxLayout()
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.setSpacing(6)

                    symbol_label = QLabel(symbol)
                    symbol_label.setStyleSheet(
                        f"color: {color}; font-size: 14px; font-weight: 700;"
                    )
                    row_layout.addWidget(symbol_label, 0, Qt.AlignmentFlag.AlignLeft)

                    count_label = QLabel(f"{count}")
                    count_label.setStyleSheet(
                        f"color: {text_primary}; font-size: 14px; font-weight: 600;"
                    )
                    row_layout.addWidget(count_label, 0, Qt.AlignmentFlag.AlignLeft)

                    desc_label = QLabel(description)
                    desc_label.setStyleSheet(f"color: {text_secondary}; font-size: 13px;")
                    row_layout.addWidget(desc_label, 0, Qt.AlignmentFlag.AlignLeft)

                    row_layout.addStretch()
                    quality_layout.addLayout(row_layout)

                if exact_count > 0:
                    add_quality("✓", success_color, exact_count, "exact matches (100% confidence)")

                if fuzzy_count > 0:
                    add_quality("~", warning_color, fuzzy_count, "fuzzy matches (recommend review)")

                if no_match_count > 0:
                    add_quality("✗", error_color, no_match_count, "no connector match")

                layout.addLayout(quality_layout)

        # Note about manual configuration
        if need_review > 0 or cannot_migrate > 0:
            layout.addSpacing(20)

            note = QLabel(
                "ⓘ Applications requiring review or that cannot be auto-migrated "
                "will need manual configuration in OneLogin after migration."
            )
            note.setWordWrap(True)
            note.setStyleSheet(
                f"""
                font-size: 13px;
                color: {warning_color};
                padding: 12px 15px;
                background-color: {self.theme_manager.get_color('surface_elevated')};
                border-left: 3px solid {warning_color};
                border-radius: 4px;
            """
            )
            layout.addWidget(note)

        layout.addStretch()

        scroll.setWidget(content_widget)

        wrapper_layout = QVBoxLayout(widget)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(scroll)

        return widget

    def create_custom_attributes_tab(self, users_data: dict[str, Any]) -> QWidget:
        """Create the Custom Attributes tab."""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        border_color = self.theme_manager.get_color("border")
        scroll.setStyleSheet(
            f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {self.theme_manager.get_color('surface')};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {border_color};
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self.theme_manager.get_color('surface_elevated')};
            }}
        """
        )

        content_widget = QWidget()
        content_widget.setStyleSheet(
            f"background-color: {self.theme_manager.get_color('background')};"
        )
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        custom_attrs = users_data.get("custom_attributes", [])

        if custom_attrs:
            # Header
            count_label = QLabel(
                f"<span style='font-size: 32px; font-weight: 700; color: {self.theme_manager.get_color('primary')};'>{len(custom_attrs)}</span> "
                f"<span style='font-size: 16px; color: {self.theme_manager.get_color('text_secondary')};'>custom attributes detected</span>"
            )
            layout.addWidget(count_label)

            layout.addSpacing(10)

            # Help text
            help_text = QLabel(
                "These custom user attributes from Okta will be created as custom fields in OneLogin during migration."
            )
            help_text.setWordWrap(True)
            help_text.setStyleSheet(
                f"font-size: 13px; color: {self.theme_manager.get_color('text_secondary')}; font-style: italic;"
            )
            layout.addWidget(help_text)

            layout.addSpacing(20)

            attrs_list_layout = QVBoxLayout()
            attrs_list_layout.setContentsMargins(0, 0, 0, 0)
            attrs_list_layout.setSpacing(6)

            for attr in custom_attrs:
                row_layout = QHBoxLayout()
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)

                bullet_label = QLabel("•")
                bullet_label.setStyleSheet(
                    f"color: {self.theme_manager.get_color('text_secondary')}; font-size: 14px; font-weight: 600;"
                )
                row_layout.addWidget(bullet_label, 0, Qt.AlignmentFlag.AlignLeft)

                name_label = QLabel(attr)
                name_label.setStyleSheet(
                    f"color: {self.theme_manager.get_color('text_primary')}; font-size: 14px; font-weight: 600;"
                )
                row_layout.addWidget(name_label, 0, Qt.AlignmentFlag.AlignLeft)

                row_layout.addStretch()
                attrs_list_layout.addLayout(row_layout)

            layout.addLayout(attrs_list_layout)

        else:
            # No custom attributes found
            no_attrs_label = QLabel("No custom attributes detected")
            no_attrs_label.setStyleSheet(
                f"font-size: 16px; color: {self.theme_manager.get_color('text_secondary')}; font-style: italic;"
            )
            layout.addWidget(no_attrs_label)

        layout.addStretch()

        scroll.setWidget(content_widget)

        wrapper_layout = QVBoxLayout(widget)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(scroll)

        return widget

    def can_proceed(self, state: WizardState) -> bool:
        """Page is complete if analysis has been run successfully."""
        result = self.analysis_results is not None
        LOGGER.info(
            f"can_proceed: analysis_results={self.analysis_results is not None}, returning={result}"
        )
        return result

    def validate(self, state: WizardState) -> tuple[bool, str]:
        """Validate that analysis was completed before proceeding."""
        if self.analysis_results is not None:
            return True, ""
        return False, "Please wait for the environment analysis to complete."

    def open_detailed_report(self):
        """Open the detailed analysis report dialog."""
        if not self.analysis_results:
            QMessageBox.warning(
                self,
                "No Analysis Data",
                "Please run the analysis first before viewing the detailed report.",
            )
            return

        dialog = AnalysisDetailDialog(self.analysis_results, self)
        dialog.exec()
