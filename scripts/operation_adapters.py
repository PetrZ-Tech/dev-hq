"""Read-only result observers. No network, credentials, retries or model calls."""
from __future__ import annotations
import json
import os
import math
import re
from datetime import datetime
from pathlib import Path

PROJECTS_ROOT = Path(os.environ.get("DEV_HQ_PROJECTS_ROOT", str(Path.home() / "Projects"))).expanduser().resolve()
MAX_BYTES = 32768
N8N_STATES = {'new', 'running', 'waiting', 'success', 'error', 'crashed', 'canceled', 'unknown'}


def receipt_path(hq_root, run_id, operation_id):
    if not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,180}', v)
               for v in (run_id, operation_id)):
        raise ValueError('Invalid receipt identifier')
    return safe_path(Path(hq_root) / 'runtime' / 'operation-observations' / run_id / (operation_id + '.json'))


def epoch(value):
    try:
        stamp = datetime.fromisoformat(value)
        return stamp.timestamp() if stamp.tzinfo else None
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def safe_path(value, *, root=None):
    p = Path(value).resolve()
    base = Path(root or PROJECTS_ROOT).resolve()
    if base not in p.parents or p.suffix.lower() != '.json' or any(part.lower().startswith('.env') for part in p.parts):
        raise ValueError('Observation file must be an ordinary JSON file inside Projects')
    return p


def validate(binding):
    if not isinstance(binding, dict) or binding.get('kind') not in {'process-result', 'n8n'}:
        return False
    try:
        safe_path(binding['path'])
    except (ValueError, TypeError, KeyError, OSError):
        return False
    if binding['kind'] == 'n8n':
        return (type(binding.get('max_age_seconds')) is int and 10 <= binding['max_age_seconds'] <= 600
                and type(binding.get('allow_historical')) is bool
                and all(isinstance(binding.get(k), str) and 0 < len(binding[k]) <= 120
                        for k in ('workflow_id', 'execution_id')))
    return True


def read(binding):
    p = safe_path(binding['path'])
    with p.open('rb') as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('Oversized observation')
    value = json.loads(content.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Invalid observation object')
    return value


def inspect(record, operation, *, at, process_observation=None):
    binding = operation.get('observer')
    if binding is None:
        return None
    unknown = {'state': 'OUTCOME_UNKNOWN', 'reason': 'observation-unavailable', 'automatic_retry': False}
    try:
        if not validate(binding):
            return {**unknown, 'reason': 'invalid-observer-binding'}
        try:
            value = read(binding)
        except FileNotFoundError:
            probe = operation.get('probe')
            if (binding['kind'] == 'process-result' and isinstance(probe, dict)
                    and isinstance(process_observation, dict) and process_observation.get('state') == 'ALIVE'
                    and process_observation.get('identity') == probe.get('identity')):
                return {'state': 'WAITING_RESULT', 'reason': 'same-process-present-exit-not-yet-recorded', 'automatic_retry': False}
            return unknown
        if any(value.get(k) != expected for k, expected in (
            ('schema_version', 1), ('run_id', record.get('run_id')), ('operation_id', operation.get('id')),
            ('kind', binding['kind']))):
            return {**unknown, 'reason': 'observation-identity-mismatch'}
        observed = epoch(value.get('observed_at'))
        if observed is None or not math.isfinite(observed) or observed > at + 5:
            return {**unknown, 'reason': 'invalid-observation-time'}
        if binding['kind'] == 'process-result':
            if value.get('started_at') != operation.get('started_at'):
                return {**unknown, 'reason': 'process-start-mismatch'}
            probe = operation.get('probe')
            if not isinstance(probe, dict) or value.get('process_identity') != probe.get('identity') or value.get('pid') != probe.get('pid'):
                return {**unknown, 'reason': 'process-identity-mismatch'}
            if value.get('outcome') == 'unknown':
                return {**unknown, 'reason': 'process-outcome-unresolved'}
            exit_code = value.get('exit_code')
            finished = epoch(value.get('finished_at'))
            started = epoch(operation.get('started_at'))
            if type(exit_code) is not int or finished is None or started is None or not started <= finished <= observed + 5:
                return {**unknown, 'reason': 'invalid-process-result'}
            return {'state': 'RESULT_AVAILABLE' if exit_code == 0 else 'FAILED',
                    'reason': 'process-exit-recorded', 'exit_code': exit_code, 'automatic_retry': False,
                    'evidence_ref': binding['path']}
        execution = value.get('execution')
        if not isinstance(execution, dict) or execution.get('id') != binding['execution_id'] or execution.get('workflowId') != binding['workflow_id']:
            return {**unknown, 'reason': 'execution-identity-mismatch'}
        if at - observed > binding['max_age_seconds']:
            return {**unknown, 'reason': 'n8n-observation-stale'}
        started, stopped = epoch(execution.get('startedAt')), epoch(execution.get('stoppedAt'))
        minimum = epoch(operation.get('started_at'))
        if started is None or started > at + 5 or minimum is None or (not binding['allow_historical'] and started < minimum - 5):
            return {**unknown, 'reason': 'execution-start-mismatch'}
        status = execution.get('status')
        if status not in N8N_STATES or status == 'unknown':
            return {**unknown, 'reason': 'execution-status-unknown'}
        terminal = status in {'success', 'error', 'crashed', 'canceled'}
        if (terminal and (stopped is None or stopped < started or stopped > at + 5)) or (not terminal and stopped is not None):
            return {**unknown, 'reason': 'execution-status-time-inconsistent'}
        return {'state': 'RESULT_AVAILABLE' if status == 'success' else 'FAILED' if terminal else 'WAITING_RESULT',
                'reason': 'n8n-' + status, 'execution_id': execution['id'], 'workflow_id': execution['workflowId'],
                'historical': binding['allow_historical'], 'observed_at': value['observed_at'],
                'automatic_retry': False, 'evidence_ref': binding['path']}
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return unknown


def notification(view):
    priorities = {'FAILED': 5, 'OUTCOME_UNKNOWN': 4, 'OVERDUE': 3, 'RESULT_AVAILABLE': 2}
    rows = [r for r in view.get('operations', []) if r.get('state') in priorities]
    if not rows:
        return None
    row = max(rows, key=lambda r: priorities[r['state']])
    state = row['state']
    return {'operation_id': row['id'], 'label': row.get('label'), 'tool': row.get('tool'),
            'severity': 'info' if state == 'RESULT_AVAILABLE' else 'error' if state == 'FAILED' else 'warning',
            'state': state, 'reason': (row.get('result_observation') or {}).get('reason', 'deadline-exceeded'),
            'next_action': 'VERIFY_RESULT_AND_ACKNOWLEDGE' if state == 'RESULT_AVAILABLE' else 'READ_ONLY_RECOVERY',
            'automatic_retry': False, 'delivery': 'LOCAL_MONITOR_ONLY'}
