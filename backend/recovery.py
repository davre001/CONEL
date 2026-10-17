"""CONEL application monitoring and durable, tenant-scoped incident records."""
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import time
import uuid
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field


def clean(value):
    value = re.sub(r'(?i)(bearer\s+|(?:token|secret|password|api[_-]?key)\s*[:=]\s*)[^\s,;]+', r'\1[redacted]', str(value))
    return re.sub(r'https?://[^\s]+', '[URL omitted]', value)[:8000]


def fingerprint(project, endpoint, kind, message, stack=''):
    normalized = re.sub(r'\b\d+\b', '#', message)
    return hashlib.sha256(json.dumps([project, endpoint, kind, normalized, stack.splitlines()[:1]], sort_keys=True).encode()).hexdigest()


def validate_url(value):
    try:
        u = urlsplit(value)
        port = u.port
    except ValueError:
        raise HTTPException(422, 'Invalid monitoring URL') from None
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment or port not in {None, 443}:
        raise HTTPException(422, 'Use a public HTTPS URL without credentials, query parameters or a fragment')
    return value.rstrip('/')


def probe(url):
    """Pin a public resolved IP while retaining hostname verification; never follow redirects."""
    u = urlsplit(validate_url(url))
    started = time.monotonic()
    try:
        addresses = socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise HTTPException(422, 'Monitoring private or reserved networks is prohibited')
        connection = http.client.HTTPSConnection(u.hostname, timeout=8, context=ssl.create_default_context())
        raw = socket.create_connection((addresses[0][4][0], 443), timeout=8)
        try:
            connection.sock = connection._context.wrap_socket(raw, server_hostname=u.hostname)
            connection.request('GET', u.path or '/', headers={'User-Agent': 'CONEL-Monitor/1.0', 'Accept': 'application/json'})
            response = connection.getresponse()
            status = response.status
            signature = hashlib.sha256(response.read(16384)).hexdigest()
        finally:
            raw.close()
            connection.close()
        return {'healthy': 200 <= status < 300, 'status_code': status, 'latency_ms': round((time.monotonic()-started)*1000), 'signature': signature, 'checked_at': time.time()}
    except HTTPException:
        raise
    except (OSError, http.client.HTTPException):
        return {'healthy': False, 'status_code': 0, 'latency_ms': round((time.monotonic()-started)*1000), 'signature': '', 'checked_at': time.time()}


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    production_url: str = Field(max_length=500)
    repository: str = Field(pattern=r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$', max_length=200)
    branch: str = Field(default='main', min_length=1, max_length=150)
    root_directory: str = Field(default='', pattern=r'^(?:[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*)?$', max_length=200)
    health_endpoint: str = Field(default='/api/health', pattern=r'^/[^?#]*$', max_length=200)
    repair_mode: str = Field(default='auto_investigate', pattern=r'^(monitor_only|auto_investigate)$')


class RuntimeErrorInput(BaseModel):
    project_id: str = Field(max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    error_name: str = Field(default='RuntimeError', max_length=100)
    stack: str = Field(default='', max_length=8000)
    endpoint: str = Field(default='/', max_length=200)
    method: str = Field(default='GET', pattern=r'^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$')


class RecoveryConfirmation(BaseModel):
    merge_commit: str = Field(pattern=r'^[a-f0-9]{40}$')
    reference: str = Field(min_length=1, max_length=500)
    notes: str = Field(min_length=20, max_length=2000)
    checked_at: float = Field(allow_inf_nan=False)


class Recovery:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        self.store.initialize()

    def save(self, db, kind, user, value):
        db.execute('INSERT INTO conel_records(id,kind,user_id,payload) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (value['id'], kind, user, json.dumps(value)))

    def list(self, kind, user=None):
        with self.store.transaction() as db:
            rows = db.execute('SELECT payload FROM conel_records WHERE kind=?' + (' AND user_id=?' if user is not None else ''), (kind, user) if user is not None else (kind,)).fetchall()
        return sorted([json.loads(r[0]) for r in rows], key=lambda r: r.get('created_at', 0), reverse=True)

    def get(self, kind, key, user):
        with self.store.transaction() as db:
            row = db.execute('SELECT payload FROM conel_records WHERE id=? AND kind=? AND user_id=?', (key, kind, user)).fetchone()
        if not row: raise HTTPException(404, 'Record not found')
        return json.loads(row[0])

    @staticmethod
    def public(project):
        return {k: v for k, v in project.items() if k not in {'monitor_key_hash', 'user_id'}}

    def incident(self, db, project, message, endpoint, kind='HealthFailure', stack='', method='GET'):
        fp = fingerprint(project['id'], endpoint, kind, message, stack)
        rows = db.execute('SELECT payload FROM conel_records WHERE kind=? AND user_id=?', ('incident', project['user_id'])).fetchall()
        for row in rows:
            item = json.loads(row[0])
            if item['fingerprint'] == fp and item['status'] not in {'RECOVERED', 'REJECTED'}:
                item['occurrence_count'] += 1
                item['last_seen'] = time.time()
                self.save(db, 'incident', project['user_id'], item)
                return item
        now = time.time()
        item = dict(id=uuid.uuid4().hex, user_id=project['user_id'], project_id=project['id'], project_name=project['name'], repository=project['repository'], branch=project['branch'], revision=None, fingerprint=fp, severity='CRITICAL', status='DETECTED', type=kind, message=clean(message), stack_trace=clean(stack), endpoint=endpoint.split('?')[0], method=method, occurrence_count=1, created_at=now, first_seen=now, last_seen=now, recovered_at=None, attempts=[], diagnosis=None, patch=None, events=[{'time': now, 'message': 'Runtime failure detected', 'status': 'DETECTED'}])
        if project['repair_mode'] == 'auto_investigate':
            from backend.conel_repairs import configured
            item['status'] = 'QUEUED' if configured() else 'NEEDS_HUMAN'
            item['events'].append({'time': now, 'message': 'Queued for source investigation and CreateOS verification' if item['status'] == 'QUEUED' else 'Automatic investigation blocked: configure CreateOS and the coding model. No code executed or repository changes made.', 'status': item['status']})
        self.save(db, 'incident', project['user_id'], item)
        return item

    def check(self, project):
        result = probe(project['production_url'] + project['health_endpoint'])
        with self.store.transaction() as db:
            row = db.execute('SELECT payload FROM conel_records WHERE id=?', (project['id'],)).fetchone()
            if not row: return result
            project = json.loads(row[0])
            if not project['monitoring_enabled']: return result
            project['health'] = result
            project['health_history'] = (project.get('health_history', []) + [result])[-120:]
            project['consecutive_failures'] = 0 if result['healthy'] else project.get('consecutive_failures', 0) + 1
            if project['consecutive_failures'] >= 2:
                self.incident(db, project, 'Health endpoint returned an unsuccessful response', project['health_endpoint'])
            self.save(db, 'project', project['user_id'], project)
        return result

    def tick(self):
        for project in self.list('project'):
            if project['monitoring_enabled'] and time.time() - project.get('health', {}).get('checked_at', 0) >= 30:
                try: self.check(project)
                except Exception:
                    # One invalid target must not stop monitoring other applications.
                    continue


def routes(app, recovery, auth):
    from backend.conel_repairs import RepairWorker, configured
    worker = RepairWorker(recovery, auth)
    app.state.repair_worker = worker
    @app.get('/api/projects')
    def projects(request: Request):
        user = auth.authenticate(request)
        return [recovery.public(p) for p in recovery.list('project', user)]

    @app.post('/api/projects', status_code=201)
    def create_project(body: ProjectInput, request: Request):
        user = auth.authenticate(request)
        auth.authorize_application(user, body.repository)
        if len(recovery.list('project', user)) >= 20: raise HTTPException(409, 'Application limit reached')
        values = body.model_dump()
        values['production_url'] = validate_url(values['production_url'])
        result = probe(values['production_url'] + values['health_endpoint'])
        if not result['healthy']: raise HTTPException(422, 'Health endpoint must pass before monitoring starts')
        key = secrets.token_urlsafe(32)
        project = dict(**values, id=uuid.uuid4().hex, user_id=user, framework='Next.js / TypeScript', monitor_key_hash=hashlib.sha256(key.encode()).hexdigest(), monitoring_enabled=True, health=result, health_history=[result], consecutive_failures=0, created_at=time.time())
        with recovery.store.transaction() as db: recovery.save(db, 'project', user, project)
        return {**recovery.public(project), 'monitor_key': key}

    @app.get('/api/projects/repositories')
    def repositories(request: Request):
        user = auth.authenticate(request)
        return {'repositories': auth.repositories(user, include_private=True)}

    @app.get('/api/projects/{project_id}')
    def project(project_id: str, request: Request):
        return recovery.public(recovery.get('project', project_id, auth.authenticate(request)))

    @app.post('/api/projects/{project_id}/pause')
    def pause(project_id: str, request: Request):
        user = auth.authenticate(request)
        with recovery.store.transaction() as db:
            row = db.execute('SELECT payload FROM conel_records WHERE id=? AND kind=? AND user_id=?', (project_id, 'project', user)).fetchone()
            if not row: raise HTTPException(404, 'Application not found')
            item = json.loads(row[0]); item['monitoring_enabled'] = not item['monitoring_enabled']
            recovery.save(db, 'project', user, item)
        return recovery.public(item)

    @app.post('/api/projects/{project_id}/test')
    def test(project_id: str, request: Request):
        return probe((p := recovery.get('project', project_id, auth.authenticate(request)))['production_url'] + p['health_endpoint'])

    @app.post('/api/monitor/health/run')
    def run_checks(request: Request):
        user = auth.authenticate(request)
        return [recovery.check(p) for p in recovery.list('project', user) if p['monitoring_enabled']]

    @app.post('/api/monitor/error', status_code=202)
    def runtime_error(body: RuntimeErrorInput, request: Request):
        credential = request.headers.get('authorization', '').removeprefix('Bearer ')
        with recovery.store.transaction() as db:
            row = db.execute('SELECT payload FROM conel_records WHERE id=? AND kind=?', (body.project_id, 'project')).fetchone()
            project = json.loads(row[0]) if row else None
            supplied = hashlib.sha256(credential.encode()).hexdigest()
            if not project or not hmac.compare_digest(supplied, project['monitor_key_hash']): raise HTTPException(401, 'Invalid monitor credential')
            if not project['monitoring_enabled']: raise HTTPException(409, 'Monitoring is paused')
            item = recovery.incident(db, project, clean(body.message), body.endpoint.split('?')[0], body.error_name, clean(body.stack), body.method)
        return {'incident_id': item['id']}

    @app.get('/api/incidents')
    def incidents(request: Request):
        return recovery.list('incident', auth.authenticate(request))

    @app.get('/api/incidents/{incident_id}')
    def incident(incident_id: str, request: Request):
        return recovery.get('incident', incident_id, auth.authenticate(request))

    @app.get('/api/incidents/{incident_id}/evidence')
    def evidence(incident_id: str, request: Request):
        from backend.evidence import export_evidence
        return export_evidence(recovery.get('incident', incident_id, auth.authenticate(request)))

    @app.post('/api/incidents/{incident_id}/confirm-recovery')
    def confirm_recovery(incident_id: str, body: RecoveryConfirmation, request: Request):
        user = auth.authenticate(request)
        item = recovery.get('incident', incident_id, user)
        if item['status'] != 'APPLYING' or not item.get('pull_request') or item['method'] in {'GET', 'HEAD'}:
            raise HTTPException(409, 'Only a merged mutating-request repair awaiting recovery can be attested')
        from backend.conel_repairs import verified
        if not item['attempts'] or not verified(item['attempts'][-1]['command_results']):
            raise HTTPException(409, 'Complete sandbox verification is required')
        now = time.time()
        if not max(item['created_at'], now-900) <= body.checked_at <= now+60:
            raise HTTPException(422, 'Supply evidence observed within the last 15 minutes')
        validate_url(body.reference)
        auth.authorize_application(user, item['repository'])
        pull = auth.api(auth.token(user), f'/repos/{item["repository"]}/pulls/{item["pull_request"]["number"]}')
        if not pull.get('merged') or pull.get('merge_commit_sha') != body.merge_commit:
            raise HTTPException(409, 'Evidence must reference the actual merged repair commit')
        project = recovery.get('project', item['project_id'], user)
        health = probe(project['production_url'] + project['health_endpoint'])
        if not health['healthy']: raise HTTPException(409, 'Live application health has not recovered')
        from backend.evidence import redact
        with recovery.store.transaction() as db:
            row = db.execute('SELECT payload FROM conel_records WHERE id=? AND kind=? AND user_id=?',
                             (incident_id, 'incident', user)).fetchone()
            current = json.loads(row[0])
            if current['status'] != 'APPLYING' or current.get('pull_request') != item['pull_request']:
                raise HTTPException(409, 'Incident changed while checking recovery')
            current['recovered_at'] = time.time()
            current['recovery_evidence'] = {'kind': 'operator_attested', 'reviewer': user,
                'merge_commit': body.merge_commit, 'reference': body.reference, 'notes': redact(body.notes),
                'checked_at': body.checked_at, 'health': health}
            current['events'].append({'time': time.time(), 'status': 'RECOVERED',
                'message': 'Developer attested mutating-request recovery after merge and live health verification; CONEL did not replay the request'})
            current['status'] = 'RECOVERED'
            recovery.save(db, 'incident', user, current)
        return current

    @app.post('/api/incidents/{incident_id}/investigate')
    def investigate(incident_id: str, request: Request):
        user = auth.authenticate(request)
        item = recovery.get('incident', incident_id, user)
        if not configured(): raise HTTPException(503, 'Configure CREATEOS_API_KEY, LLM_API_KEY and LLM_MODEL to investigate')
        with recovery.store.transaction() as db:
            row = db.execute('SELECT payload FROM conel_records WHERE id=? AND user_id=?', (incident_id, user)).fetchone()
            item = json.loads(row[0])
            if item['status'] not in {'DETECTED', 'NEEDS_HUMAN', 'REPAIR_FAILED', 'VERIFICATION_FAILED'}: raise HTTPException(409, 'Incident is already being processed or awaits review')
            if len(item['attempts']) >= 3: raise HTTPException(409, 'Three-attempt repair limit reached')
            item['status'] = 'QUEUED'
            item['events'].append({'time': time.time(), 'status': 'QUEUED', 'message': 'Investigation queued by developer'})
            recovery.save(db, 'incident', user, item)
        return item

    @app.post('/api/incidents/{incident_id}/approve')
    def approve(incident_id: str, request: Request):
        user = auth.authenticate(request)
        with recovery.store.transaction() as db:
            row = db.execute('SELECT payload FROM conel_records WHERE id=? AND kind=? AND user_id=?', (incident_id, 'incident', user)).fetchone()
            if not row: raise HTTPException(404, 'Incident not found')
            item = json.loads(row[0])
            if item['status'] not in {'VERIFIED', 'AWAITING_APPROVAL'}: raise HTTPException(409, 'Only an objectively verified repair can be approved')
            if item.get('publication'): raise HTTPException(409, 'Publication already started; reconcile GitHub before retrying')
            item['status'] = 'APPLYING'
            recovery.save(db, 'incident', user, item)
        try: return worker.publish(item, user)
        except HTTPException as error:
            worker.update(item, 'NEEDS_HUMAN', 'Publication stopped: '+str(error.detail))
            raise
        except Exception:
            worker.update(item, 'NEEDS_HUMAN', 'Publication interrupted. Inspect the repair branch and GitHub before retrying; no deployment is confirmed.')
            raise HTTPException(502, 'PR publication did not complete; inspect GitHub before retrying') from None

    @app.post('/api/incidents/{incident_id}/reject')
    def reject(incident_id: str, request: Request):
        user = auth.authenticate(request)
        with recovery.store.transaction() as db:
            row = db.execute('SELECT payload FROM conel_records WHERE id=? AND kind=? AND user_id=?', (incident_id, 'incident', user)).fetchone()
            if not row: raise HTTPException(404, 'Incident not found')
            item = json.loads(row[0])
            if item['status'] not in {'VERIFIED', 'AWAITING_APPROVAL'}: raise HTTPException(409, 'There is no verified fix to reject')
            item['status'] = 'REJECTED'
            item['events'].append({'time': time.time(), 'status': 'REJECTED', 'message': 'Developer rejected the repair'})
            recovery.save(db, 'incident', user, item)
        return item

    @app.get('/api/integrations')
    def integrations(request: Request):
        user = auth.authenticate(request)
        tested = recovery.list('integration', user)
        sandbox_verified = any(t['id'] == 'createos-test-'+user and t['status'] == 'connected' and time.time()-t['created_at'] < 3600 for t in tested)
        from backend.stack import status as stack_status
        stack = stack_status()
        return {'github': 'connected', 'createos': 'connected' if sandbox_verified else 'configured_not_verified' if os.getenv('CREATEOS_API_KEY') else 'not_connected', 'stripe_projects': stack['status'], 'stack': stack, 'stripe_checkout': 'optional_not_configured', 'repair_executor': 'configured_not_verified' if configured() else 'not_connected', 'monitor_interval_seconds': 30, 'approval_required': True}

    @app.post('/api/integrations/createos/test')
    def test_sandbox(request: Request):
        auth.authenticate(request)
        if not os.getenv('CREATEOS_API_KEY'): raise HTTPException(503, 'CreateOS API key is not configured')
        from backend.conel_repairs import CreateOS
        sandbox = CreateOS()
        try:
            identity = sandbox.create()
            result = sandbox.execute('printf CONEL', 'connection')
            if result['exit_code'] != 0: raise ValueError('Sandbox execution failed')
        except Exception:
            raise HTTPException(502, 'Sandbox connection test failed') from None
        finally:
            try: sandbox.close()
            except Exception: raise HTTPException(502, 'Sandbox cleanup failed; check the CreateOS dashboard') from None
        with recovery.store.transaction() as db:
            recovery.save(db, 'integration', auth.authenticate(request), {'id': 'createos-test-'+auth.authenticate(request), 'status': 'connected', 'created_at': time.time()})
        return {'sandbox_id': identity, 'status': 'connected', 'command_result': result}
