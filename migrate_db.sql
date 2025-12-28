-- TEIV cache table
CREATE TABLE IF NOT EXISTS teiv_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_urn TEXT UNIQUE NOT NULL,
    attributes_json TEXT NOT NULL,
    cached_at TEXT NOT NULL
);

-- Test case registry
CREATE TABLE IF NOT EXISTS test_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id TEXT UNIQUE NOT NULL,
    test_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    target_odu_urn TEXT,
    target_cell_urn TEXT,
    parameters_json TEXT,
    loaded_at TEXT NOT NULL
);

-- Aggregated test results
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_execution_id INTEGER NOT NULL,
    successful_runs INTEGER,
    avg_throughput_mbps REAL,
    avg_jitter_ms REAL,
    avg_loss_percent REAL,
    avg_rsrp_dbm REAL,
    avg_rsrq_db REAL,
    avg_sinr_db REAL,
    avg_cpu_percent REAL,
    passed INTEGER,
    FOREIGN KEY(test_execution_id) REFERENCES test_executions(id)
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_teiv_urn ON teiv_cache(entity_urn);
CREATE INDEX IF NOT EXISTS idx_test_id ON test_cases(test_id);
CREATE INDEX IF NOT EXISTS idx_exec_id ON test_results(test_execution_id);
