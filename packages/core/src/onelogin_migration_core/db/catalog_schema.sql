-- SQLite Schema for OneLogin Migration Tool - CATALOG DATABASE
-- Version: 2.0 (Split Architecture)
-- Purpose: Read-only connector catalogs and mappings (bundled in executable)
-- Location: Bundled in .exe/.app - READ ONLY

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

-- Mapping between Okta and OneLogin connectors (pre-computed)
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
-- METADATA
-- ============================================================================

-- Track catalog version
CREATE TABLE IF NOT EXISTS catalog_version (
    version TEXT PRIMARY KEY,
    build_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    onelogin_count INTEGER,
    okta_count INTEGER,
    mapping_count INTEGER,
    description TEXT
);

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
    verified
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
ORDER BY confidence_score DESC;

-- View to show mapping statistics
CREATE VIEW IF NOT EXISTS mapping_statistics AS
SELECT
    match_type,
    source,
    COUNT(*) as count,
    AVG(confidence_score) as avg_confidence,
    SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END) as verified_count
FROM connector_mappings
GROUP BY match_type, source;
