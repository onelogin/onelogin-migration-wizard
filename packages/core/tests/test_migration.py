from pathlib import Path

import pytest
from onelogin_migration_core.manager import MigrationAborted, MigrationManager

from onelogin_migration_core.clients import OktaClient
from onelogin_migration_core.config import MigrationSettings, OktaApiSettings
from onelogin_migration_core.progress import MigrationProgress

STATE_FILE = Path("artifacts/migration_state.json")


@pytest.fixture(autouse=True)
def cleanup_state_file() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    yield
    if STATE_FILE.exists():
        STATE_FILE.unlink()


class DummyOktaClient:
    pass


class DummyOneLoginClient:
    def __init__(self) -> None:
        self.dry_run = False
        self.roles: list[dict] = []
        self.users: list[dict] = []
        self.apps: list[dict] = []
        self.assignments: list[tuple[int, int]] = []
        self.user_role_assignments: list[tuple[int, int]] = []
        self.custom_attribute_definitions: set[str] = set()

    def ensure_role(self, payload: dict) -> dict:
        self.roles.append(payload)
        return {"id": len(self.roles)}

    def ensure_user(self, payload: dict) -> dict:
        custom_attributes = payload.get("custom_attributes")
        if isinstance(custom_attributes, dict) and custom_attributes:
            missing = set(custom_attributes) - self.custom_attribute_definitions
            if missing:
                raise AssertionError(
                    f"Custom attributes not ensured before user creation: {missing}"
                )
        self.users.append(payload)
        return {"id": len(self.users)}

    def ensure_application(self, payload: dict) -> dict:
        if "appConnectorId" in payload:
            raise AssertionError("Payload should not contain Okta appConnectorId values")
        self.apps.append(payload)
        return {"id": len(self.apps)}

    def assign_role_to_app(self, app_id: int, role_id: int) -> None:
        self.assignments.append((int(app_id), int(role_id)))

    def assign_user_to_role(self, user_id: int, role_id: int) -> None:
        self.user_role_assignments.append((int(user_id), int(role_id)))

    def assign_users_to_role_bulk(self, role_id: int, user_ids: set) -> None:
        for user_id in user_ids:
            self.user_role_assignments.append((int(user_id), int(role_id)))

    def ensure_custom_attribute_definitions(self, custom_attributes: dict) -> None:
        if isinstance(custom_attributes, dict):
            self.custom_attribute_definitions.update(custom_attributes.keys())


def test_okta_export_all_skips_unselected_categories() -> None:
    client = OktaClient(OktaApiSettings(domain="example.okta.com", token="token"))
    calls: list[str] = []

    def record(name, value):
        def _inner(*_, **__):
            calls.append(name)
            return value

        return _inner

    client.list_users = record("users", [{"id": "u1"}])  # type: ignore[assignment]
    client.list_groups = record("groups", [{"id": "g1"}])  # type: ignore[assignment]
    client.list_group_memberships = record("memberships", [{"group_id": "g1", "user_id": "u1"}])  # type: ignore[assignment]
    client.list_applications = record("applications", [{"id": "app1"}])  # type: ignore[assignment]

    export = client.export_all({"users": False, "groups": False, "applications": True})

    assert calls == ["applications"]
    assert export["users"] == []
    assert export["groups"] == []
    assert export["memberships"] == []
    assert export["applications"] == [{"id": "app1"}]


def test_okta_export_all_avoids_memberships_without_users() -> None:
    client = OktaClient(OktaApiSettings(domain="example.okta.com", token="token"))
    calls: list[str] = []

    def record(name, value):
        def _inner(*_, **__):
            calls.append(name)
            return value

        return _inner

    groups = [{"id": "g1"}]

    client.list_users = record("users", [{"id": "u1"}])  # type: ignore[assignment]
    client.list_groups = record("groups", groups)  # type: ignore[assignment]

    def memberships_stub(*_, **__):
        calls.append("memberships")
        return [{"group_id": "g1", "user_id": "u1"}]

    client.list_group_memberships = memberships_stub  # type: ignore[assignment]
    client.list_applications = record("applications", [])  # type: ignore[assignment]

    export = client.export_all({"users": False, "groups": True, "applications": False})

    assert calls == ["groups"]
    assert export["groups"] == groups
    assert export["memberships"] == []


def test_okta_export_all_fetches_memberships_when_enabled() -> None:
    client = OktaClient(OktaApiSettings(domain="example.okta.com", token="token"))
    calls: list[str] = []
    groups = [{"id": "g1"}]
    memberships = [{"group_id": "g1", "user_id": "u1"}]
    captured_groups = None

    def record(name, value):
        def _inner(*_, **__):
            calls.append(name)
            return value

        return _inner

    client.list_users = record("users", [{"id": "u1"}])  # type: ignore[assignment]
    client.list_groups = record("groups", groups)  # type: ignore[assignment]

    def memberships_stub(passed_groups=None, *_args, **_kwargs):
        nonlocal captured_groups
        calls.append("memberships")
        captured_groups = passed_groups
        return memberships

    client.list_group_memberships = memberships_stub  # type: ignore[assignment]
    client.list_applications = record("applications", [])  # type: ignore[assignment]

    export = client.export_all({"users": True, "groups": True, "applications": False})

    assert calls == ["users", "groups", "memberships"]
    assert captured_groups == groups
    assert export["memberships"] == memberships


def test_import_processes_entities_and_updates_progress() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": False,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
            "metadata": {
                "application_connectors": {
                    "ExampleApp": {"SAML_2_0": 90001},
                }
            },
        }
    )
    progress = MigrationProgress(categories=("users", "groups", "applications"))
    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=DummyOneLoginClient(),
        progress=progress,
        dry_run=False,
    )

    export = {
        "groups": [
            {"id": "1", "profile": {"name": "Admins", "description": "Okta group"}},
        ],
        "users": [
            {
                "id": "10",
                "status": "ACTIVE",
                "profile": {
                    "firstName": "Ada",
                    "lastName": "Lovelace",
                    "email": "ada@example.com",
                    "login": "ada",
                },
            }
        ],
        "applications": [
            {
                "id": "app1",
                "label": "ExampleApp",
                "signOnMode": "SAML_2_0",
                "_embedded": {
                    "group": [
                        {
                            "id": "1",
                            "profile": {"name": "Admins"},
                        }
                    ]
                },
            }
        ],
    }

    manager.import_into_onelogin(export)

    snapshot = progress.snapshot()
    assert snapshot.completed["groups"] == 1
    assert snapshot.completed["users"] == 1
    assert snapshot.completed["applications"] == 1
    assert manager.onelogin.assignments == [(1, 1)]


def test_run_reuses_export_after_stop(tmp_path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    settings = MigrationSettings.from_dict(
        {
            "dry_run": False,
            "export_directory": str(export_dir),
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )

    class RecordingOktaClient:
        def __init__(self) -> None:
            self.calls = 0

        def export_all(self, _categories) -> dict:
            self.calls += 1
            return {"users": [], "groups": [], "applications": [], "memberships": []}

    class StopAfterImport(MigrationManager):
        stop_before_import = False

        def import_into_onelogin(self, export):
            if self.stop_before_import:
                self.request_stop()
            return super().import_into_onelogin(export)

    okta_client = RecordingOktaClient()
    onelogin_client = DummyOneLoginClient()
    manager = StopAfterImport(
        settings,
        okta_client=okta_client,  # type: ignore[arg-type]
        onelogin_client=onelogin_client,
        dry_run=False,
    )

    manager.stop_before_import = True
    manager.run()
    assert okta_client.calls == 1
    assert manager.was_stopped() is True

    manager.stop_before_import = False
    manager.run()
    assert okta_client.calls == 1  # cached export reused
    assert manager.was_stopped() is False
    assert not (export_dir / "migration_state.json").exists()


def test_import_resumes_without_repeating_completed_items(tmp_path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    settings = MigrationSettings.from_dict(
        {
            "dry_run": False,
            "export_directory": str(export_dir),
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )

    export = {
        "groups": [
            {"id": "1", "profile": {"name": "Admins"}},
            {"id": "2", "profile": {"name": "Developers"}},
        ],
        "users": [],
        "applications": [],
        "memberships": [],
    }

    class InterruptingOneLoginClient(DummyOneLoginClient):
        def __init__(self, mgr: MigrationManager) -> None:
            super().__init__()
            self.manager = mgr
            self.should_stop = True

        def ensure_role(self, payload: dict) -> dict:  # type: ignore[override]
            response = super().ensure_role(payload)
            if self.should_stop:
                self.should_stop = False
                self.manager.request_stop()
            return response

    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=DummyOneLoginClient(),
        dry_run=False,
    )

    interrupt_client = InterruptingOneLoginClient(manager)
    manager.onelogin = interrupt_client  # type: ignore[assignment]

    manager.progress.reset()
    try:
        manager.import_into_onelogin(export)
    except MigrationAborted:
        pass
    assert manager.was_stopped() is True
    assert len(interrupt_client.roles) == 1

    manager.reset_stop_request()
    manager.progress.reset()
    interrupt_client.should_stop = False
    manager.import_into_onelogin(export)

    assert len(interrupt_client.roles) == 2
    assert interrupt_client.user_role_assignments == []
    # ensure first group was not reprocessed
    assert interrupt_client.roles[0]["name"] == "Admins"
    assert interrupt_client.roles[1]["name"] == "Developers"
    assert manager.was_stopped() is False


def test_set_threading_updates_settings(tmp_path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    settings = MigrationSettings.from_dict(
        {
            "dry_run": False,
            "export_directory": str(export_dir),
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )

    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=DummyOneLoginClient(),
        dry_run=False,
    )

    manager.set_threading(True, 5)

    assert manager.settings.concurrency_enabled is True
    assert manager.settings.max_workers == 5


def test_bulk_user_upload_generates_csv(tmp_path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    settings = MigrationSettings.from_dict(
        {
            "dry_run": False,
            "bulk_user_upload": True,
            "export_directory": str(export_dir),
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )

    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=DummyOneLoginClient(),
        dry_run=False,
    )

    export = {
        "users": [
            {
                "id": "10",
                "status": "ACTIVE",
                "profile": {
                    "firstName": "Ada",
                    "lastName": "Lovelace",
                    "email": "ada@example.com",
                    "login": "ada",
                    "favoriteColor": "Teal",
                },
            }
        ],
    }

    manager.import_into_onelogin(export)

    files = list(export_dir.glob("bulk_user_upload_*.csv"))
    assert len(files) == 1
    content = files[0].read_text().splitlines()
    assert content, "CSV should contain header row"
    headers = content[0].split(",")
    assert "favorite_color" in headers
    rows = content[1:]
    assert rows and "Ada" in rows[0]
    assert "Teal" in rows[0]

    snapshot = manager.progress.snapshot()
    assert snapshot.completed["users"] == 1
    assert manager.onelogin.users == []
    assert manager.last_bulk_export == files[0]
    assert "favorite_color" in manager.onelogin.custom_attribute_definitions


def test_transform_application_uses_connector_lookup_and_configuration() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": True,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
            "metadata": {
                "application_connectors": {
                    "Custom App": {"SAML_2_0": 55555},
                }
            },
        }
    )
    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=DummyOneLoginClient(),
        dry_run=True,
    )

    okta_app = {
        "label": "Custom App",
        "signOnMode": "SAML_2_0",
        "settings": {
            "appNotes": "Important app",
            "appVisible": "false",
            "appSettingsJson": {"audience": "https://example.com/audience"},
            "appUrl": "https://example.com/login",
        },
        "parameters": {"field": {"value": "abc"}},
    }

    payload = manager._transform_application(okta_app)  # type: ignore[attr-defined]
    assert payload is not None
    assert payload["connector_id"] == 55555
    assert payload["visible"] is False
    assert payload["configuration"] == {
        "audience": "https://example.com/audience",
        "url": "https://example.com/login",
    }
    assert payload["parameters"] == okta_app["parameters"]
    assert payload.get("signon_mode") == "SAML_2_0"
    assert "appConnectorId" not in payload


def test_transform_application_supports_generic_connector_mapping() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": True,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
            "metadata": {
                "application_connectors": {
                    "Shared App": 44444,
                }
            },
        }
    )
    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=DummyOneLoginClient(),
        dry_run=True,
    )

    okta_app = {
        "label": "Shared  App",
        "signOnMode": "OPENID_CONNECT",
    }

    payload = manager._transform_application(okta_app)  # type: ignore[attr-defined]
    assert payload is not None
    assert payload["connector_id"] == 44444
    assert payload["visible"] is True


def test_import_skips_app_without_connector_mapping() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": False,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )
    progress = MigrationProgress(categories=("applications",))
    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=DummyOneLoginClient(),
        progress=progress,
        dry_run=False,
    )

    export = {
        "applications": [
            {
                "id": "missing",
                "label": "Unmapped",
                "signOnMode": "SAML_2_0",
            }
        ]
    }

    manager.import_into_onelogin(export)

    assert manager.onelogin.apps == []
    assert progress.snapshot().completed["applications"] == 1


def test_import_assigns_user_roles_from_memberships() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": False,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )
    progress = MigrationProgress(categories=("users", "groups"))
    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=DummyOneLoginClient(),
        progress=progress,
        dry_run=False,
    )

    export = {
        "groups": [
            {"id": "g1", "profile": {"name": "Staff"}},
        ],
        "users": [
            {
                "id": "user-1",
                "status": "ACTIVE",
                "profile": {
                    "firstName": "Grace",
                    "lastName": "Hopper",
                    "email": "grace@example.com",
                    "login": "grace",
                },
            }
        ],
        "memberships": [
            {"group_id": "g1", "user_id": "user-1"},
        ],
    }

    manager.import_into_onelogin(export)

    assert manager.onelogin.user_role_assignments == [(1, 1)]


def test_import_ensures_custom_attribute_definitions_before_creating_user() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": False,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
            "categories": {"groups": False, "applications": False},
        }
    )
    progress = MigrationProgress(categories=("users",))
    onelogin_client = DummyOneLoginClient()
    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=onelogin_client,
        progress=progress,
        dry_run=False,
    )

    export = {
        "users": [
            {
                "id": "custom-1",
                "status": "ACTIVE",
                "profile": {
                    "firstName": "Casey",
                    "lastName": "Custom",
                    "email": "casey.custom@example.com",
                    "login": "casey.custom",
                    "city": "Austin",
                    "state": "TX",
                    "streetAddress": "1 Congress Ave",
                    "zipCode": "78701",
                    "countryCode": "US",
                    "favoriteColor": "Purple",
                    "Cost Center": 1001,
                    "manager": {"id": "skip"},
                },
            }
        ]
    }

    manager.import_into_onelogin(export)

    expected_keys = {
        "street_address",
        "city",
        "state",
        "zip_code",
        "country_code",
        "favorite_color",
        "cost_center",
    }
    assert expected_keys.issubset(onelogin_client.custom_attribute_definitions)
    assert progress.snapshot().completed["users"] == 1


def test_roles_for_app_resolves_enriched_group_assignments() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": True,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )
    manager = MigrationManager(
        settings,
        okta_client=DummyOktaClient(),
        onelogin_client=DummyOneLoginClient(),
    )

    okta_app = {
        "id": "app-123",
        "_embedded": {
            "group": [
                {"groupId": "1001", "profile": {"name": "Finance"}},
                {"id": "1001", "profile": {"name": "Finance Duplicate"}},
                {"id": "missing"},
            ]
        },
    }

    role_lookup = {"1001": 77}

    assert list(manager._roles_for_app(okta_app, role_lookup)) == [77]


def test_transform_user_promotes_unknown_profile_fields_to_custom_attributes() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": True,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )
    manager = MigrationManager(
        settings, okta_client=DummyOktaClient(), onelogin_client=DummyOneLoginClient()
    )

    okta_user = {
        "id": "dyn-1",
        "status": "ACTIVE",
        "profile": {
            "firstName": "Dynamic",
            "lastName": "User",
            "login": "dynamic.user",
            "favoriteColor": "Blue",
            "Cost Center": 1001,
            "customField123": "value",
            "  spaced field  ": " spaced value ",
            "manager": {"id": "skip"},
            "emptyField": "",
        },
    }

    payload = manager._transform_user(okta_user)  # type: ignore[attr-defined]
    assert payload is not None
    custom_attributes = payload.get("custom_attributes")
    assert custom_attributes is not None
    assert custom_attributes.get("favorite_color") == "Blue"
    assert custom_attributes.get("cost_center") == "1001"
    assert custom_attributes.get("custom_field123") == "value"
    assert custom_attributes.get("spaced_field") == " spaced value "
    assert "manager" not in custom_attributes
    assert "empty_field" not in custom_attributes


def test_transform_user_maps_contact_fields_correctly() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": True,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )
    # Use dummy clients but we won't call import; we'll call the private method for mapping
    manager = MigrationManager(
        settings, okta_client=DummyOktaClient(), onelogin_client=DummyOneLoginClient()
    )

    okta_user = {
        "id": "u1",
        "status": "ACTIVE",
        "profile": {
            "firstName": "Bob",
            "lastName": "Sky",
            "email": "bob@example.com",
            "login": "bob",
            "secondEmail": "bob.secondary@example.com",
            "mobilePhone": "+1 555 123 4567",
            "primaryPhone": "+1 555 000 1111",
            "department": "Engineering",
            "title": "Architect",
            "company": "Acme Corp",
            "preferredLocale": "en-US",
            "streetAddress": "123 Main St",
            "city": "Austin",
            "state": "TX",
            "zipCode": "73301",
            "countryCode": "US",
        },
    }

    payload = manager._transform_user(okta_user)  # type: ignore[attr-defined]
    assert payload is not None
    # Standard fields present with snake_case
    assert payload.get("firstname") == "Bob"
    assert payload.get("lastname") == "Sky"
    assert payload.get("email") == "bob@example.com"
    assert payload.get("username") == "bob"
    assert "second_email" not in payload
    assert payload.get("mobile_phone") == "+1 555 123 4567"
    assert payload.get("phone") == "+1 555 000 1111"
    # No camelCase leftovers
    assert "secondEmail" not in payload
    assert "mobilePhone" not in payload
    # Location metadata should be surfaced via custom attributes
    custom_attributes = payload.get("custom_attributes")
    assert custom_attributes is not None
    assert custom_attributes.get("street_address") == "123 Main St"
    assert custom_attributes.get("city") == "Austin"
    assert custom_attributes.get("state") == "TX"
    assert custom_attributes.get("zip_code") == "73301"
    assert custom_attributes.get("country_code") == "US"
    assert "city" not in payload
    # Account state should reflect activation status, not geographic info
    assert payload.get("state") == 1
    assert "zip" not in payload
    # Department should map to top-level
    assert payload.get("department") == "Engineering"
    assert payload.get("title") == "Architect"
    assert payload.get("company") == "Acme Corp"
    assert payload.get("preferred_locale_code") == "en-US"
    assert payload.get("status") == 1
    assert payload.get("external_id") == "u1"
    assert payload.get("samaccountname") == "bob"
    assert payload.get("userprincipalname") == "bob@example.com"


def test_transform_user_falls_back_to_credentials_and_secondary_fields() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": True,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )
    manager = MigrationManager(
        settings, okta_client=DummyOktaClient(), onelogin_client=DummyOneLoginClient()
    )

    okta_user = {
        "id": "user-123",
        "status": "STAGED",
        "profile": {
            "firstName": "Test",
            "lastName": "User",
            "login": "test.user",
            "secondEmail": "secondary@example.com",
            "streetAddress": "500 Secondary Rd",
            "city": "Springfield",
            "state": "IL",
            "postalCode": "62704",
            "country": "United States",
            "preferredLanguage": "en-US",
        },
        "credentials": {
            "emails": [
                {"value": "primary.from.credentials@example.com"},
            ]
        },
    }

    payload = manager._transform_user(okta_user)  # type: ignore[attr-defined]
    assert payload is not None
    # Email should prefer credentials when profile email missing
    assert payload.get("email") == "primary.from.credentials@example.com"
    # Username falls back to login
    assert payload.get("username") == "test.user"
    # Secondary fields should populate address metadata
    custom_attributes = payload.get("custom_attributes")
    assert custom_attributes is not None
    assert custom_attributes.get("street_address") == "500 Secondary Rd"
    assert custom_attributes.get("city") == "Springfield"
    assert custom_attributes.get("state") == "IL"
    assert custom_attributes.get("zip_code") == "62704"
    assert custom_attributes.get("country") == "United States"
    assert payload.get("preferred_locale_code") == "en-US"
    # STAGED users should be inactive in OneLogin
    assert payload.get("status") == 0
    assert payload.get("state") == 0
    assert payload.get("external_id") == "user-123"


def test_transform_user_uses_secondary_email_if_no_other_option() -> None:
    settings = MigrationSettings.from_dict(
        {
            "dry_run": True,
            "okta": {"domain": "example.okta.com", "token": "token"},
            "onelogin": {"client_id": "id", "client_secret": "secret"},
        }
    )
    manager = MigrationManager(
        settings, okta_client=DummyOktaClient(), onelogin_client=DummyOneLoginClient()
    )

    okta_user = {
        "id": "user-456",
        "status": "ACTIVE",
        "profile": {
            "firstName": "Only",
            "lastName": "Secondary",
            "login": "secondary.user",
            "secondEmail": "secondary-only@example.com",
        },
    }

    payload = manager._transform_user(okta_user)  # type: ignore[attr-defined]
    assert payload is not None
    assert payload.get("email") == "secondary-only@example.com"
    assert payload.get("username") == "secondary.user"
    custom_attributes = payload.get("custom_attributes")
    assert custom_attributes is not None
    assert custom_attributes.get("second_email") == "secondary-only@example.com"
    assert payload.get("status") == 1
    assert payload.get("state") == 1
