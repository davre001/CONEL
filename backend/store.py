"""Transactional persistence for CONEL identity, monitoring and incident records."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from backend.database import Database

SCHEMA_VERSION = 1
SCHEMA = '''
CREATE TABLE IF NOT EXISTS conel_schema_migrations (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, github_login TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_states (hash TEXT PRIMARY KEY, verifier TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS github_connections (user_id TEXT PRIMARY KEY, login TEXT NOT NULL, token TEXT NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS browser_sessions (hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS http_admission (window INTEGER NOT NULL, actor TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(window,actor));
CREATE TABLE IF NOT EXISTS conel_records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, user_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS conel_record_owner ON conel_records(kind,user_id);
'''


class Store:
    def __init__(self, path: Path | str):
        self.database = Database(path)

    @contextmanager
    def transaction(self):
        with self.database.transaction() as db:
            yield db

    def initialize(self, migrate=False):
        if self.database.postgres and not migrate:
            with self.transaction() as db:
                row = db.execute('SELECT MAX(version) FROM conel_schema_migrations').fetchone()
                if row[0] != SCHEMA_VERSION:
                    raise ValueError('Run python -m backend migrate with the migration credential first')
            return
        if not self.database.postgres:
            self.database.target.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.database.target) as db:
                db.execute('PRAGMA journal_mode=WAL')
        with self.transaction() as db:
            db.executescript(SCHEMA)
            row = db.execute('SELECT MAX(version) FROM conel_schema_migrations').fetchone()
            if row[0] is not None and row[0] > SCHEMA_VERSION:
                raise ValueError('Database schema is newer than this application')
            db.execute('INSERT INTO conel_schema_migrations(version) VALUES(?) ON CONFLICT(version) DO NOTHING', (SCHEMA_VERSION,))
