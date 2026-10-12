#!/usr/bin/env python3
"""Local, stdlib MCP broker for the CLI's approved learning store.

Receipts prove only that this broker was called, never prompt delivery order or
human authorship. A client must call it before its model to establish that order.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import stat
import os
import sys

# Import the adjacent canonical CLI, also when bundled in a plugin.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cli

PROTOCOLS = ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25')
MAX_LINE = 32768
MAX_RECEIPTS = 100  # Older metadata is archived automatically; rules stay canonical.
RETAIN_RECEIPTS = 64
POLICY_SCOPES = ('execution', 'quality', 'efficiency', 'continuity', 'visual', 'writing',
                 'automation', 'security', 'workshops', 'proposals', 'brain')
MAX_POLICY = 64 * 1024

def checked_directory(path):
    path = Path(path).expanduser().absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise cli.LearningError('unsafe configured policy directory')
    return path

EXPLICIT = re.compile(r'^(?:remember(?:\s+that)?|from\s+now\s+on|תזכור|מעכשיו)\s*[:,-]?\s+(.+)$', re.I)
MATERIAL = re.compile(r'(?i)\b(build|implement|create|fix|debug|develop|install|review|verify|test|deploy)\b|(?:תבנה|תתקן|תיצור|תפתח|תבדוק|תתקין|בנה|תקן|צור|בדוק)')
SENSITIVE = re.compile(r'(?i)(?:bearer\s+\S+|-----BEGIN\s+.*PRIVATE\s+KEY|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+|(?:credential|token|private[_ -]?key)\s*[:=])')


def text_value(value, label, limit):
    result = cli.clean_text(value, label, limit)
    if '${' in result or '{{' in result or SENSITIVE.search(result):
        raise cli.LearningError('unresolved template or sensitive value')
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode()).hexdigest()


def schema(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {},
            'required': list(required), 'additionalProperties': False}


def string():
    return {'type': 'string'}


TOOLS = [
    {'name': 'prompt_checkpoint', 'description': 'Record a local call receipt; no proof of human authorship or model ordering. Explicit remember requests become pending only.',
     'inputSchema': schema({**{key: string() for key in ('session_id', 'turn_id', 'cwd', 'prompt', 'agent_id', 'source')},
                            'scheduled': {'type': 'boolean'}, 'as_hook': {'type': 'boolean'}}, ('session_id', 'turn_id'))},
    {'name': 'read_scoped_policy', 'description': 'Read verified approved rules for one exact scope. Pending hypotheses are never returned.',
     'inputSchema': schema({'scope': string()}, ('scope',))},
    {'name': 'propose_rule', 'description': 'Record a pending hypothesis for an explicit scope. Does not approve or apply it; source reference is not authentication.',
     'inputSchema': schema({key: string() for key in ('scope', 'rule', 'source_ref')}, ('scope', 'rule', 'source_ref'))},
    {'name': 'learning_status', 'description': 'Bounded counts, approved policy fingerprint, and recent hashed receipt metadata.', 'inputSchema': schema()}
]


class Broker:
    def __init__(self, root, policy_root=None):
        self.policy_root = checked_directory(policy_root) if policy_root is not None else None
        # CLI Store resolves ancestors; validate the requested chain first so a
        # symlink ancestor cannot redirect this broker to a different store.
        requested = Path(root).expanduser().absolute()
        if requested.exists() and requested.lstat().st_uid != os.getuid():
            raise cli.LearningError('state root must be owned by the current user')
        self.store = cli.Store(cli.ensure_real_dir(requested))
        if self.store.root.stat().st_uid != os.getuid():
            raise cli.LearningError('state root must be owned by the current user')
        self.receipt_file = self.store.root / 'mcp-receipts.json'

    def state_and_policies(self):
        state = self.store.load()
        policies = {}
        ids = set()
        for item in state['preferences']:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] in ids:
                raise cli.LearningError('invalid preference record')
            ids.add(item['id'])
            cli.scope_name(item.get('scope'))
            text_value(item.get('rule'), 'rule', 200)
            if item.get('status') not in ('pending', 'approved'):
                raise cli.LearningError('invalid preference status')
            if item['status'] == 'approved':
                history = item.get('history', [])
                if not isinstance(history, list) or not any(isinstance(h, dict) and h.get('status') == 'approved'
                                                           and h.get('approval_note') for h in history):
                    raise cli.LearningError('incomplete approval record')
        scopes = {p['scope'] for p in state['preferences']}
        directory = self.store.root / 'standards'
        if directory.exists() or directory.is_symlink():
            cli.ensure_real_dir(directory)
            files = list(directory.glob('*.md'))
            if len(files) > 100:
                raise cli.LearningError('too many scoped standards')
            scopes.update(cli.scope_name(p.stem) for p in files)
        if len(scopes) > 100:
            raise cli.LearningError('too many scopes')
        for scope in sorted(scopes):
            data = cli.read_regular(self.store.standard_path(scope))
            if data is None:
                if any(p['scope'] == scope and p['status'] == 'approved' for p in state['preferences']):
                    raise cli.LearningError('missing approved projection')
                continue
            blocks = cli.verify_projection(scope, data, state['preferences'])
            if blocks:
                policies[scope] = [{'id': pid, 'rule': rule} for pid, rule in sorted(blocks.items())]
        return state, policies

    def managed_policies(self):
        if self.policy_root is None:
            return None
        checked_directory(self.policy_root)
        references = self.policy_root / 'references'
        checked_directory(references)
        policies = {}
        for scope in (*POLICY_SCOPES, 'router'):
            path = self.policy_root / 'ROUTER.md' if scope == 'router' else references / (scope + '.md')
            data = cli.read_regular(path)
            if data is None:
                continue
            if len(data) > MAX_POLICY:
                raise cli.LearningError('configured policy exceeds size limit')
            try:
                policies[scope] = data.decode('utf-8')
            except UnicodeError as exc:
                raise cli.LearningError('configured policy is not UTF-8') from exc
        return policies

    def receipts(self):
        raw = cli.read_regular(self.receipt_file)
        if raw is None:
            return {'version': 1, 'receipts': {}, 'overflow_count': 0}
        try:
            value = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise cli.LearningError('invalid receipt index') from exc
        if (not isinstance(value, dict) or set(value) != {'version', 'receipts', 'overflow_count'}
                or value['version'] != 1 or not isinstance(value['receipts'], dict)
                or len(value['receipts']) > MAX_RECEIPTS
                or type(value['overflow_count']) is not int or not 0 <= value['overflow_count'] <= 2147483647):
            raise cli.LearningError('invalid receipt index')
        for key, receipt in value['receipts'].items():
            if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key) or not isinstance(receipt, dict):
                raise cli.LearningError('invalid receipt record')
            if set(receipt) != {'receipt_id', 'session_hash', 'first_turn_hash', 'turn_hash', 'observed_at', 'last_observed_at', 'policy_version', 'policy_fingerprint'}:
                raise cli.LearningError('invalid receipt record')
            if receipt['receipt_id'] != key or receipt['policy_version'] != 1:
                raise cli.LearningError('invalid receipt identity')
            for field in ('session_hash', 'first_turn_hash', 'turn_hash', 'policy_fingerprint'):
                if not isinstance(receipt[field], str) or not re.fullmatch('[a-f0-9]{64}', receipt[field]):
                    raise cli.LearningError('invalid receipt digest')
            for field in ('observed_at', 'last_observed_at'):
                if not isinstance(receipt[field], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?\+00:00', receipt[field]):
                    raise cli.LearningError('invalid receipt time')
        return value

    def archive_receipts(self, index):
        # Called only under the canonical Store lock. Archive the exact validated
        # active bytes first; a failed active commit leaves a safe retryable copy.
        raw = cli.read_regular(self.receipt_file)
        if raw is None or json.loads(raw) != index:
            raise cli.LearningError('receipt index changed before archival')
        month = dt.datetime.now().strftime('%Y-%m')
        archive_root = self.store.root / 'Old'
        directory = archive_root / month
        for path in (archive_root, directory):
            cli.ensure_real_dir(path)
            if path.stat().st_uid != os.getuid():
                raise cli.LearningError('archive directory must be owned by current user')
        path = directory / ('receipts-' + hashlib.sha256(raw).hexdigest() + '.json')
        prior = cli.read_regular(path)
        if prior is None:
            cli.atomic_write(path, raw)
        elif prior != raw:
            raise cli.LearningError('receipt archive already contains different bytes')
        retained = sorted(index['receipts'].items(), key=lambda item: item[1]['last_observed_at'])[-RETAIN_RECEIPTS:]
        return {'version': 1, 'receipts': dict(retained),
                'overflow_count': min(2147483647, index['overflow_count'] + 1)}

    def propose(self, state, scope, rule, source_ref):
        scope = cli.scope_name(scope)
        rule = text_value(rule, 'rule', 200)
        source_ref = text_value(source_ref, 'source reference', 160)
        for item in state['preferences']:
            if item.get('source_ref') == source_ref:
                if item['rule'] != rule or item['scope'] != scope:
                    raise cli.LearningError('source reference already identifies a different proposal')
                return {'id': item['id'], 'status': item['status'], 'duplicate': True}
        used = {p['id'] for p in state['preferences']}
        number = len(used) + 1
        while 'p%04d' % number in used:
            number += 1
        item = {'id': 'p%04d' % number, 'scope': scope, 'rule': rule, 'status': 'pending',
                'source_ref': source_ref, 'history': [{'status': 'proposed', 'date': cli.today()}]}
        state['preferences'].append(item)
        self.store.save(state)
        return {'id': item['id'], 'status': 'pending', 'duplicate': False}

    def call(self, name, args):
        output = self._call(name, args)
        if name == 'prompt_checkpoint' and args.get('as_hook') is True:
            if output.get('skipped') or not MATERIAL.search(args.get('prompt', '')):
                return {}
            return {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                           'additionalContext': 'Policy: read_scoped_policy'}}
        return output

    def _call(self, name, args):
        definition = next((tool for tool in TOOLS if tool['name'] == name), None)
        if definition is None:
            raise cli.LearningError('unknown tool')
        expected = definition['inputSchema']
        if (not isinstance(args, dict) or set(args) - set(expected['properties'])
                or set(expected['required']) - set(args)):
            raise cli.LearningError('invalid tool arguments')
        for key, value in args.items():
            kind = expected['properties'][key]['type']
            if (kind == 'string' and not isinstance(value, str)) or (kind == 'boolean' and type(value) is not bool):
                raise cli.LearningError('invalid argument type')
        with self.store.lock():
            state, policies = self.state_and_policies()
            managed = self.managed_policies()
            fingerprint = digest({'approved': policies, 'configured': managed})
            if name == 'read_scoped_policy':
                scope = cli.scope_name(args['scope'])
                if managed is not None and scope in (*POLICY_SCOPES, 'router'):
                    return {'scope': scope, 'policy': managed.get(scope, ''),
                            'provenance': 'operator-configured policy root; not authenticated human approval',
                            'policy_fingerprint': fingerprint}
                return {'scope': scope, 'rules': policies.get(scope, []), 'policy_fingerprint': fingerprint}
            if name == 'propose_rule':
                return self.propose(state, **args)
            index = self.receipts()
            if name == 'learning_status':
                return {'preferences': len(state['preferences']),
                        'pending': sum(p['status'] == 'pending' for p in state['preferences']),
                        'approved': sum(p['status'] == 'approved' for p in state['preferences']),
                        'failures': len(state['failures']), 'policy_version': 1, 'policy_fingerprint': fingerprint,
                        'receipt_count': len(index['receipts']), 'receipt_limit': MAX_RECEIPTS,
                        'receipt_unit': 'sessions', 'maintenance_required': False,
                        'archived_batches': index['overflow_count'],
                        'overflow_count': index['overflow_count'], 'receipts': list(index['receipts'].values())[-3:]}
            session = text_value(args['session_id'], 'session ID', 160)
            turn = text_value(args['turn_id'], 'turn ID', 160)
            if 'cwd' in args:
                text_value(args['cwd'], 'cwd', 1024)  # Metadata only, never traversed or retained.
            if args.get('agent_id') or args.get('scheduled') or args.get('source', '').lower() in ('agent', 'scheduled', 'automation', 'subagent'):
                return {'skipped': True, 'reason': 'agent or scheduled input', 'additional_context': ''}
            if 'agent_id' in args:
                # Even an empty supplied agent field cannot establish human input.
                return {'skipped': True, 'reason': 'agent identity supplied', 'additional_context': ''}
            if 'source' in args and args['source'] != 'user':
                raise cli.LearningError('unsupported input source')
            key, turn_hash = digest(session), digest(turn)
            source_key = digest([session, turn])
            prior = index['receipts'].get(key)
            if prior is not None and prior['turn_hash'] == turn_hash and prior['policy_fingerprint'] == fingerprint:
                return {'receipt': prior, 'duplicate': True, 'additional_context': ''}
            prompt = args.get('prompt', '')
            if len(prompt) > MAX_LINE:
                raise cli.LearningError('prompt exceeds input limit')
            proposal = None
            match = EXPLICIT.fullmatch(prompt.strip())
            if match:
                # Reject sensitive material anywhere in an explicit request. Never
                # truncate a secret or long instruction into a misleading rule.
                rule = text_value(match.group(1), 'remember request', 200)
                proposal = self.propose(state, 'unscoped', rule, 'checkpoint:' + source_key[:32])
            if prior is None and len(index['receipts']) >= MAX_RECEIPTS:
                index = self.archive_receipts(index)
            observed = dt.datetime.now(dt.timezone.utc).isoformat(timespec='microseconds')
            receipt = {'receipt_id': key, 'session_hash': key,
                       'first_turn_hash': prior['first_turn_hash'] if prior else turn_hash, 'turn_hash': turn_hash,
                       'observed_at': prior['observed_at'] if prior else observed, 'last_observed_at': observed,
                       'policy_version': 1, 'policy_fingerprint': fingerprint}
            index['receipts'][key] = receipt
            cli.atomic_write(self.receipt_file, self.store.encoded(index))
            result = {'receipt': receipt, 'duplicate': False, 'additional_context': ''}
            if proposal:
                result['proposal'] = proposal
            return result


class Server:
    def __init__(self, broker):
        self.broker = broker
        self.initialized = False

    @staticmethod
    def error(request_id, code, message):
        return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}

    def handle(self, request):
        if (not isinstance(request, dict) or request.get('jsonrpc') != '2.0'
                or not isinstance(request.get('method'), str)
                or ('id' in request and (type(request['id']) not in (str, int) and request['id'] is not None))):
            return self.error(None, -32600, 'Invalid Request')
        if 'id' not in request:
            return None  # JSON-RPC notifications never receive replies.
        request_id, method = request['id'], request['method']
        params = request.get('params', {})
        if not isinstance(params, dict):
            return self.error(request_id, -32602, 'Invalid params')
        if method == 'initialize':
            protocol = params.get('protocolVersion')
            if not isinstance(protocol, str):
                return self.error(request_id, -32602, 'protocolVersion is required')
            self.initialized = True
            result = {'protocolVersion': protocol if protocol in PROTOCOLS else PROTOCOLS[-1],
                      'capabilities': {'tools': {'listChanged': False}},
                      'serverInfo': {'name': 'workflow-hooks-learning', 'version': '1.0.0'}}
        elif not self.initialized:
            return self.error(request_id, -32000, 'Initialize first')
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': TOOLS}
        elif method == 'tools/call':
            if not isinstance(params.get('name'), str):
                return self.error(request_id, -32602, 'Tool name is required')
            try:
                output = self.broker.call(params['name'], params.get('arguments', {}))
                result = {'content': [{'type': 'text', 'text': json.dumps(output, ensure_ascii=False)}]}
            except (cli.LearningError, OSError, ValueError, TypeError, KeyError):
                # Do not echo caller values, private paths, or filesystem errors.
                hook_mode = (params['name'] == 'prompt_checkpoint' and isinstance(params.get('arguments'), dict)
                             and params['arguments'].get('as_hook') is True)
                error_text = '{}' if hook_mode else 'Learning request rejected: invalid input or unsafe/inconsistent local state.'
                result = {'isError': True, 'content': [{'type': 'text', 'text': error_text}]}
        else:
            return self.error(request_id, -32601, 'Method not found')
        return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def serve(server, source, target):
    while True:
        line = source.readline(MAX_LINE + 1)
        if not line:
            break
        oversized = len(line) > MAX_LINE
        if oversized:
            while line and not line.endswith(b'\n'):
                line = source.readline(MAX_LINE + 1)
            response = server.error(None, -32700, 'Request exceeds line limit')
        else:
            try:
                response = server.handle(json.loads(line))
            except (UnicodeError, ValueError, RecursionError):
                response = server.error(None, -32700, 'Parse error')
        if response is not None:
            target.write(json.dumps(response, ensure_ascii=False, separators=(',', ':')) + '\n')
            target.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=Path.home() / '.local/share/workflow-hooks-kit/learning')
    parser.add_argument('--policy-root', type=Path, help='Optional operator-configured read-only scoped policy root')
    args = parser.parse_args(argv)
    try:
        serve(Server(Broker(args.state_dir, args.policy_root)), sys.stdin.buffer, sys.stdout)
    except (cli.LearningError, OSError):
        print('learning MCP: unsafe or unavailable local state', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
