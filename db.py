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

    c.execute('''
        CREATE TABLE IF NOT EXISTS nfo_deployments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            name TEXT NOT NULL,
            instance_id TEXT,
            artifact_name TEXT,
            node_name TEXT,
            config TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS ue_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            operation TEXT NOT NULL,
            details TEXT
        )
    ''')

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

    c.execute('''
    CREATE TABLE IF NOT EXISTS sideload_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        instance_id TEXT UNIQUE,
        node_name TEXT,
        ip_address TEXT NOT NULL,
        port INTEGER DEFAULT 8080,
        registered_at TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        status TEXT DEFAULT 'active'
    )
    ''')

    conn.commit()
    conn.close()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def record_nfo_deployment(name, instance_id, config):
    """Record NFO deployment event"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO nfo_deployments
            (timestamp, name, instance_id, artifact_name, node_name, config)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            name,
            instance_id,
            config.get('artifact_name'),
            config.get('values', {}).get('nodeSelector', {}).get('kubernetes.io/hostname'),
            json.dumps(config)
        ))
        conn.commit()

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

def get_history(table, limit=50):
    """Get history from table"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(f'SELECT * FROM {table} ORDER BY timestamp DESC LIMIT ?', (limit,))
        return [dict(row) for row in c.fetchall()]

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

def register_sideload(instance_id, node_name, ip_address, port=8080):
    """Register sideload pod"""
    with get_db() as conn:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''
            INSERT OR REPLACE INTO sideload_registry
            (instance_id, node_name, ip_address, port, registered_at, last_seen, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (instance_id, node_name, ip_address, port, now, now, 'active'))
        conn.commit()

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

def register_sideload(instance_id, node_name, ip_address, port=8080):
    """Register sideload pod"""
    with get_db() as conn:
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''
            INSERT OR REPLACE INTO sideload_registry
            (instance_id, node_name, ip_address, port, registered_at, last_seen, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (instance_id, node_name, ip_address, port, now, now, 'active'))
        conn.commit()

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

def update_sideload_heartbeat(instance_id):
    """Update last_seen timestamp"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''
            UPDATE sideload_registry
            SET last_seen = ?
            WHERE instance_id = ?
        ''', (datetime.now().isoformat(), instance_id))
