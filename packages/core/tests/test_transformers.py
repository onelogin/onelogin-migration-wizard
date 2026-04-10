"""Comprehensive tests for transformers module."""

from __future__ import annotations

import pytest

from onelogin_migration_core.transformers import FieldTransformer


class TestFieldTransformerUserTransform:
    """Tests for user transformation logic."""

    def test_transform_user_basic(self) -> None:
        """Test basic user transformation with minimal fields."""
        user = {
            "profile": {
                "firstName": "John",
                "lastName": "Doe",
                "email": "john.doe@example.com",
                "login": "john.doe@example.com",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["firstname"] == "John"
        assert result["lastname"] == "Doe"
        assert result["email"] == "john.doe@example.com"
        assert result["username"] == "john.doe@example.com"
        assert result["state"] == 1
        assert result["status"] == 1

    def test_transform_user_inactive(self) -> None:
        """Test user transformation with inactive status."""
        user = {
            "profile": {
                "firstName": "Jane",
                "lastName": "Smith",
                "email": "jane@example.com",
                "login": "jane@example.com",
            },
            "status": "SUSPENDED",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["state"] == 0
        assert result["status"] == 0

    def test_transform_user_with_phone_fields(self) -> None:
        """Test user transformation with phone fields."""
        user = {
            "profile": {
                "firstName": "Alice",
                "lastName": "Johnson",
                "email": "alice@example.com",
                "login": "alice@example.com",
                "mobilePhone": "+1-555-1234",
                "primaryPhone": "+1-555-5678",
                "workPhone": "+1-555-9999",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["mobile_phone"] == "+1-555-1234"
        assert result["phone"] == "+1-555-5678"

    def test_transform_user_with_organization_fields(self) -> None:
        """Test user transformation with organization fields."""
        user = {
            "profile": {
                "firstName": "Bob",
                "lastName": "Wilson",
                "email": "bob@example.com",
                "login": "bob@example.com",
                "company": "Acme Corp",
                "department": "Engineering",
                "title": "Senior Developer",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["company"] == "Acme Corp"
        assert result["department"] == "Engineering"
        assert result["title"] == "Senior Developer"

    def test_transform_user_with_ad_fields(self) -> None:
        """Test user transformation with Active Directory fields."""
        user = {
            "profile": {
                "firstName": "Charlie",
                "lastName": "Brown",
                "email": "charlie@example.com",
                "login": "charlie@example.com",
                "samAccountName": "cbrown",
                "userPrincipalName": "cbrown@ad.example.com",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["samaccountname"] == "cbrown"
        assert result["userprincipalname"] == "cbrown@ad.example.com"

    def test_transform_user_samaccountname_from_login(self) -> None:
        """Test SAM account name derivation from login."""
        user = {
            "profile": {
                "firstName": "David",
                "lastName": "Lee",
                "email": "david@example.com",
                "login": "dlee@example.com",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["samaccountname"] == "dlee"

    def test_transform_user_with_custom_attributes(self) -> None:
        """Test user transformation with custom attributes."""
        user = {
            "profile": {
                "firstName": "Emma",
                "lastName": "Garcia",
                "email": "emma@example.com",
                "login": "emma@example.com",
                "secondEmail": "emma.garcia@personal.com",
                "streetAddress": "123 Main St",
                "city": "Springfield",
                "state": "IL",
                "zipCode": "62701",
                "country": "US",
                "countryCode": "US",
                "displayName": "Emma G.",
                "employeeNumber": "E12345",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert "custom_attributes" in result
        attrs = result["custom_attributes"]
        assert attrs["second_email"] == "emma.garcia@personal.com"
        assert attrs["street_address"] == "123 Main St"
        assert attrs["city"] == "Springfield"
        assert attrs["state"] == "IL"
        assert attrs["zip_code"] == "62701"
        assert attrs["country"] == "US"
        assert attrs["country_code"] == "US"
        assert attrs["display_name"] == "Emma G."
        assert attrs["employee_number"] == "E12345"

    def test_transform_user_with_dynamic_custom_attributes(self) -> None:
        """Test user transformation with dynamic custom attributes."""
        user = {
            "profile": {
                "firstName": "Frank",
                "lastName": "Miller",
                "email": "frank@example.com",
                "login": "frank@example.com",
                "customField1": "value1",
                "anotherCustomField": "value2",
                "numericField": 12345,
                "booleanField": True,
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert "custom_attributes" in result
        attrs = result["custom_attributes"]
        assert attrs["custom_field1"] == "value1"
        assert attrs["another_custom_field"] == "value2"
        assert attrs["numeric_field"] == "12345"
        assert attrs["boolean_field"] == "True"

    def test_transform_user_skips_complex_custom_attributes(self) -> None:
        """Test that complex types are skipped in custom attributes."""
        user = {
            "profile": {
                "firstName": "Grace",
                "lastName": "Hopper",
                "email": "grace@example.com",
                "login": "grace@example.com",
                "simpleField": "value",
                "arrayField": ["item1", "item2"],
                "objectField": {"key": "value"},
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert "custom_attributes" in result
        attrs = result["custom_attributes"]
        assert "simple_field" in attrs
        assert "array_field" not in attrs
        assert "object_field" not in attrs

    def test_transform_user_with_external_id(self) -> None:
        """Test user transformation preserves external ID."""
        user = {
            "id": "00u123abc456def",
            "profile": {
                "firstName": "Henry",
                "lastName": "Ford",
                "email": "henry@example.com",
                "login": "henry@example.com",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["external_id"] == "00u123abc456def"

    def test_transform_user_with_credentials_email(self) -> None:
        """Test user transformation extracts email from credentials."""
        user = {
            "profile": {
                "firstName": "Isabel",
                "lastName": "Chen",
                "login": "isabel@example.com",
            },
            "credentials": {
                "emails": [
                    {"value": "isabel.chen@example.com", "type": "primary"}
                ]
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["email"] == "isabel.chen@example.com"

    def test_transform_user_with_comment_fields(self) -> None:
        """Test user transformation with comment/notes fields."""
        user = {
            "profile": {
                "firstName": "Jack",
                "lastName": "Ryan",
                "email": "jack@example.com",
                "login": "jack@example.com",
                "comment": "Test comment",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["comment"] == "Test comment"

    def test_transform_user_cleans_empty_values(self) -> None:
        """Test that empty strings are removed from payload."""
        user = {
            "profile": {
                "firstName": "Kate",
                "lastName": "Smith",
                "email": "kate@example.com",
                "login": "kate@example.com",
                "title": "",
                "department": "   ",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert "title" not in result
        assert "department" not in result

    def test_transform_user_returns_none_for_invalid(self) -> None:
        """Test that invalid user returns None."""
        user = {"invalid": "data"}
        result = FieldTransformer.transform_user(user)
        assert result is None

    def test_transform_user_with_locale(self) -> None:
        """Test user transformation with locale."""
        user = {
            "profile": {
                "firstName": "Liam",
                "lastName": "O'Brien",
                "email": "liam@example.com",
                "login": "liam@example.com",
                "locale": "en-US",
            },
            "status": "ACTIVE",
        }

        result = FieldTransformer.transform_user(user)

        assert result is not None
        assert result["preferred_locale_code"] == "en-US"


class TestFieldTransformerGroupTransform:
    """Tests for group transformation logic."""

    def test_transform_group_basic(self) -> None:
        """Test basic group transformation."""
        group = {
            "profile": {
                "name": "Engineering Team"
            }
        }

        result = FieldTransformer.transform_group(group)

        assert result is not None
        assert result["name"] == "Engineering Team"

    def test_transform_group_from_label(self) -> None:
        """Test group transformation using label field."""
        group = {
            "label": "Sales Team"
        }

        result = FieldTransformer.transform_group(group)

        assert result is not None
        assert result["name"] == "Sales Team"

    def test_transform_group_returns_none_for_invalid(self) -> None:
        """Test that invalid group returns None."""
        group = {"invalid": "data"}
        result = FieldTransformer.transform_group(group)
        assert result is None


class TestFieldTransformerApplicationTransform:
    """Tests for application transformation logic."""

    def test_transform_application_basic(self) -> None:
        """Test basic application transformation."""
        app = {
            "label": "Slack",
            "signOnMode": "saml",
            "settings": {
                "appVisible": True
            }
        }
        connector_lookup = {
            "slack": {"saml": 123456}
        }

        result = FieldTransformer.transform_application(app, connector_lookup)

        assert result is not None
        assert result["name"] == "Slack"
        assert result["connector_id"] == 123456
        assert result["visible"] is True
        assert result["signon_mode"] == "saml"

    def test_transform_application_with_configuration(self) -> None:
        """Test application transformation with configuration."""
        app = {
            "label": "GitHub",
            "signOnMode": "openid",
            "settings": {
                "appUrl": "https://github.com",
                "appSettingsJson": {
                    "client_id": "abc123"
                }
            }
        }
        connector_lookup = {
            "github": {"openid": 789012}
        }

        result = FieldTransformer.transform_application(app, connector_lookup)

        assert result is not None
        assert result["connector_id"] == 789012
        assert "configuration" in result
        assert result["configuration"]["client_id"] == "abc123"
        assert result["configuration"]["url"] == "https://github.com"

    def test_transform_application_without_connector_returns_none(self) -> None:
        """Test that app without connector mapping returns None."""
        app = {
            "label": "Unknown App",
            "signOnMode": "saml"
        }
        connector_lookup = {}

        result = FieldTransformer.transform_application(app, connector_lookup)

        assert result is None

    def test_transform_application_normalizes_label_for_lookup(self) -> None:
        """Test that app labels are normalized for lookup."""
        app = {
            "label": "  GitHub   Enterprise  ",
            "signOnMode": "saml"
        }
        connector_lookup = {
            "github enterprise": {"saml": 99999}
        }

        result = FieldTransformer.transform_application(app, connector_lookup)

        assert result is not None
        assert result["connector_id"] == 99999

    def test_transform_application_with_wildcard_connector(self) -> None:
        """Test application with wildcard connector (no specific sign-on mode)."""
        app = {
            "label": "Custom App",
            "signOnMode": "oidc"
        }
        connector_lookup = {
            "custom app": {None: 55555}
        }

        result = FieldTransformer.transform_application(app, connector_lookup)

        assert result is not None
        assert result["connector_id"] == 55555


class TestNormalizeCustomAttributeName:
    """Tests for custom attribute name normalization."""

    def test_normalize_camel_case(self) -> None:
        """Test camelCase to snake_case conversion."""
        assert FieldTransformer.normalize_custom_attribute_name("employeeNumber") == "employee_number"
        assert FieldTransformer.normalize_custom_attribute_name("secondEmail") == "second_email"
        assert FieldTransformer.normalize_custom_attribute_name("displayName") == "display_name"

    def test_normalize_pascal_case(self) -> None:
        """Test PascalCase to snake_case conversion."""
        assert FieldTransformer.normalize_custom_attribute_name("EmployeeNumber") == "employee_number"
        assert FieldTransformer.normalize_custom_attribute_name("FirstName") == "first_name"

    def test_normalize_already_snake_case(self) -> None:
        """Test that snake_case is preserved."""
        assert FieldTransformer.normalize_custom_attribute_name("employee_number") == "employee_number"
        assert FieldTransformer.normalize_custom_attribute_name("custom_field") == "custom_field"

    def test_normalize_removes_invalid_chars(self) -> None:
        """Test that invalid characters are replaced."""
        assert FieldTransformer.normalize_custom_attribute_name("field-name") == "field_name"
        assert FieldTransformer.normalize_custom_attribute_name("field.name") == "field_name"
        assert FieldTransformer.normalize_custom_attribute_name("field name") == "field_name"
        assert FieldTransformer.normalize_custom_attribute_name("field@name") == "field_name"

    def test_normalize_starts_with_digit(self) -> None:
        """Test that names starting with digit get prefix."""
        assert FieldTransformer.normalize_custom_attribute_name("123field") == "_123field"
        assert FieldTransformer.normalize_custom_attribute_name("1stName") == "_1st_name"

    def test_normalize_max_length(self) -> None:
        """Test that names are truncated to 64 characters."""
        long_name = "a" * 100
        result = FieldTransformer.normalize_custom_attribute_name(long_name)
        assert len(result) == 64

    def test_normalize_empty_string(self) -> None:
        """Test that empty string returns empty."""
        assert FieldTransformer.normalize_custom_attribute_name("") == ""
        assert FieldTransformer.normalize_custom_attribute_name("   ") == ""

    def test_normalize_strips_underscores(self) -> None:
        """Test that leading/trailing underscores are stripped."""
        assert FieldTransformer.normalize_custom_attribute_name("_field_") == "field"
        assert FieldTransformer.normalize_custom_attribute_name("__field__") == "field"

    def test_normalize_non_string(self) -> None:
        """Test that non-string input returns empty."""
        assert FieldTransformer.normalize_custom_attribute_name(None) == ""  # type: ignore
        assert FieldTransformer.normalize_custom_attribute_name(123) == ""  # type: ignore


class TestNormalizeAppLabel:
    """Tests for application label normalization."""

    def test_normalize_app_label_basic(self) -> None:
        """Test basic label normalization."""
        assert FieldTransformer.normalize_app_label("Slack") == "slack"
        assert FieldTransformer.normalize_app_label("GitHub") == "github"

    def test_normalize_app_label_whitespace(self) -> None:
        """Test that multiple spaces are normalized to single space."""
        assert FieldTransformer.normalize_app_label("  GitHub   Enterprise  ") == "github enterprise"
        assert FieldTransformer.normalize_app_label("App\t\tName") == "app name"

    def test_normalize_app_label_non_string(self) -> None:
        """Test that non-string returns empty string."""
        assert FieldTransformer.normalize_app_label(None) == ""
        assert FieldTransformer.normalize_app_label(123) == ""


class TestNormalizeSignonMode:
    """Tests for sign-on mode normalization."""

    def test_normalize_signon_mode_basic(self) -> None:
        """Test basic sign-on mode normalization."""
        assert FieldTransformer.normalize_signon_mode("SAML") == "saml"
        assert FieldTransformer.normalize_signon_mode("OpenID") == "openid"

    def test_normalize_signon_mode_none(self) -> None:
        """Test that None returns None."""
        assert FieldTransformer.normalize_signon_mode(None) is None

    def test_normalize_signon_mode_empty(self) -> None:
        """Test that empty string returns None."""
        assert FieldTransformer.normalize_signon_mode("") is None
        assert FieldTransformer.normalize_signon_mode("   ") is None


class TestCoerceBool:
    """Tests for boolean coercion."""

    def test_coerce_bool_native(self) -> None:
        """Test native boolean values."""
        assert FieldTransformer._coerce_bool(True, default=False) is True
        assert FieldTransformer._coerce_bool(False, default=True) is False

    def test_coerce_bool_string_true(self) -> None:
        """Test string values coerced to True."""
        assert FieldTransformer._coerce_bool("true", default=False) is True
        assert FieldTransformer._coerce_bool("TRUE", default=False) is True
        assert FieldTransformer._coerce_bool("1", default=False) is True
        assert FieldTransformer._coerce_bool("yes", default=False) is True
        assert FieldTransformer._coerce_bool("y", default=False) is True

    def test_coerce_bool_string_false(self) -> None:
        """Test string values coerced to False."""
        assert FieldTransformer._coerce_bool("false", default=True) is False
        assert FieldTransformer._coerce_bool("FALSE", default=True) is False
        assert FieldTransformer._coerce_bool("0", default=True) is False
        assert FieldTransformer._coerce_bool("no", default=True) is False
        assert FieldTransformer._coerce_bool("n", default=True) is False

    def test_coerce_bool_default(self) -> None:
        """Test that default is used for None and unknown strings."""
        assert FieldTransformer._coerce_bool(None, default=True) is True
        assert FieldTransformer._coerce_bool(None, default=False) is False
        assert FieldTransformer._coerce_bool("unknown", default=True) is True
        assert FieldTransformer._coerce_bool("unknown", default=False) is False

    def test_coerce_bool_numeric(self) -> None:
        """Test numeric values."""
        assert FieldTransformer._coerce_bool(1, default=False) is True
        assert FieldTransformer._coerce_bool(0, default=True) is False


class TestCleanPayload:
    """Tests for payload cleaning."""

    def test_clean_payload_removes_none(self) -> None:
        """Test that None values are removed."""
        payload = {
            "name": "Test",
            "value": None,
            "count": 0,
        }
        result = FieldTransformer.clean_payload(payload)
        assert "name" in result
        assert "value" not in result
        assert "count" in result

    def test_clean_payload_removes_empty_strings(self) -> None:
        """Test that empty strings are removed."""
        payload = {
            "name": "Test",
            "empty": "",
            "whitespace": "   ",
            "valid": "value",
        }
        result = FieldTransformer.clean_payload(payload)
        assert "name" in result
        assert "empty" not in result
        assert "whitespace" not in result
        assert "valid" in result

    def test_clean_payload_preserves_zero(self) -> None:
        """Test that zero values are preserved."""
        payload = {
            "count": 0,
            "amount": 0.0,
            "flag": False,
        }
        result = FieldTransformer.clean_payload(payload)
        assert result["count"] == 0
        assert result["amount"] == 0.0
        assert result["flag"] is False
