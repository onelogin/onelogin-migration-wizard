"""Comprehensive tests for custom_attributes module."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from onelogin_migration_core.custom_attributes import CustomAttributeManager


class TestDiscoverCustomAttributes:
    """Tests for discover_custom_attributes method."""

    def test_discover_basic_custom_attributes(self) -> None:
        """Test discovering basic custom attributes from users."""
        users = [
            {
                "profile": {
                    "firstName": "John",
                    "lastName": "Doe",
                    "email": "john@example.com",
                    "employeeNumber": "E12345",
                    "customField1": "value1",
                }
            }
        ]

        result = CustomAttributeManager.discover_custom_attributes(users)

        assert "employee_number" in result
        assert "custom_field1" in result
        # Standard fields should not be included
        assert "first_name" not in result
        assert "last_name" not in result
        assert "email" not in result

    def test_discover_normalizes_attribute_names(self) -> None:
        """Test that attribute names are normalized to snake_case."""
        users = [
            {
                "profile": {
                    "email": "test@example.com",
                    "employeeNumber": "123",
                    "secondEmail": "second@example.com",
                    "displayName": "Test User",
                }
            }
        ]

        result = CustomAttributeManager.discover_custom_attributes(users)

        assert "employee_number" in result
        assert "second_email" in result
        assert "display_name" in result

    def test_discover_skips_null_values(self) -> None:
        """Test that null values are skipped."""
        users = [
            {
                "profile": {
                    "email": "test@example.com",
                    "customField1": None,
                    "customField2": "value",
                }
            }
        ]

        result = CustomAttributeManager.discover_custom_attributes(users)

        assert "custom_field1" not in result
        assert "custom_field2" in result

    def test_discover_skips_empty_strings(self) -> None:
        """Test that empty strings are skipped."""
        users = [
            {
                "profile": {
                    "email": "test@example.com",
                    "customField1": "",
                    "customField2": "   ",
                    "customField3": "valid",
                }
            }
        ]

        result = CustomAttributeManager.discover_custom_attributes(users)

        assert "custom_field1" not in result
        assert "custom_field2" not in result
        assert "custom_field3" in result

    def test_discover_skips_complex_types(self) -> None:
        """Test that arrays and objects are skipped."""
        users = [
            {
                "profile": {
                    "email": "test@example.com",
                    "simpleField": "value",
                    "arrayField": ["item1", "item2"],
                    "objectField": {"key": "value"},
                }
            }
        ]

        result = CustomAttributeManager.discover_custom_attributes(users)

        assert "simple_field" in result
        assert "array_field" not in result
        assert "object_field" not in result

    def test_discover_aggregates_across_users(self) -> None:
        """Test that attributes are discovered from multiple users."""
        users = [
            {
                "profile": {
                    "email": "user1@example.com",
                    "customField1": "value1",
                }
            },
            {
                "profile": {
                    "email": "user2@example.com",
                    "customField2": "value2",
                }
            },
            {
                "profile": {
                    "email": "user3@example.com",
                    "customField1": "another_value",
                    "customField3": "value3",
                }
            },
        ]

        result = CustomAttributeManager.discover_custom_attributes(users)

        assert "custom_field1" in result
        assert "custom_field2" in result
        assert "custom_field3" in result

    def test_discover_with_no_users(self) -> None:
        """Test discovering with empty user list."""
        users: list = []

        result = CustomAttributeManager.discover_custom_attributes(users)

        assert len(result) == 0

    def test_discover_with_invalid_users(self) -> None:
        """Test discovering with invalid user structures."""
        users = [
            "not a dict",
            {"invalid": "structure"},
            {"profile": "not a dict"},
            None,
        ]

        result = CustomAttributeManager.discover_custom_attributes(users)

        assert len(result) == 0

    def test_discover_deduplicates_attributes(self) -> None:
        """Test that duplicate attributes are only counted once."""
        users = [
            {"profile": {"email": "test1@example.com", "customField": "value1"}},
            {"profile": {"email": "test2@example.com", "customField": "value2"}},
            {"profile": {"email": "test3@example.com", "customField": "value3"}},
        ]

        result = CustomAttributeManager.discover_custom_attributes(users)

        # Should only appear once in the set
        assert "custom_field" in result
        assert len([attr for attr in result if attr == "custom_field"]) == 1

    def test_discover_skips_standard_onelogin_fields(self) -> None:
        """Test that known OneLogin standard fields are skipped."""
        users = [
            {
                "profile": {
                    "firstName": "John",
                    "lastName": "Doe",
                    "email": "john@example.com",
                    "login": "john@example.com",
                    "company": "Acme Corp",
                    "department": "Engineering",
                    "title": "Developer",
                    "samAccountName": "jdoe",
                    "customRealField": "custom_value",
                }
            }
        ]

        result = CustomAttributeManager.discover_custom_attributes(users)

        # Only the custom field should be discovered (mobilePhone, primaryPhone become custom attrs)
        assert "custom_real_field" in result
        # All standard fields should be excluded
        assert "first_name" not in result
        assert "last_name" not in result
        assert "email" not in result
        assert "login" not in result
        assert "company" not in result
        assert "department" not in result
        assert "title" not in result
        assert "sam_account_name" not in result


class TestProvisionCustomAttributes:
    """Tests for provision_custom_attributes method."""

    def test_provision_creates_new_attributes(self) -> None:
        """Test provisioning creates new custom attributes."""
        mock_client = Mock()
        mock_client._custom_attribute_cache = set()
        mock_client._load_custom_attribute_cache = Mock()
        mock_client._create_custom_attribute = Mock()

        attributes = {"employee_number", "cost_center", "manager_id"}

        result = CustomAttributeManager.provision_custom_attributes(
            mock_client, attributes
        )

        assert len(result["created"]) == 3
        assert "employee_number" in result["created"]
        assert "cost_center" in result["created"]
        assert "manager_id" in result["created"]
        assert len(result["existing"]) == 0
        assert len(result["failed"]) == 0

        # Verify all attributes were created
        assert mock_client._create_custom_attribute.call_count == 3

    def test_provision_skips_existing_attributes(self) -> None:
        """Test provisioning skips attributes that already exist."""
        mock_client = Mock()
        mock_client._custom_attribute_cache = {"employee_number", "cost_center"}
        mock_client._load_custom_attribute_cache = Mock()
        mock_client._create_custom_attribute = Mock()

        attributes = {"employee_number", "cost_center", "manager_id"}

        result = CustomAttributeManager.provision_custom_attributes(
            mock_client, attributes
        )

        assert len(result["created"]) == 1
        assert "manager_id" in result["created"]
        assert len(result["existing"]) == 2
        assert "employee_number" in result["existing"]
        assert "cost_center" in result["existing"]
        assert len(result["failed"]) == 0

        # Only the new attribute should be created
        assert mock_client._create_custom_attribute.call_count == 1

    def test_provision_handles_creation_errors(self) -> None:
        """Test provisioning handles errors during attribute creation."""
        mock_client = Mock()
        mock_client._custom_attribute_cache = set()
        mock_client._load_custom_attribute_cache = Mock()

        def create_with_error(attr_name: str) -> None:
            if attr_name == "bad_attribute":
                raise Exception("API error: Invalid attribute name")

        mock_client._create_custom_attribute = Mock(side_effect=create_with_error)

        attributes = {"good_attribute", "bad_attribute"}

        result = CustomAttributeManager.provision_custom_attributes(
            mock_client, attributes
        )

        assert len(result["failed"]) == 1
        assert "bad_attribute" in result["failed"]
        assert "API error" in result["failed"]["bad_attribute"]

    def test_provision_with_empty_set(self) -> None:
        """Test provisioning with no attributes."""
        mock_client = Mock()

        attributes: set[str] = set()

        result = CustomAttributeManager.provision_custom_attributes(
            mock_client, attributes
        )

        assert len(result["created"]) == 0
        assert len(result["existing"]) == 0
        assert len(result["failed"]) == 0

    def test_provision_loads_cache_first(self) -> None:
        """Test that provisioning loads the cache before checking."""
        mock_client = Mock()
        mock_client._custom_attribute_cache = set()
        mock_client._load_custom_attribute_cache = Mock()
        mock_client._create_custom_attribute = Mock()

        attributes = {"test_attribute"}

        CustomAttributeManager.provision_custom_attributes(mock_client, attributes)

        # Verify cache was loaded
        mock_client._load_custom_attribute_cache.assert_called_once()

    def test_provision_handles_cache_load_error(self) -> None:
        """Test that provisioning continues even if cache load fails."""
        mock_client = Mock()
        mock_client._custom_attribute_cache = set()
        mock_client._load_custom_attribute_cache = Mock(
            side_effect=Exception("Cache load failed")
        )
        mock_client._create_custom_attribute = Mock()

        attributes = {"test_attribute"}

        # Should not raise, just log warning
        result = CustomAttributeManager.provision_custom_attributes(
            mock_client, attributes
        )

        # Attribute should still be created
        assert len(result["created"]) == 1
        assert "test_attribute" in result["created"]

    def test_provision_result_structure(self) -> None:
        """Test that provision result has correct structure."""
        mock_client = Mock()
        mock_client._custom_attribute_cache = {"existing_attr"}
        mock_client._load_custom_attribute_cache = Mock()

        def create_with_conditional_error(attr_name: str) -> None:
            if attr_name == "fail_attr":
                raise Exception("Creation failed")

        mock_client._create_custom_attribute = Mock(
            side_effect=create_with_conditional_error
        )

        attributes = {"new_attr", "existing_attr", "fail_attr"}

        result = CustomAttributeManager.provision_custom_attributes(
            mock_client, attributes
        )

        # Verify result structure
        assert "created" in result
        assert "existing" in result
        assert "failed" in result
        assert isinstance(result["created"], list)
        assert isinstance(result["existing"], list)
        assert isinstance(result["failed"], dict)

        assert "new_attr" in result["created"]
        assert "existing_attr" in result["existing"]
        assert "fail_attr" in result["failed"]


class TestCustomAttributeManagerIntegration:
    """Integration tests for custom attribute workflows."""

    def test_discover_and_provision_workflow(self) -> None:
        """Test complete workflow of discovering and provisioning attributes."""
        # Sample user data
        users = [
            {
                "profile": {
                    "firstName": "John",
                    "lastName": "Doe",
                    "email": "john@example.com",
                    "employeeNumber": "E001",
                    "costCenter": "CC-100",
                }
            },
            {
                "profile": {
                    "firstName": "Jane",
                    "lastName": "Smith",
                    "email": "jane@example.com",
                    "employeeNumber": "E002",
                    "managerId": "M001",
                }
            },
        ]

        # Discover attributes
        discovered = CustomAttributeManager.discover_custom_attributes(users)

        assert "employee_number" in discovered
        assert "cost_center" in discovered
        assert "manager_id" in discovered

        # Mock client for provisioning
        mock_client = Mock()
        mock_client._custom_attribute_cache = set()
        mock_client._load_custom_attribute_cache = Mock()
        mock_client._create_custom_attribute = Mock()

        # Provision discovered attributes
        result = CustomAttributeManager.provision_custom_attributes(
            mock_client, discovered
        )

        assert len(result["created"]) == 3
        assert all(
            attr in result["created"]
            for attr in ["employee_number", "cost_center", "manager_id"]
        )

    def test_discover_with_varied_data_types(self) -> None:
        """Test discovery handles various data types correctly."""
        users = [
            {
                "profile": {
                    "email": "test@example.com",
                    "stringField": "text",
                    "intField": 42,
                    "floatField": 3.14,
                    "boolField": True,
                    "nullField": None,
                    "emptyField": "",
                    "arrayField": [1, 2, 3],
                    "objectField": {"nested": "data"},
                }
            }
        ]

        discovered = CustomAttributeManager.discover_custom_attributes(users)

        # Simple types should be discovered (will be stringified during transform)
        assert "string_field" in discovered
        assert "int_field" in discovered
        assert "float_field" in discovered
        assert "bool_field" in discovered

        # Complex types and empty values should be skipped
        assert "null_field" not in discovered
        assert "empty_field" not in discovered
        assert "array_field" not in discovered
        assert "object_field" not in discovered

    def test_provision_maintains_sorted_order(self) -> None:
        """Test that provisioning processes attributes in sorted order."""
        mock_client = Mock()
        mock_client._custom_attribute_cache = set()
        mock_client._load_custom_attribute_cache = Mock()

        created_attrs = []

        def track_creation(attr_name: str) -> None:
            created_attrs.append(attr_name)

        mock_client._create_custom_attribute = Mock(side_effect=track_creation)

        attributes = {"zebra", "apple", "mango", "banana"}

        CustomAttributeManager.provision_custom_attributes(mock_client, attributes)

        # Verify attributes were created in sorted order
        assert created_attrs == ["apple", "banana", "mango", "zebra"]
