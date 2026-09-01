"""Pytest collection configuration for the core test suite.

Five files under this directory are standalone diagnostic/verification
scripts, not pytest modules: they contain no test functions and execute
module-level code that calls ``exit()``/``sys.exit()`` at import time,
which aborts pytest collection for the whole suite. Exclude them from
collection so the real tests can run. They remain runnable directly
(``python tests/<name>.py``).
"""

collect_ignore = [
    "test_permissions_fix.py",
    "test_security_complete.py",
    "test_encryption_direct.py",
    "test_load_connectors.py",
    "test_schema_migration.py",
]
