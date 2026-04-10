#!/usr/bin/env python3
"""Simple test script to load connector data without package installation."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from onelogin_migration_core.db.load_connectors import load_all_connectors

if __name__ == "__main__":
    data_dir = Path("/Users/jeffriebudde/Downloads/ol_okta_connectors_analysis")

    print(f"Loading connectors from: {data_dir}")
    print("=" * 60)

    try:
        results = load_all_connectors(data_dir)
        print("\nSUCCESS!")
        print("Database created at: ~/.onelogin-migration/connectors.db")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
