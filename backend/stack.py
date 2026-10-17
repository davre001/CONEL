"""Runtime view of the Stripe Projects-managed infrastructure stack.
Provisioning is an operator CLI action; account credentials never reach browser routes.
"""
import json
import math
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]


def directory():
    value = Path(os.getenv('CONEL_STRIPE_PROJECTS_DIR', str(ROOT / 'var' / 'stripe-projects')))
    return (ROOT / value).resolve() if not value.is_absolute() else value.resolve()


def status():
    """Expose only our small, credential-free operator receipt, never CLI state or vaults."""
    result = {'manager': 'Stripe Projects', 'provider': 'CreateOS', 'status': 'not_connected',
              'project_initialized': False, 'createos_provisioned': False, 'checked_at': None}
    receipt = directory() / 'conel-receipt.json'
    try:
        if receipt.stat().st_size > 4096: return result
        value = json.loads(receipt.read_text(encoding='utf-8'))
        if not isinstance(value, dict): return result
        checked = value.get('checked_at')
        if value.get('schema') != 1 or type(checked) not in {int, float} or not math.isfinite(checked) or checked > time.time()+60: return result
        initialized = value.get('project_initialized') is True
        provisioned = initialized and value.get('createos_provisioned') is True
        result.update(project_initialized=initialized, createos_provisioned=provisioned, checked_at=checked)
        if time.time()-checked > 3600:
            result['status'] = 'needs_refresh'
        elif provisioned and initialized:
            result['status'] = 'provisioned'
        elif initialized:
            result['status'] = 'initialized'
    except (OSError, ValueError, TypeError):
        pass
    return result
