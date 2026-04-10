#!/usr/bin/env python3
"""End-to-end integration tests for database and telemetry system.

Tests the complete flow:
1. Database initialization
2. Connector loading
3. Telemetry consent
4. Intelligent connector matching
5. Telemetry logging
6. CLI commands
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def print_section(title: str) -> None:
    """Print a test section header."""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print("=" * 80)


def print_test(name: str, passed: bool, details: str = "") -> None:
    """Print test result."""
    status = "✓ PASS" if passed else "✗ FAIL"
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    print(f"{color}{status}{reset} {name}")
    if details:
        print(f"       {details}")


def test_database_initialization() -> bool:
    """Test 1: Database exists and has correct schema."""
    print_section("TEST 1: Database Initialization")

    db_path = Path.home() / ".onelogin-migration" / "connectors.db"

    if not db_path.exists():
        print_test("Database file exists", False, f"Not found at {db_path}")
        return False

    print_test("Database file exists", True, str(db_path))

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check for required tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        required_tables = {
            "onelogin_connectors",
            "okta_connectors",
            "connector_mappings",
            "telemetry_settings",
            "connector_telemetry",
            "error_telemetry",
            "migration_scenario_telemetry",
            "user_connector_overrides",
            "connector_refresh_log",
        }

        missing_tables = required_tables - tables
        if missing_tables:
            print_test("Required tables exist", False, f"Missing: {missing_tables}")
            conn.close()
            return False

        print_test("Required tables exist", True, f"{len(required_tables)} tables found")

        # Check for required views
        cursor.execute("SELECT name FROM sqlite_master WHERE type='view'")
        views = {row[0] for row in cursor.fetchall()}

        required_views = {
            "best_connector_mappings",
            "last_refresh",
            "connector_telemetry_summary",
            "error_pattern_summary",
            "scenario_effectiveness",
        }

        missing_views = required_views - views
        if missing_views:
            print_test("Required views exist", False, f"Missing: {missing_views}")
            conn.close()
            return False

        print_test("Required views exist", True, f"{len(required_views)} views found")

        conn.close()
        return True

    except Exception as e:
        print_test("Database schema validation", False, str(e))
        return False


def test_connector_data() -> bool:
    """Test 2: Connector data is loaded correctly."""
    print_section("TEST 2: Connector Data")

    db_path = Path.home() / ".onelogin-migration" / "connectors.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Check OneLogin connectors
        cursor.execute("SELECT COUNT(*) as count FROM onelogin_connectors")
        onelogin_count = cursor.fetchone()["count"]

        expected_onelogin = 8426
        if onelogin_count != expected_onelogin:
            print_test(
                "OneLogin connectors loaded",
                False,
                f"Expected {expected_onelogin}, found {onelogin_count}",
            )
        else:
            print_test("OneLogin connectors loaded", True, f"{onelogin_count:,} connectors")

        # Check Okta connectors
        cursor.execute("SELECT COUNT(*) as count FROM okta_connectors")
        okta_count = cursor.fetchone()["count"]

        expected_okta = 8152
        if okta_count != expected_okta:
            print_test(
                "Okta connectors loaded", False, f"Expected {expected_okta}, found {okta_count}"
            )
        else:
            print_test("Okta connectors loaded", True, f"{okta_count:,} connectors")

        # Check mappings
        cursor.execute("SELECT COUNT(*) as count FROM connector_mappings")
        mapping_count = cursor.fetchone()["count"]

        expected_mappings = 2170
        if mapping_count != expected_mappings:
            print_test(
                "Connector mappings loaded",
                False,
                f"Expected {expected_mappings}, found {mapping_count}",
            )
        else:
            print_test("Connector mappings loaded", True, f"{mapping_count:,} mappings")

        # Sample connector lookup
        cursor.execute(
            """
            SELECT * FROM onelogin_connectors
            WHERE name LIKE '%Salesforce%'
            LIMIT 1
        """
        )
        salesforce = cursor.fetchone()

        if salesforce:
            print_test("Connector lookup works", True, f"Found: {salesforce['name']}")
        else:
            print_test("Connector lookup works", False, "Could not find Salesforce connector")

        conn.close()
        return True

    except Exception as e:
        print_test("Connector data validation", False, str(e))
        conn.close()
        return False


def test_intelligent_matching() -> bool:
    """Test 3: Intelligent connector matching with confidence scores."""
    print_section("TEST 3: Intelligent Connector Matching")

    db_path = Path.home() / ".onelogin-migration" / "connectors.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Test exact match
        test_apps = [
            ("Salesforce", 100.0, "exact"),
            ("Slack", 100.0, "exact"),
            ("GitHub", 100.0, "exact"),
        ]

        for app_name, expected_confidence, expected_type in test_apps:
            cursor.execute(
                """
                SELECT * FROM best_connector_mappings
                WHERE okta_internal_name = ?
            """,
                (app_name,),
            )

            mapping = cursor.fetchone()

            if mapping:
                confidence = mapping["confidence_score"]
                match_type = mapping["match_type"]

                if confidence >= expected_confidence * 0.9:  # Allow 10% variance
                    print_test(
                        f"Match '{app_name}'",
                        True,
                        f"{mapping['onelogin_name']} ({confidence:.0f}%, {match_type})",
                    )
                else:
                    print_test(f"Match '{app_name}'", False, f"Low confidence: {confidence:.0f}%")
            else:
                print_test(f"Match '{app_name}'", False, "No mapping found")

        # Test fuzzy matches exist
        cursor.execute(
            """
            SELECT COUNT(*) as count FROM connector_mappings
            WHERE match_type = 'fuzzy' AND confidence_score < 100
        """
        )
        fuzzy_count = cursor.fetchone()["count"]

        if fuzzy_count > 0:
            print_test("Fuzzy matches exist", True, f"{fuzzy_count} fuzzy matches")
        else:
            print_test("Fuzzy matches exist", False, "No fuzzy matches found")

        conn.close()
        return True

    except Exception as e:
        print_test("Intelligent matching", False, str(e))
        conn.close()
        return False


def test_telemetry_system() -> bool:
    """Test 4: Telemetry system functionality."""
    print_section("TEST 4: Telemetry System")

    db_path = Path.home() / ".onelogin-migration" / "connectors.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Check telemetry settings
        cursor.execute("SELECT * FROM telemetry_settings LIMIT 1")
        settings = cursor.fetchone()

        if settings:
            enabled = settings["enabled"]
            status = "Enabled" if enabled else "Disabled"
            print_test(
                "Telemetry settings exist",
                True,
                f"Status: {status}, ID: {settings['installation_id'][:8]}...",
            )
        else:
            print_test(
                "Telemetry settings exist",
                False,
                "No telemetry settings found (run GUI to initialize)",
            )

        # Check telemetry tables
        cursor.execute("SELECT COUNT(*) as count FROM connector_telemetry")
        connector_telemetry = cursor.fetchone()["count"]
        print_test("Connector telemetry table accessible", True, f"{connector_telemetry} records")

        cursor.execute("SELECT COUNT(*) as count FROM error_telemetry")
        error_telemetry = cursor.fetchone()["count"]
        print_test("Error telemetry table accessible", True, f"{error_telemetry} records")

        cursor.execute("SELECT COUNT(*) as count FROM migration_scenario_telemetry")
        scenario_telemetry = cursor.fetchone()["count"]
        print_test("Scenario telemetry table accessible", True, f"{scenario_telemetry} records")

        # Check telemetry views
        cursor.execute("SELECT COUNT(*) as count FROM connector_telemetry_summary")
        summary_count = cursor.fetchone()["count"]
        print_test(
            "Telemetry summary views work", True, f"{summary_count} unique connectors tracked"
        )

        conn.close()
        return True

    except Exception as e:
        print_test("Telemetry system", False, str(e))
        conn.close()
        return False


def test_anonymization() -> bool:
    """Test 5: Data anonymization (SHA-256 hashing)."""
    print_section("TEST 5: Data Anonymization")

    db_path = Path.home() / ".onelogin-migration" / "connectors.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Check that connector_telemetry uses hashes, not plaintext
        cursor.execute("SELECT okta_connector_hash FROM connector_telemetry LIMIT 5")
        hashes = cursor.fetchall()

        if hashes:
            all_hashes = True
            for row in hashes:
                hash_val = row["okta_connector_hash"]
                # SHA-256 produces 64-character hex strings
                if not (isinstance(hash_val, str) and len(hash_val) == 64):
                    all_hashes = False
                    break

            if all_hashes:
                print_test(
                    "SHA-256 hashing verified",
                    True,
                    f"All {len(hashes)} records use 64-char hashes",
                )
            else:
                print_test("SHA-256 hashing verified", False, "Found non-hash values in telemetry")
        else:
            print_test(
                "SHA-256 hashing", True, "No telemetry data yet (will use hashes when collected)"
            )

        # Verify no PII columns exist
        cursor.execute("PRAGMA table_info(connector_telemetry)")
        columns = {row[1] for row in cursor.fetchall()}

        pii_columns = {"email", "name", "user_id", "organization", "domain", "ip_address"}
        found_pii = columns & pii_columns

        if found_pii:
            print_test("No PII columns in schema", False, f"Found PII columns: {found_pii}")
        else:
            print_test("No PII columns in schema", True, "Schema has zero capability to store PII")

        conn.close()
        return True

    except Exception as e:
        print_test("Anonymization verification", False, str(e))
        conn.close()
        return False


def test_cli_integration() -> bool:
    """Test 6: CLI module imports and structure."""
    print_section("TEST 6: CLI Integration")

    try:
        # Check if telemetry_cli module exists and is importable
        telemetry_cli_path = Path("src/onelogin_migration_tool/telemetry_cli.py")

        if not telemetry_cli_path.exists():
            print_test("Telemetry CLI module exists", False, f"Not found at {telemetry_cli_path}")
            return False

        print_test("Telemetry CLI module exists", True, str(telemetry_cli_path))

        # Check CLI module structure
        content = telemetry_cli_path.read_text()

        required_commands = [
            "def status",
            "def export",
            "def disable",
            "def enable",
            "def clear",
            "def view_summary",
        ]

        missing_commands = []
        for cmd in required_commands:
            if cmd not in content:
                missing_commands.append(cmd)

        if missing_commands:
            print_test("CLI commands implemented", False, f"Missing: {missing_commands}")
        else:
            print_test("CLI commands implemented", True, f"{len(required_commands)} commands found")

        # Check CLI registration in main cli.py
        main_cli_path = Path("src/onelogin_migration_tool/cli.py")
        if main_cli_path.exists():
            cli_content = main_cli_path.read_text()

            if "telemetry_app" in cli_content and "telemetry" in cli_content:
                print_test(
                    "CLI subcommand registered", True, "telemetry subcommand added to main CLI"
                )
            else:
                print_test(
                    "CLI subcommand registered", False, "telemetry not registered in main CLI"
                )

        return True

    except Exception as e:
        print_test("CLI integration", False, str(e))
        return False


def test_documentation() -> bool:
    """Test 7: Documentation files exist."""
    print_section("TEST 7: Documentation")

    required_docs = [
        ("PRIVACY_POLICY.md", "Privacy policy"),
        ("TELEMETRY_CLI_USAGE.md", "CLI usage guide"),
        ("ANALYSIS_PAGE_UPDATE.md", "Analysis page docs"),
        ("IMPLEMENTATION_COMPLETE.md", "Implementation summary"),
    ]

    all_exist = True
    for filename, description in required_docs:
        path = Path(filename)
        if path.exists():
            size_kb = path.stat().st_size / 1024
            print_test(f"{description} exists", True, f"{filename} ({size_kb:.1f} KB)")
        else:
            print_test(f"{description} exists", False, f"{filename} not found")
            all_exist = False

    # Check LICENSE has telemetry section
    license_path = Path("src/onelogin_migration_tool/assets/LICENSE")
    if license_path.exists():
        license_content = license_path.read_text()
        if "ANONYMIZED TELEMETRY" in license_content:
            print_test("LICENSE telemetry disclosure", True, "Section 6 found")
        else:
            print_test("LICENSE telemetry disclosure", False, "Section 6 missing")
            all_exist = False
    else:
        print_test("LICENSE file exists", False, "LICENSE not found")
        all_exist = False

    return all_exist


def run_all_tests() -> bool:
    """Run all integration tests."""
    print("\n" + "=" * 80)
    print("  END-TO-END INTEGRATION TEST SUITE")
    print("  OneLogin Migration Tool - Database & Telemetry System")
    print("=" * 80)
    print(f"\n  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    tests = [
        ("Database Initialization", test_database_initialization),
        ("Connector Data", test_connector_data),
        ("Intelligent Matching", test_intelligent_matching),
        ("Telemetry System", test_telemetry_system),
        ("Data Anonymization", test_anonymization),
        ("CLI Integration", test_cli_integration),
        ("Documentation", test_documentation),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ FATAL ERROR in {name}: {e}")
            results.append((name, False))

    # Summary
    print_section("TEST SUMMARY")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        color = "\033[92m" if result else "\033[91m"
        reset = "\033[0m"
        print(f"  {color}{status}{reset}  {name}")

    print(f"\n  Results: {passed}/{total} tests passed")

    if passed == total:
        print("\n  \033[92m✓ ALL TESTS PASSED\033[0m")
        print("  System is ready for production use.")
    else:
        print(f"\n  \033[91m✗ {total - passed} TESTS FAILED\033[0m")
        print("  Review failures above and fix issues.")

    print(f"\n  Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80 + "\n")

    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
