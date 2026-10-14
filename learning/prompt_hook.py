#!/usr/bin/env python3
"""Local prompt checkpoint adapter; never connects to a model or MCP client."""
import argparse
import json
from pathlib import Path
import sys
from mcp_server import Broker, MAX_LINE


def checkpoint(payload, broker):
    if not isinstance(payload, dict) or payload.get('hook_event_name') != 'UserPromptSubmit':
        return {}
    args = {'session_id': payload.get('session_id'),
            'turn_id': payload.get('prompt_id'), 'as_hook': True}
    for key in ('cwd', 'prompt', 'agent_id', 'source', 'scheduled'):
        if key in payload:
            args[key] = payload[key]
    return broker.call('prompt_checkpoint', args)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--policy-root', type=Path)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_LINE + 1)
        if len(raw) > MAX_LINE:
            raise ValueError('oversized input')
        output = checkpoint(json.loads(raw), Broker(args.state_dir, args.policy_root))
    except Exception:
        # No caller values or paths in diagnostics. A failure is not a PASS.
        output = {'systemMessage': 'Shared learning checkpoint unavailable; automatic learning not verified.'}
    print(json.dumps(output, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
