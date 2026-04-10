"""Shared constants and enums for migration operations."""

from __future__ import annotations

# Application connector mapping (default values)
DEFAULT_APPLICATION_CONNECTORS: dict[str, dict[str | None, int]] = {}

# Known profile fields that map to standard OneLogin user fields (not custom attributes)
# Based on OneLogin API docs: https://developers.onelogin.com/api-docs/2/users/create-user
KNOWN_STANDARD_FIELDS: set[str] = {
    # Core user fields (required/common)
    "username",
    "email",
    "login",  # Okta uses "login" which maps to OneLogin "username"
    # Profile fields
    "firstname",
    "firstName",  # Okta casing
    "lastname",
    "lastName",  # Okta casing
    "title",
    "department",
    "company",
    "comment",
    "phone",
    "state",  # OneLogin has "state" for approval status
    # Locale
    "preferred_locale_code",
    "preferredLocale",  # Okta casing
    "locale",  # Okta casing
    # Active Directory fields
    "manager_ad_id",
    "manager_user_id",
    "samaccountname",
    "samAccountName",  # Okta casing
    "member_of",
    "userprincipalname",
    "userPrincipalName",  # Okta casing
    "distinguished_name",
    # Authentication fields
    "password",
    "password_confirmation",
    "password_algorithm",
    "salt",
    # Identity fields
    "external_id",
    "openid_name",
}

__all__ = [
    "DEFAULT_APPLICATION_CONNECTORS",
    "KNOWN_STANDARD_FIELDS",
]
