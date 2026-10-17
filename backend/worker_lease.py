"""Durable worker ownership with token-checked renewal and fenced writes."""
import json
import secrets
import threading
import time


class LeaseLost(RuntimeError):
    pass


def expired(record, now):
    return record.get('expires_at', record['created_at'] + 7200) <= now


class WorkerLease:
    def __init__(self, recovery, key, user, incident_id, ttl=90, interval=15):
        self.recovery = recovery
        self.key, self.user, self.incident_id = key, user, incident_id
        self.ttl, self.interval = ttl, interval
        self.token = secrets.token_urlsafe(32)
        self.stop = threading.Event()
        self.lost = threading.Event()
        self.thread = None

    def claim(self, db):
        if db.execute('SELECT 1 FROM conel_records WHERE id=?', (self.key,)).fetchone():
            return False
        now = time.time()
        self.recovery.save(db, 'repair_lock', self.user, {
            'id': self.key, 'user_id': self.user, 'incident_id': self.incident_id,
            'owner_token': self.token, 'created_at': now,
            'heartbeat_at': now, 'expires_at': now + self.ttl,
        })
        return True

    def assert_owned(self, db):
        row = db.execute('SELECT payload FROM conel_records WHERE id=? AND kind=?', (self.key, 'repair_lock')).fetchone()
        record = json.loads(row[0]) if row else None
        if (self.lost.is_set() or not record or record.get('owner_token') != self.token
                or expired(record, time.time())):
            self.lost.set()
            raise LeaseLost('Repair worker no longer owns this incident')
        return record

    def check(self):
        with self.recovery.store.transaction() as db:
            self.assert_owned(db)

    def renew(self):
        with self.recovery.store.transaction() as db:
            record = self.assert_owned(db)
            now = time.time()
            record.update(heartbeat_at=now, expires_at=now + self.ttl)
            self.recovery.save(db, 'repair_lock', self.user, record)

    def start(self):
        def heartbeat():
            while not self.stop.wait(self.interval):
                try:
                    self.renew()
                except Exception:
                    self.lost.set()
                    return
        self.thread = threading.Thread(target=heartbeat, name='conel-repair-heartbeat', daemon=True)
        self.thread.start()

    def release(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=25)
        with self.recovery.store.transaction() as db:
            row = db.execute('SELECT payload FROM conel_records WHERE id=?', (self.key,)).fetchone()
            if row and json.loads(row[0]).get('owner_token') == self.token:
                if self.lost.is_set():
                    found = db.execute('SELECT payload FROM conel_records WHERE id=? AND kind=? AND user_id=?',
                                       (self.incident_id, 'incident', self.user)).fetchone()
                    if found:
                        item = json.loads(found[0])
                        if item['status'] in {'INVESTIGATING', 'DIAGNOSED', 'GENERATING_FIX', 'TESTING', 'VERIFICATION_FAILED'}:
                            item['status'] = 'NEEDS_HUMAN'
                            item['events'].append({'time': time.time(), 'status': 'NEEDS_HUMAN',
                                                   'message': 'Worker ownership lost. Inspect sandbox cleanup before investigating again.'})
                            self.recovery.save(db, 'incident', self.user, item)
                db.execute('DELETE FROM conel_records WHERE id=?', (self.key,))


def reconcile_expired(recovery):
    with recovery.store.transaction() as db:
        rows = db.execute('SELECT payload FROM conel_records WHERE kind=?', ('repair_lock',)).fetchall()
        for row in rows:
            lock = json.loads(row[0])
            if not expired(lock, time.time()):
                continue
            found = db.execute('SELECT payload FROM conel_records WHERE id=? AND kind=? AND user_id=?',
                               (lock['incident_id'], 'incident', lock['user_id'])).fetchone()
            if found:
                item = json.loads(found[0])
                if item['status'] in {'INVESTIGATING', 'DIAGNOSED', 'GENERATING_FIX', 'TESTING', 'VERIFICATION_FAILED'}:
                    item['status'] = 'NEEDS_HUMAN'
                    item['events'].append({'time': time.time(), 'status': 'NEEDS_HUMAN',
                                           'message': 'Worker lease expired. Inspect recorded sandboxes before investigating again.'})
                    recovery.save(db, 'incident', lock['user_id'], item)
            db.execute('DELETE FROM conel_records WHERE id=?', (lock['id'],))
