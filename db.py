# db.py
import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

DB_PATH = 'rapp.db'

def init_db():
    """Initialize database schema"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # NFO deployments
    c.execute('''
        CREATE TABLE IF NOT EXISTS nfo_deployments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            name TEXT NOT NULL,
            descriptor_id TEXT,
            instance_id TEXT,
            operation_id TEXT,
            artifact_name TEXT,
            node_name TEXT,
            status TEXT,
            config TEXT
        )
    ''')

    # UE operations
    c.execute('''
        CREATE TABLE IF NOT EXISTS ue_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            operation TEXT NOT NULL,
            details TEXT
        )
    ''')

    # Sideload registry
    c.execute('''
        CREATE TABLE IF NOT EXISTS sideload_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT UNIQUE,
            node_name TEXT UNIQUE NOT NULL,
            ip_address TEXT NOT NULL,
            port INTEGER DEFAULT 8080,
            registered_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        )
    ''')

    # Sideload RT reports
    c.execute('''
        CREATE TABLE IF NOT EXISTS sideload_rt_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            isolated_cpus TEXT,
            online_cpus TEXT,
            tuned_profile TEXT,
            rt_throttling_us TEXT,
            rt_period_us TEXT,
            kernel_version TEXT,
            cpu_governor TEXT,
            hugepages_total TEXT,
            hugepages_free TEXT,
            hugepagesize TEXT,
            FOREIGN KEY(instance_id) REFERENCES sideload_registry(instance_id)
        )
    ''')

    # Sideload operations
    c.execute('''
        CREATE TABLE IF NOT EXISTS sideload_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            operation TEXT NOT NULL,
            url TEXT,
            parameters TEXT,
            result TEXT
        )
    ''')

    # Test executions
    c.execute('''
        CREATE TABLE IF NOT EXISTS test_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            test_id TEXT NOT NULL,
            gnb_instance_id TEXT,
            sideload_instance_id TEXT,
            oru_vendor TEXT,
            status TEXT
        )
    ''')

    # UE measurements
    c.execute('''
        CREATE TABLE IF NOT EXISTS ue_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            test_execution_id INTEGER,
            phase TEXT,
            attached INTEGER,
            rsrp INTEGER,
            rsrq INTEGER,
            sinr INTEGER,
            throughput_mbps REAL,
            FOREIGN KEY(test_execution_id) REFERENCES test_executions(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS sideload_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            reachable INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(instance_id) REFERENCES sideload_registry(instance_id)
        )
    ''')

    conn.commit()
    conn.close()

@contextmanager
def get_db():
    """Context manager for database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# NFO Deployments
def record_nfo_deployment(name, descriptor_id, instance_id, operation_id, config):
    """Record NFO deployment event"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO nfo_deployments
            (timestamp, name, descriptor_id, instance_id, operation_id,
             artifact_name, node_name, status, config)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            name,
            descriptor_id,
            instance_id,
            operation_id,
            config.get('artifact_name'),
            config.get('values', {}).get('nodeSelector', {}).get('kubernetes.io/hostname'),
            'deployed',
            json.dumps(config)
        ))
        conn.commit()
        return c.lastrowid

# UE Operations
def record_ue_operation(operation, details):
    """Record UE operation"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO ue_operations (timestamp, operation, details)
            VALUES (?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            operation,
            json.dumps(details)
        ))
        conn.commit()

# Sideload Registry
def register_sideload(instance_id, node_name, ip_address, port):
    """Register or update sideload by node_name"""
    with get_db() as conn:
        c = conn.cursor()
        now = datetime.now().isoformat()

        # Check if node already registered
        c.execute('SELECT instance_id FROM sideload_registry WHERE node_name = ?', (node_name,))
        existing = c.fetchone()

        if existing:
            # Update existing
            c.execute('''
                UPDATE sideload_registry
                SET ip_address = ?, port = ?, last_seen = ?, status = 'active'
                WHERE node_name = ?
            ''', (ip_address, port, now, node_name))
            conn.commit()
            return existing[0]
        else:
            # Insert new
            c.execute('''
                INSERT INTO sideload_registry
                (instance_id, node_name, ip_address, port, registered_at, last_seen, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (instance_id, node_name, ip_address, port, now, now, 'active'))
            conn.commit()
            return instance_id

def get_sideload_ip(instance_id):
    """Get sideload IP by instance_id"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT ip_address, port FROM sideload_registry
            WHERE instance_id = ? AND status = 'active'
        ''', (instance_id,))
        row = c.fetchone()
        return dict(row) if row else None

def get_sideload_by_node(node_name):
    """Get sideload IP by node name"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT ip_address, port FROM sideload_registry
            WHERE node_name = ? AND status = 'active'
            ORDER BY last_seen DESC LIMIT 1
        ''', (node_name,))
        row = c.fetchone()
        return dict(row) if row else None

def get_all_sideloads():
    """Get all registered sideloads"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM sideload_registry WHERE status = "active"')
        return [dict(row) for row in c.fetchall()]

def update_sideload_heartbeat(instance_id):
    """Update last_seen timestamp"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            UPDATE sideload_registry
            SET last_seen = ?
            WHERE instance_id = ?
        ''', (datetime.now().isoformat(), instance_id))
        conn.commit()

# Sideload RT Reports
def record_sideload_rt_report(instance_id, rt_config):
    """Store RT report as-is"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO sideload_rt_reports
            (instance_id, timestamp, isolated_cpus, online_cpus, tuned_profile,
             rt_throttling_us, rt_period_us, kernel_version, cpu_governor,
             hugepages_total, hugepages_free, hugepagesize)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            instance_id,
            datetime.now().isoformat(),
            rt_config.get('isolated_cpus'),
            rt_config.get('online_cpus'),
            rt_config.get('tuned_profile'),
            rt_config.get('rt_throttling_us'),
            rt_config.get('rt_period_us'),
            rt_config.get('kernel_version'),
            rt_config.get('cpu_governor'),
            rt_config.get('hugepages_total'),
            rt_config.get('hugepages_free'),
            rt_config.get('hugepagesize')
        ))
        conn.commit()

def get_sideload_rt_report(instance_id):
    """Get latest RT report for sideload"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT * FROM sideload_rt_reports
            WHERE instance_id = ?
            ORDER BY timestamp DESC LIMIT 1
        ''', (instance_id,))
        row = c.fetchone()
        return dict(row) if row else None

# Sideload Operations
def record_sideload_operation(operation, url, parameters, result):
    """Record sideload operation"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO sideload_operations (timestamp, operation, url, parameters, result)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            operation,
            url,
            json.dumps(parameters),
            json.dumps(result)
        ))
        conn.commit()

# Test Executions
def record_test_start(test_id, gnb_instance_id, sideload_instance_id, oru_vendor):
    """Record test execution start"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO test_executions
            (timestamp, test_id, gnb_instance_id, sideload_instance_id, oru_vendor, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            test_id,
            gnb_instance_id,
            sideload_instance_id,
            oru_vendor,
            'running'
        ))
        conn.commit()
        return c.lastrowid

def update_test_status(test_execution_id, status):
    """Update test status"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE test_executions SET status = ? WHERE id = ?',
                 (status, test_execution_id))
        conn.commit()

def record_ue_measurement(test_execution_id, phase, ue_status, iperf_result):
    """Record UE measurement"""
    with get_db() as conn:
        c = conn.cursor()

        throughput = None
        if iperf_result and 'end' in iperf_result:
            throughput = iperf_result['end']['sum_received']['bits_per_second'] / 1_000_000

        c.execute('''
            INSERT INTO ue_measurements
            (timestamp, test_execution_id, phase, attached, rsrp, rsrq, sinr, throughput_mbps)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            test_execution_id,
            phase,
            ue_status.get('attached'),
            ue_status.get('signal', {}).get('rsrp'),
            ue_status.get('signal', {}).get('rsrq'),
            ue_status.get('signal', {}).get('sinr'),
            throughput
        ))
        conn.commit()

# History
def get_history(table, limit=50):
    """Get history from table"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(f'SELECT * FROM {table} ORDER BY timestamp DESC LIMIT ?', (limit,))
        return [dict(row) for row in c.fetchall()]

def get_test_history(limit=50):
    """Get test execution history"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM test_executions ORDER BY timestamp DESC LIMIT ?', (limit,))
        return [dict(row) for row in c.fetchall()]

def record_sideload_ips(instance_id, validated_ips):
    """Store all validated IPs"""
    with get_db() as conn:
        c = conn.cursor()
        timestamp = datetime.now().isoformat()

        for ip_info in validated_ips:
            c.execute('''
                INSERT INTO sideload_ips (instance_id, ip_address, reachable, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (
                instance_id,
                ip_info['ip'],
                1 if ip_info['reachable'] else 0,
                timestamp
            ))

        conn.commit()

def upsert_teiv_cache(entity_type, entity_urn, attributes_json):
    """Store TEIV entity in cache"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO teiv_cache
            (entity_type, entity_urn, attributes_json, cached_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (entity_type, entity_urn, attributes_json))
        conn.commit()

def register_test_case(test_id, test_type, file_path, target_odu_urn, parameters_json):
    """Register test case in database"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO test_cases
            (test_id, test_type, file_path, target_odu_urn, parameters_json, loaded_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (test_id, test_type, file_path, target_odu_urn, parameters_json))
        conn.commit()

def get_test_case(test_id):
    """Get test case by ID"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT file_path, target_odu_urn, parameters_json
            FROM test_cases WHERE test_id = ?
        """, (test_id,))
        return cursor.fetchone()

def list_test_cases():
    """List all test cases"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT test_id, test_type, target_odu_urn
            FROM test_cases ORDER BY test_id
        """)
        return cursor.fetchall()

def record_test_results(test_execution_id, successful_runs, avg_throughput,
                       avg_jitter, avg_loss, avg_rsrp, avg_rsrq, avg_sinr,
                       avg_cpu=None, cpu_breakdown=None):
    """Store aggregated test results"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO test_results
            (test_execution_id, successful_runs, avg_throughput_mbps, avg_jitter_ms,
             avg_loss_percent, avg_rsrp_dbm, avg_rsrq_db, avg_sinr_db,
             avg_cpu_percent, cpu_breakdown_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (test_execution_id, successful_runs, avg_throughput, avg_jitter,
              avg_loss, avg_rsrp, avg_rsrq, avg_sinr, avg_cpu,
              json.dumps(cpu_breakdown) if cpu_breakdown else None))
        conn.commit()
        return cursor.lastrowid
