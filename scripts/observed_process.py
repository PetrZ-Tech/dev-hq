"""Run an explicitly requested local command and leave metadata-only exit evidence.

No model/API client. No shell. No retries. A timeout leaves a live child alone.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
import task_lifecycle as lifecycle
import operation_control as operations


def run(args):
    record, run_path = lifecycle.load_run(args.run)
    if lifecycle.RUN_ROOT.resolve() not in run_path.resolve().parents:
        raise ValueError('Run must be a canonical local HQ task record')
    if operations.guard(record)['invalid']:
        raise ValueError('Invalid registry requires recovery')
    operation = record.get('operations', {}).get(args.operation)
    if not operation or operation['state'] != 'RUNNING' or operation.get('observer') is not None or operation.get('probe') is not None:
        raise ValueError('Use an unbound running operation; never relaunch a bound action')
    cwd = lifecycle.resolve_project(args.cwd)
    if type(args.timeout) is not int or not 1 <= args.timeout <= 86400:
        raise ValueError('Timeout must be 1..86400 seconds')
    command = list(args.command)
    if command and command[0] == '--': command.pop(0)
    if not command: raise ValueError('Explicit command required')
    receipt_path = operations.adapters.receipt_path(lifecycle.HQ_ROOT, record['run_id'], operation['id'])
    if receipt_path.exists(): raise ValueError('Existing result must be diagnosed, not overwritten')
    binding = {'kind': 'process-result', 'path': str(receipt_path)}
    if not operations.adapters.validate(binding): raise ValueError('Invalid result path')
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.with_suffix('.claim').open('x', encoding='utf-8') as stream:
        json.dump({'run_id': record['run_id'], 'operation_id': operation['id']}, stream)
    # Bind BEFORE launching: failed launch or interrupted acknowledgement blocks a second invocation.
    operation['observer'] = binding
    lifecycle.save(record, run_path, touch_progress=False)
    child = subprocess.Popen(command, cwd=cwd, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    identity = operations.probe_process(child.pid).get('identity')
    # Reload to preserve any other lifecycle observations recorded during launch.
    record, run_path = lifecycle.load_run(str(run_path))
    operation = record['operations'][args.operation]
    operation['probe'] = {'kind': 'process', 'pid': child.pid, 'identity': identity} if identity else None
    lifecycle.save(record, run_path, touch_progress=False)
    try:
        exit_code = child.wait(timeout=args.timeout)
        outcome = 'finished'
    except subprocess.TimeoutExpired:
        exit_code, outcome = None, 'unknown'
    receipt = {'schema_version': 1, 'kind': 'process-result', 'run_id': record['run_id'],
               'operation_id': operation['id'], 'started_at': operation['started_at'],
               'pid': child.pid, 'process_identity': identity, 'exit_code': exit_code,
               'outcome': outcome, 'finished_at': operations.iso(time.time()) if outcome == 'finished' else None,
               'observed_at': operations.iso(time.time())}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects prior results even if a caller races.
    with receipt_path.open('x', encoding='utf-8') as stream: json.dump(receipt, stream, indent=2)
    print(json.dumps({'status': 'RESULT_RECORDED', 'receipt': str(receipt_path), 'exit_code': exit_code,
                      'outcome': outcome, 'child_pid': child.pid, 'automatic_retry': False}))
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True)
    p.add_argument('--operation', required=True)
    p.add_argument('--cwd', required=True)
    p.add_argument('--timeout', type=int, default=300)
    p.add_argument('command', nargs=argparse.REMAINDER)
    try:
        return run(p.parse_args())
    except Exception as exc:
        print(json.dumps({'status': 'ERROR', 'error': type(exc).__name__ + ': ' + str(exc)}), file=sys.stderr)
        return 2

if __name__ == '__main__': raise SystemExit(main())
