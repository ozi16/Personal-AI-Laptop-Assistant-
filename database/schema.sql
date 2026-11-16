CREATE TABLE IF NOT EXISTS system_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    cpu_percent REAL NOT NULL,
    cpu_count_logical INTEGER,
    cpu_count_physical INTEGER,
    cpu_freq_mhz REAL,
    ram_total_bytes INTEGER NOT NULL,
    ram_used_bytes INTEGER NOT NULL,
    ram_available_bytes INTEGER NOT NULL,
    ram_percent REAL NOT NULL,
    disk_c_total_bytes INTEGER,
    disk_c_used_bytes INTEGER,
    disk_c_free_bytes INTEGER,
    disk_c_free_percent REAL,
    disk_d_total_bytes INTEGER,
    disk_d_used_bytes INTEGER,
    disk_d_free_bytes INTEGER,
    disk_d_free_percent REAL,
    health_status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_system_metrics_timestamp
    ON system_metrics (timestamp);

CREATE TABLE IF NOT EXISTS process_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    pid INTEGER NOT NULL,
    name TEXT NOT NULL,
    cpu_percent REAL,
    memory_bytes INTEGER NOT NULL,
    memory_percent REAL
);

CREATE INDEX IF NOT EXISTS idx_process_metrics_timestamp
    ON process_metrics (timestamp);

CREATE TABLE IF NOT EXISTS scanned_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    extension TEXT NOT NULL,
    category TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    modified_at TEXT NOT NULL,
    sha256 TEXT,
    scanned_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scanned_files_category
    ON scanned_files (category);

CREATE INDEX IF NOT EXISTS idx_scanned_files_size
    ON scanned_files (file_size);

CREATE INDEX IF NOT EXISTS idx_scanned_files_sha256
    ON scanned_files (sha256);

CREATE INDEX IF NOT EXISTS idx_scanned_files_scanned_at
    ON scanned_files (scanned_at);

CREATE TABLE IF NOT EXISTS file_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK (operation_type IN ('move', 'undo')),
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'success', 'failed', 'undo_pending', 'undone', 'recovery_required'
    )),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_file_operations_status
    ON file_operations (status);

CREATE INDEX IF NOT EXISTS idx_file_operations_created_at
    ON file_operations (created_at);
