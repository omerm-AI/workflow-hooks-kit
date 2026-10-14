#!/usr/bin/env python3
"""Local prompt checkpoint adapter; never connects to a model or MCP client."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
from mcp_server import Broker, MAX_LINE, cli, digest


def checkpoint(payload, broker):
    if not isinstance(payload, dict) or payload.get('hook_event_name') != 'UserPromptSubmit':
        return {}
    # Codex supplies turn_id; Claude supplies prompt_id. Never invent an ID.
    turn_id = payload.get('turn_id', payload.get('prompt_id'))
    if ('turn_id' in payload and 'prompt_id' in payload
            and payload['turn_id'] != payload['prompt_id']):
        raise ValueError('conflicting native identities')
    args = {'session_id': payload.get('session_id'), 'turn_id': turn_id, 'as_hook': True}
    for key in ('cwd', 'prompt', 'agent_id', 'source', 'scheduled'):
        if key in payload:
            args[key] = payload[key]
    output = broker.call('prompt_checkpoint', args)
    if 'hookSpecificOutput' in output:
        output['hookSpecificOutput']['additionalContext'] = 'Policy:read_scoped_policy'
    return output


# Fixed field names only: arbitrary input keys could themselves contain secrets.
DIAGNOSTIC_FIELDS = ('hook_event_name', 'session_id', 'turn_id', 'prompt_id',
                     'cwd', 'prompt', 'agent_id', 'source', 'scheduled')


def write_diagnostic(state_dir, payload, phase, outcome, error=None):
    """Replace one bounded metadata record; diagnostics must never affect hooks."""
    try:
        broker = Broker(state_dir)
        record = {'version': 1, 'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'phase': phase, 'outcome': outcome, 'input_type': type(payload).__name__}
        if isinstance(payload, dict):
            record['field_types'] = {key: type(payload[key]).__name__
                                     for key in DIAGNOSTIC_FIELDS if key in payload}
            record['unknown_key_count'] = sum(key not in DIAGNOSTIC_FIELDS for key in payload)
            record['user_prompt_event'] = payload.get('hook_event_name') == 'UserPromptSubmit'
            record['identity_hashes'] = {key: digest(payload[key])
                                         for key in ('session_id', 'turn_id', 'prompt_id')
                                         if isinstance(payload.get(key), str)
                                         and 0 < len(payload[key]) <= 160}
            record['agent_field_present'] = 'agent_id' in payload
        if error is not None:
            # Exception messages may contain prompts, paths or credentials.
            record['error_type'] = type(error).__name__ if type(error).__name__ in (
                'ValueError', 'TypeError', 'LearningError', 'JSONDecodeError',
                'UnicodeDecodeError', 'PermissionError', 'OSError') else 'OtherError'
        raw = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('utf-8')
        if len(raw) <= 2048:
            cli.atomic_write(broker.store.root / 'last-prompt-hook.json', raw + b'\n')
    except Exception:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--policy-root', type=Path)
    args = parser.parse_args(argv)
    payload = None
    phase = 'input'
    error = None
    outcome = 'rejected'
    try:
        raw = sys.stdin.buffer.read(MAX_LINE + 1)
        if len(raw) > MAX_LINE:
            raise ValueError('oversized input')
        phase = 'decode'
        payload = json.loads(raw)
        phase = 'broker_init'
        broker = Broker(args.state_dir, args.policy_root)
        phase = 'checkpoint'
        output = checkpoint(payload, broker)
        outcome = ('broker_returned' if isinstance(payload, dict)
                   and payload.get('hook_event_name') == 'UserPromptSubmit' else 'ignored_event')
    except Exception as exc:
        error = exc
        # No caller values or paths in diagnostics. A failure is not a PASS.
        output = {'systemMessage': 'Shared learning checkpoint unavailable; automatic learning not verified.'}
    write_diagnostic(args.state_dir, payload, phase, outcome, error)
    print(json.dumps(output, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
