"""Bounded macOS single-process checks using the actual Seatbelt backend.

Passed means process exit zero, never semantic QA approval. Fork/spawn, network,
Mach services and writes outside private scratch are denied. Project and selected
system runtime files remain readable; metadata is readable globally. This is not
a general hostile-code security claim or storage quota. No model calls are used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

BACKEND = '/usr/bin/sandbox-exec'
MAX_OUTPUT = 8192
SYSTEM_ROOTS = ('/System', '/usr', '/bin', '/sbin', '/opt/homebrew',
                '/Library/Frameworks/Python.framework',
                '/Library/Developer/CommandLineTools')


def _within(path, parent):
    return path == parent or parent in path.parents


def _validate(root, body):
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError('An absolute protected project directory is required')
    for directory in (root,) + tuple(root.parents):
        mode = directory.lstat().st_mode
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            raise ValueError('Project directory and ancestors must not be symlinks')
    root = root.resolve(strict=True)
    if len(root.parts) < 3 or _within(Path.home().resolve(), root):
        raise ValueError('A specific project directory, not a broad root, is required')
    if root in tuple(Path(p) for p in SYSTEM_ROOTS) + (Path('/private/tmp'),):
        raise ValueError('A specific project directory is required')
    if not isinstance(body, dict) or set(body) - {'argv', 'timeout'}:
        raise ValueError('Check accepts only argv and optional timeout')
    argv = body.get('argv')
    if (not isinstance(argv, list) or not 1 <= len(argv) <= 32
            or any(not isinstance(a, str) or '\0' in a for a in argv)
            or sum(len(a) for a in argv) > 8192 or not argv[0]):
        raise ValueError('argv must contain one to 32 strings, at most 8192 characters')
    executable = Path(argv[0])
    if not executable.is_absolute():
        raise ValueError('An absolute executable is required')
    executable = executable.resolve(strict=True)
    allowed = (root,) + tuple(Path(p).resolve() for p in SYSTEM_ROOTS)
    if not any(_within(executable, p) for p in allowed):
        raise ValueError('Executable must be inside the project or a supported runtime root')
    if not executable.is_file() or not os.access(str(executable), os.X_OK):
        raise ValueError('Executable must be an executable regular file')
    timeout = body.get('timeout', 3)
    if type(timeout) is not int or not 1 <= timeout <= 3:
        raise ValueError('timeout must be an integer from one to three seconds')
    return root, [str(executable)] + argv[1:], timeout


def _profile(root, scratch):
    # JSON quoting escapes Seatbelt string metacharacters; UTF-8 stays literal.
    quote = lambda p: json.dumps(str(p), ensure_ascii=False)
    readable = (root, scratch) + tuple(Path(p).resolve() for p in SYSTEM_ROOTS)
    filters = ' '.join('(subpath %s)' % quote(p) for p in readable)
    return ('(version 1)(deny default)(allow file-read-metadata)'
            '(allow file-read-data file-map-executable (literal "/") ' + filters + ')'
            '(allow file-read-data (literal "/dev/null") (literal "/dev/random")'
            ' (literal "/dev/urandom"))(allow process-exec)(allow sysctl-read)'
            '(allow file-write* (subpath ' + quote(scratch) + '))')


def _stop(process):
    # Only our newly created group is targeted, including after normal exit.
    # The profile independently denies fork/spawn, preventing setsid escapes.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=1)


def _execute(argv, profile, root, env, deadline):
    data = bytearray()
    process = None
    status, returncode = 'failed', None
    try:
        process = subprocess.Popen([BACKEND, '-p', profile] + argv,
            cwd=str(root), env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            shell=False, close_fds=True, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    status = 'timed-out'
                    break
                for key, _mask in selector.select(min(remaining, 0.025)):
                    chunk = os.read(key.fd, MAX_OUTPUT - len(data) + 1)
                    if chunk:
                        data.extend(chunk[:MAX_OUTPUT - len(data)])
                        if len(data) >= MAX_OUTPUT:
                            status = 'output-limit'
                            break
                    else:
                        selector.unregister(key.fileobj)
                if status == 'output-limit':
                    break
                returncode = process.poll()
                if returncode is not None:
                    while len(data) < MAX_OUTPUT:
                        try:
                            chunk = os.read(process.stdout.fileno(), MAX_OUTPUT - len(data))
                        except BlockingIOError:
                            break
                        if not chunk:
                            break
                        data.extend(chunk)
                    status = 'output-limit' if len(data) >= MAX_OUTPUT else (
                        'passed' if returncode == 0 else 'failed')
                    break
    except OSError as exc:
        data = bytearray(('Backend execution failed: ' + str(exc)).encode()[:MAX_OUTPUT])
    finally:
        if process is not None:
            _stop(process)
            returncode = process.returncode
            process.stdout.close()
    output = data.decode('utf-8', errors='replace').encode('utf-8')[:MAX_OUTPUT]
    return status, returncode, output.decode('utf-8', errors='ignore')


def _cleanup(scratch):
    """Bounded descriptor-relative cleanup that never follows created links.

    Large/deep trees stay private and are reported as retained. This avoids an
    unbounded recursive cleanup after adversarial file creation.
    """
    budget = [128]

    def clean(fd, depth):
        if depth > 8:
            return False
        with os.scandir(fd) as entries:
            for entry in entries:
                budget[0] -= 1
                if budget[0] < 0:
                    return False
                if entry.is_dir(follow_symlinks=False):
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        if not clean(child, depth + 1):
                            return False
                    finally:
                        os.close(child)
                    os.rmdir(entry.name, dir_fd=fd)
                else:
                    os.unlink(entry.name, dir_fd=fd)
        return True

    try:
        fd = os.open(str(scratch), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            complete = clean(fd, 0)
        finally:
            os.close(fd)
        if complete:
            scratch.rmdir()
        return complete
    except OSError:
        return False


def _preflight(python, profile, root, env, deadline, outside):
    # Only expendable parent-created canaries are probed, never project files.
    code = '''import os, socket, errno
p = os.environ['TMPDIR'] + '/preflight'
with open(p, 'w') as f: f.write('scratch')
assert open(p).read() == 'scratch'
blocked = 0
for operation in (lambda: open(%r).read(), lambda: open(%r, 'w'),
                  lambda: os.fork(),
                  lambda: os.posix_spawn('/usr/bin/true', ['true'], {}),
                  lambda: socket.socket().connect(('127.0.0.1', 9))):
    try: operation()
    except OSError as error:
        assert error.errno in (errno.EPERM, errno.EACCES)
        blocked += 1
assert blocked == 5
print('seatbelt-preflight-ok')
''' % (str(outside), str(outside))
    status, _code, output = _execute([str(python), '-I', '-S', '-c', code],
                                    profile, root, env, deadline)
    return status == 'passed' and output.strip() == 'seatbelt-preflight-ok'


def run(root: Path, body: dict) -> dict:
    """Run validated argv; invalid requests raise ValueError before execution.

    Checks needing child processes are deliberately outside the supported scope.
    """
    started = time.monotonic()
    root, argv, timeout = _validate(root, body)
    result = {'status': 'unsupported', 'returncode': None, 'output': '',
              'elapsed': 0.0, 'backend': 'none'}
    if sys.platform != 'darwin' or not Path(BACKEND).is_file() or not os.access(BACKEND, os.X_OK):
        result['output'] = 'A working macOS sandbox-exec backend is required'
        result['elapsed'] = round(time.monotonic() - started, 3)
        return result
    python = Path(sys.executable).resolve()
    if not any(_within(python, Path(p).resolve()) for p in SYSTEM_ROOTS):
        result['output'] = 'A supported trusted Python runtime is required for backend verification'
        result['elapsed'] = round(time.monotonic() - started, 3)
        return result
    scratch = Path(tempfile.mkdtemp(prefix='workflow-check-', dir='/private/tmp')).resolve()
    os.chmod(str(scratch), 0o700)
    if _within(scratch, root):
        _cleanup(scratch)
        raise ValueError('Scratch storage must be outside the protected project')
    fixture = Path(tempfile.mkdtemp(prefix='workflow-check-canary-', dir='/private/tmp')).resolve()
    outside = fixture / 'private-canary'
    outside.write_text('private-backend-canary', encoding='utf-8')
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(scratch),
           'TMPDIR': str(scratch), 'PYTHONDONTWRITEBYTECODE': '1',
           'XDG_CACHE_HOME': str(scratch)}
    profile = _profile(root, scratch)
    deadline = started + timeout
    try:
        if not _preflight(python, profile, root, env, deadline, outside):
            result['output'] = 'Actual Seatbelt confinement verification failed; command was not executed'
        else:
            status, returncode, output = _execute(argv, profile, root, env, deadline)
            result.update(status=status, returncode=returncode, output=output)
        result['backend'] = BACKEND
    finally:
        result['scratch_retained'] = not _cleanup(scratch)
        _cleanup(fixture)
        result['elapsed'] = round(time.monotonic() - started, 3)
    return result
