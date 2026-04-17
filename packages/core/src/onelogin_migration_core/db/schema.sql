-- SQLite Schema for OneLogin Migration Tool
-- Version: 1.0
-- Purpose: Store connector catalogs, mappings, and migration telemetry

-- ============================================================================
-- CONNECTOR CATALOGS
-- ============================================================================

-- OneLogin connector catalog
CREATE TABLE IF NOT EXISTS onelogin_connectors (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    icon_url TEXT,
    allows_new_parameters BOOLEAN DEFAULT 0,
    auth_method INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_onelogin_connectors_name ON onelogin_connectors(name);
CREATE INDEX IF NOT EXISTS idx_onelogin_connectors_auth ON onelogin_connectors(auth_method);

-- Okta connector catalog (extracted from internal OIN API)
CREATE TABLE IF NOT EXISTS okta_connectors (
    internal_name TEXT PRIMARY KEY,  -- Okta's internal identifier (e.g., "salesforce")
    display_name TEXT NOT NULL,      -- User-facing name (e.g., "Salesforce")
    label TEXT,                      -- Alternative label
    category TEXT,                   -- App category (e.g., "crm", "hr")
    logo_url TEXT,                   -- App logo URL
    status TEXT,                     -- "ACTIVE", "DEPRECATED", etc.
    sign_on_modes TEXT,              -- JSON array of supported auth methods
    features TEXT,                   -- JSON array of features
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_okta_connectors_name ON okta_connectors(display_name);
CREATE INDEX IF NOT EXISTS idx_okta_connectors_category ON okta_connectors(category);
CREATE INDEX IF NOT EXISTS idx_okta_connectors_status ON okta_connectors(status);

-- ============================================================================
-- CONNECTOR MAPPINGS
-- ============================================================================

-- Mapping between Okta and OneLogin connectors
CREATE TABLE IF NOT EXISTS connector_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    okta_internal_name TEXT NOT NULL,
    okta_display_name TEXT,
    onelogin_id INTEGER NOT NULL,
    onelogin_name TEXT,
    match_type TEXT NOT NULL CHECK(match_type IN ('exact', 'fuzzy', 'manual', 'user_override')),
    confidence_score REAL DEFAULT 100.0 CHECK(confidence_score >= 0 AND confidence_score <= 100),
    source TEXT NOT NULL DEFAULT 'automated' CHECK(source IN ('automated', 'user_corrected', 'verified', 'community')),
    normalized_name TEXT,
    similarity_score REAL,  -- For fuzzy matches
    verified BOOLEAN DEFAULT 0,  -- Has this mapping been verified by a user?
    usage_count INTEGER DEFAULT 0,  -- How many times has this mapping been used?
    success_count INTEGER DEFAULT 0,  -- How many times did migration succeed with this mapping?
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (okta_internal_name) REFERENCES okta_connectors(internal_name),
    FOREIGN KEY (onelogin_id) REFERENCES onelogin_connectors(id)
);

CREATE INDEX IF NOT EXISTS idx_mappings_okta ON connector_mappings(okta_internal_name);
CREATE INDEX IF NOT EXISTS idx_mappings_onelogin ON connector_mappings(onelogin_id);
CREATE INDEX IF NOT EXISTS idx_mappings_type ON connector_mappings(match_type);
CREATE INDEX IF NOT EXISTS idx_mappings_confidence ON connector_mappings(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_mappings_source ON connector_mappings(source);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mappings_unique ON connector_mappings(okta_internal_name, onelogin_id, match_type);

-- ============================================================================
-- TELEMETRY & ANALYTICS
-- ============================================================================

-- Track migration runs
CREATE TABLE IF NOT EXISTS migration_runs (
    id TEXT PRIMARY KEY,  -- UUID for each migration run
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT CHECK(status IN ('started', 'completed', 'failed', 'cancelled')),
    total_users INTEGER DEFAULT 0,
    total_groups INTEGER DEFAULT 0,
    total_apps INTEGER DEFAULT 0,
    migrated_users INTEGER DEFAULT 0,
    migrated_groups INTEGER DEFAULT 0,
    migrated_apps INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    dry_run BOOLEAN DEFAULT 1,
    metadata TEXT  -- JSON blob for additional context
);

CREATE INDEX IF NOT EXISTS idx_migration_runs_started ON migration_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_migration_runs_status ON migration_runs(status);

-- Track individual migration events
CREATE TABLE IF NOT EXISTS migration_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    migration_run_id TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,  -- 'connector_match', 'connector_override', 'error', 'warning', etc.
    entity_type TEXT,  -- 'user', 'group', 'app'
    entity_id TEXT,
    okta_app_name TEXT,
    okta_connector TEXT,
    suggested_onelogin_id INTEGER,
    actual_onelogin_id INTEGER,
    user_accepted BOOLEAN,
    error_message TEXT,
    metadata TEXT,  -- JSON blob for additional details
    FOREIGN KEY (migration_run_id) REFERENCES migration_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_events_run ON migration_events(migration_run_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON migration_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON migration_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_okta_connector ON migration_events(okta_connector);

-- ============================================================================
-- USER PREFERENCES
-- ============================================================================

-- Store user's custom connector preferences
CREATE TABLE IF NOT EXISTS user_connector_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    okta_internal_name TEXT NOT NULL,
    preferred_onelogin_id INTEGER NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(okta_internal_name),
    FOREIGN KEY (okta_internal_name) REFERENCES okta_connectors(internal_name),
    FOREIGN KEY (preferred_onelogin_id) REFERENCES onelogin_connectors(id)
);

CREATE INDEX IF NOT EXISTS idx_overrides_okta ON user_connector_overrides(okta_internal_name);

-- ============================================================================
-- METADATA
-- ============================================================================

-- Track schema version for migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- Insert initial version
INSERT OR IGNORE INTO schema_version (version, description)
VALUES (1, 'Initial schema with connectors, mappings, and telemetry');

-- ============================================================================
-- VIEWS (for convenience)
-- ============================================================================

-- View to get best mapping for each Okta connector
CREATE VIEW IF NOT EXISTS best_connector_mappings AS
SELECT
    okta_internal_name,
    okta_display_name,
    onelogin_id,
    onelogin_name,
    match_type,
    confidence_score,
    source,
    verified,
    usage_count,
    success_count,
    CASE
        WHEN usage_count > 0 THEN CAST(success_count AS REAL) / usage_count * 100
        ELSE confidence_score
    END as effective_confidence
FROM connector_mappings
WHERE id IN (
    SELECT id
    FROM connector_mappings cm1
    WHERE confidence_score = (
        SELECT MAX(confidence_score)
        FROM connector_mappings cm2
        WHERE cm1.okta_internal_name = cm2.okta_internal_name
    )
)
ORDER BY effective_confidence DESC;

-- View to show mapping statistics
CREATE VIEW IF NOT EXISTS mapping_statistics AS
SELECT
    match_type,
    source,
    COUNT(*) as count,
    AVG(confidence_score) as avg_confidence,
    SUM(usage_count) as total_usage,
    SUM(success_count) as total_success,
    SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END) as verified_count
FROM connector_mappings
GROUP BY match_type, source;

-- ============================================================================
-- CONNECTOR REFRESH & AUTO-UPDATE
-- ============================================================================

-- Track connector catalog refresh operations
CREATE TABLE IF NOT EXISTS connector_refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_type TEXT NOT NULL,  -- 'onelogin', 'okta', 'mappings'
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT NOT NULL,  -- 'running', 'success', 'failed', 'skipped'
    records_updated INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_refresh_log_type ON connector_refresh_log(refresh_type);
CREATE INDEX IF NOT EXISTS idx_refresh_log_status ON connector_refresh_log(status);
CREATE INDEX IF NOT EXISTS idx_refresh_log_completed ON connector_refresh_log(completed_at DESC);

-- View for last successful refresh per type
CREATE VIEW IF NOT EXISTS last_refresh AS
SELECT
    refresh_type,
    MAX(completed_at) as last_update,
    status,
    records_updated
FROM connector_refresh_log
WHERE status = 'success'
GROUP BY refresh_type;

-- ============================================================================
-- TELEMETRY (Privacy-Compliant, Anonymized Only)
-- ============================================================================

-- Telemetry consent and settings
CREATE TABLE IF NOT EXISTS telemetry_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enabled BOOLEAN DEFAULT 0,
    user_consent_date TIMESTAMP,
    anonymized BOOLEAN DEFAULT 1,  -- Always 1, non-anonymized telemetry not allowed
    installation_id TEXT UNIQUE,  -- UUID, not user-identifiable
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_telemetry_settings_installation ON telemetry_settings(installation_id);

-- Connector mapping telemetry (anonymized)
CREATE TABLE IF NOT EXISTS connector_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    installation_id TEXT,
    okta_connector_hash TEXT NOT NULL,  -- SHA256(connector_name), not plaintext
    onelogin_connector_id INTEGER,
    suggested BOOLEAN,  -- Was this our suggested mapping?
    accepted BOOLEAN,   -- Did user accept it (or override)?
    confidence_score REAL,
    match_type TEXT,  -- 'exact', 'fuzzy', 'manual', 'user_override'
    migration_run_id TEXT,  -- Link to migration run
    FOREIGN KEY (installation_id) REFERENCES telemetry_settings(installation_id)
);

CREATE INDEX IF NOT EXISTS idx_connector_telemetry_hash
    ON connector_telemetry(okta_connector_hash);
CREATE INDEX IF NOT EXISTS idx_connector_telemetry_run
    ON connector_telemetry(migration_run_id);
CREATE INDEX IF NOT EXISTS idx_connector_telemetry_timestamp
    ON connector_telemetry(timestamp DESC);

-- Anonymized error patterns
CREATE TABLE IF NOT EXISTS error_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    installation_id TEXT,
    error_category TEXT NOT NULL,  -- Exception type, not message
    component TEXT NOT NULL,       -- 'user_migration', 'app_migration', 'group_migration'
    http_status INTEGER,
    retry_count INTEGER DEFAULT 0,
    resolved BOOLEAN DEFAULT 0,  -- Did retry succeed?
    migration_run_id TEXT,
    FOREIGN KEY (installation_id) REFERENCES telemetry_settings(installation_id)
);

CREATE INDEX IF NOT EXISTS idx_error_telemetry_category
    ON error_telemetry(error_category);
CREATE INDEX IF NOT EXISTS idx_error_telemetry_component
    ON error_telemetry(component);
CREATE INDEX IF NOT EXISTS idx_error_telemetry_run
    ON error_telemetry(migration_run_id);
CREATE INDEX IF NOT EXISTS idx_error_telemetry_timestamp
    ON error_telemetry(timestamp DESC);

-- Migration scenario patterns (anonymized aggregates)
CREATE TABLE IF NOT EXISTS migration_scenario_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    installation_id TEXT,
    migration_run_id TEXT UNIQUE,
    user_count_bucket TEXT,  -- '1-10', '11-50', '51-200', '201-1000', '1000+'
    group_count_bucket TEXT,
    app_count_bucket TEXT,
    duration_seconds INTEGER,
    success_rate_percent REAL,  -- Overall success %
    dry_run BOOLEAN,
    concurrency_enabled BOOLEAN,
    FOREIGN KEY (installation_id) REFERENCES telemetry_settings(installation_id)
);

CREATE INDEX IF NOT EXISTS idx_scenario_telemetry_run
    ON migration_scenario_telemetry(migration_run_id);
CREATE INDEX IF NOT EXISTS idx_scenario_telemetry_timestamp
    ON migration_scenario_telemetry(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_scenario_telemetry_bucket
    ON migration_scenario_telemetry(user_count_bucket);

-- ============================================================================
-- TELEMETRY VIEWS (for privacy-safe reporting)
-- ============================================================================

-- Connector mapping effectiveness summary
CREATE VIEW IF NOT EXISTS connector_telemetry_summary AS
SELECT
    match_type,
    COUNT(*) as total_decisions,
    SUM(CASE WHEN accepted THEN 1 ELSE 0 END) as accepted_count,
    SUM(CASE WHEN suggested AND accepted THEN 1 ELSE 0 END) as correctly_suggested,
    AVG(confidence_score) as avg_confidence,
    MIN(confidence_score) as min_confidence,
    MAX(confidence_score) as max_confidence
FROM connector_telemetry
GROUP BY match_type;

-- Error pattern summary
CREATE VIEW IF NOT EXISTS error_pattern_summary AS
SELECT
    error_category,
    component,
    COUNT(*) as occurrence_count,
    AVG(retry_count) as avg_retries,
    SUM(CASE WHEN resolved THEN 1 ELSE 0 END) as resolved_count,
    CAST(SUM(CASE WHEN resolved THEN 1 ELSE 0 END) AS REAL) / COUNT(*) * 100 as resolution_rate
FROM error_telemetry
GROUP BY error_category, component
ORDER BY occurrence_count DESC;

-- Migration scenario effectiveness
CREATE VIEW IF NOT EXISTS scenario_effectiveness AS
SELECT
    user_count_bucket,
    COUNT(*) as scenario_count,
    AVG(success_rate_percent) as avg_success_rate,
    AVG(duration_seconds) as avg_duration_seconds,
    SUM(CASE WHEN dry_run THEN 1 ELSE 0 END) as dry_run_count,
    SUM(CASE WHEN concurrency_enabled THEN 1 ELSE 0 END) as concurrency_count
FROM migration_scenario_telemetry
GROUP BY user_count_bucket;
