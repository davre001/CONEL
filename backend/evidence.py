"""Versioned, credential-free incident evidence for developer review and export."""
import hashlib
import re
from backend.recovery import clean


def redact(value):
    text = re.sub(r'-----BEGIN [^\n]*PRIVATE KEY-----.*?-----END [^\n]*PRIVATE KEY-----', '[redacted private key]', str(value), flags=re.S)
    text = re.sub(r'''(?i)((?:["']?[\w-]*(?:token|secret|password|api[_-]?key|encryption[_-]?key|monitor[_-]?key|authorization|cookie)[\w-]*["']?)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''', r'\1[redacted]', text)
    text = re.sub(r'\b(?:sk_(?:live|test)_[A-Za-z0-9_-]+|gh[pousr]_[A-Za-z0-9_]+)\b', '[redacted]', text)
    return clean(text)


def export_evidence(item):
    patch = item.get('patch') or ''
    attempts = []
    for attempt in item.get('attempts', []):
        attempts.append({
            'number': attempt['number'], 'sandbox_id': attempt.get('sandbox_id'),
            'status': attempt.get('status'), 'created_at': attempt.get('created_at'),
            'completed_at': attempt.get('completed_at'),
            'cleanup_error': redact(attempt['cleanup_error']) if attempt.get('cleanup_error') else None,
            'command_results': [{**{k: r.get(k) for k in ('check', 'exit_code', 'duration_ms')},
                                 **{k: redact(r.get(k, '')) for k in ('command', 'stdout', 'stderr')}}
                                for r in attempt.get('command_results', [])],
        })
    recovery = item.get('recovery_evidence') or {}
    safe_recovery = {k: {field: recovery[k].get(field) for field in ('healthy', 'status_code', 'latency_ms', 'checked_at', 'signature')}
                     for k in ('health', 'targeted') if isinstance(recovery.get(k), dict)}
    safe_recovery.update({k: redact(recovery[k]) for k in ('kind', 'merge_commit', 'reference', 'notes') if recovery.get(k)})
    if recovery.get('checked_at') is not None: safe_recovery['checked_at'] = recovery['checked_at']
    pr = item.get('pull_request') or {}
    return {
        'schema_version': 1, 'incident_id': item['id'], 'project_id': item['project_id'],
        'status': item['status'], 'revision': item.get('revision'), 'repository': redact(item['repository']),
        'method': item['method'], 'endpoint': redact(item['endpoint'].split('?')[0]),
        'message': redact(item['message']), 'created_at': item['created_at'],
        'recovered_at': item.get('recovered_at'),
        'patch_sha256': hashlib.sha256(patch.encode()).hexdigest(), 'patch': redact(patch),
        'patch_may_be_redacted_or_truncated': True,
        'attempts': attempts, 'pull_request': {'number': pr.get('number')},
        'recovery': safe_recovery,
        'events': [{**{k: e.get(k) for k in ('time', 'status')}, 'message': redact(e.get('message', ''))}
                   for e in item.get('events', [])],
    }
