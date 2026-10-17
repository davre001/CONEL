"""Database boundary for the fixed CONEL SQL statements (not arbitrary SQL)."""
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlparse, parse_qs


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)

    def __iter__(self):
        return iter(self.values())


def row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


def postgres_sql(sql):
    # Queries in the store are static; '?' occurs only as a bind placeholder.
    sql = re.sub(r'\bREAL\b', 'DOUBLE PRECISION', sql)
    sql = re.sub(r'\bwindow\b', '"window"', sql)
    sql = sql.replace('count=count+1', 'count=http_admission.count+1')
    sql = sql.replace('?', '%s')
    return sql


class Connection:
    def __init__(self, db, postgres):
        self.db, self.postgres = db, postgres

    def execute(self, sql, params=()):
        if self.postgres:
            return self.db.execute(postgres_sql(sql), params or None)
        return self.db.execute(sql, params)

    def executescript(self, sql):
        # Unlike sqlite executescript, do not implicitly commit the transaction.
        for statement in sql.split(';'):
            statement = statement.strip()
            if statement and not (self.postgres and statement.startswith('PRAGMA')):
                self.execute(statement)


class Database:
    def __init__(self, target):
        value = str(target)
        self.postgres = value.startswith(('postgresql://', 'postgres://'))
        self.target = value if self.postgres else Path(target)
        if self.postgres:
            url = urlparse(value)
            if not url.hostname or not url.path.strip('/'):
                raise ValueError('Invalid CONEL_DATABASE_URL')
            if url.hostname not in {'localhost', '127.0.0.1', '::1'} and parse_qs(url.query).get('sslmode', [''])[0] not in {'require','verify-ca','verify-full'}:
                raise ValueError('Remote PostgreSQL requires sslmode=require or certificate verification')

    @contextmanager
    def transaction(self):
        if self.postgres:
            import psycopg
            db = psycopg.connect(self.target, row_factory=row_factory, connect_timeout=10,
                                prepare_threshold=None)
        else:
            self.target.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.target, timeout=10, isolation_level=None)
            db.row_factory = sqlite3.Row
        try:
            if self.postgres:
                db.execute("SET LOCAL lock_timeout = '10s'")
                db.execute("SET LOCAL statement_timeout = '20s'")
                # Match SQLite BEGIN IMMEDIATE: every cooperating CONEL process
                # serializes short DB transactions, including read-then-write quotas.
                db.execute('SELECT pg_advisory_xact_lock(847291603)')
            else:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('BEGIN IMMEDIATE')
            yield Connection(db, self.postgres)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
