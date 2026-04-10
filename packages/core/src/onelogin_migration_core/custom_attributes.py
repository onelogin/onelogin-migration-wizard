"""Custom attribute discovery and provisioning for OneLogin."""

from __future__ import annotations

import logging
from typing import Any

from .constants import KNOWN_STANDARD_FIELDS
from .transformers import FieldTransformer

LOGGER = logging.getLogger(__name__)


class CustomAttributeManager:
    """Manages custom attribute discovery and provisioning."""

    @staticmethod
    def discover_custom_attributes(users: list[dict[str, Any]]) -> set[str]:
        """Analyze Okta users and discover all custom attributes that would be created.

        Returns a set of normalized custom attribute names that would be
        created in OneLogin during migration.

        Args:
            users: List of Okta user objects

        Returns:
            Set of normalized custom attribute names
        """
        attributes: set[str] = set()

        for user in users:
            if not isinstance(user, dict):
                continue

            profile = user.get("profile")
            if not isinstance(profile, dict):
                continue

            # Process all fields dynamically
            for key, value in profile.items():
                # Skip OneLogin standard fields
                if key in KNOWN_STANDARD_FIELDS:
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

                # Normalize the field name for OneLogin
                normalized = FieldTransformer.normalize_custom_attribute_name(key)
                if normalized:
                    attributes.add(normalized)

        return attributes

    @staticmethod
    def provision_custom_attributes(
        onelogin_client: Any,
        attributes: set[str],
    ) -> dict[str, Any]:
        """Provision custom attributes in OneLogin.

        Args:
            onelogin_client: OneLogin API client instance
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
            onelogin_client._load_custom_attribute_cache()
        except Exception as exc:
            LOGGER.warning("Unable to load existing custom attributes: %s", exc)

        for attr_name in sorted(attributes):
            # Check if already exists
            if attr_name in onelogin_client._custom_attribute_cache:
                result["existing"].append(attr_name)
                LOGGER.info("Custom attribute '%s' already exists", attr_name)
                continue

            # Create the attribute
            try:
                onelogin_client._create_custom_attribute(attr_name)
                result["created"].append(attr_name)
                LOGGER.info("Created custom attribute '%s'", attr_name)
            except Exception as exc:
                error_msg = str(exc)
                result["failed"][attr_name] = error_msg
                LOGGER.error("Failed to create custom attribute '%s': %s", attr_name, error_msg)

        return result


__all__ = ["CustomAttributeManager"]
