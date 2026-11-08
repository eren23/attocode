"""Bounded, isolated CI probe of the Registry's uvx command; never publish."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VERSION = r'[0-9]+(?:\.[0-9]+){2}(?:(?:a|b|rc)[0-9]+)?'


def _environment(root):
    # A listed-command check must not resolve through checkout/user configuration
    # or inherit provider credentials. Every tool/cache/config directory is owned.
    keep = {'PATH', 'SYSTEMROOT', 'WINDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'LANG', 'LC_ALL'}
    env = {key: value for key, value in os.environ.items() if key in keep}
    for name in ['home', 'work']:
        (root / name).mkdir()
    env.update(HOME=str(root / 'home'), XDG_CONFIG_HOME=str(root / 'config'),
               UV_CACHE_DIR=str(root / 'cache'), UV_TOOL_DIR=str(root / 'tools'),
               UV_TOOL_BIN_DIR=str(root / 'bin'), UV_PYTHON_INSTALL_DIR=str(root / 'python'),
               UV_NO_CONFIG='1', UV_NO_PROGRESS='1')
    return env


def _invoke(command, root, env, deadline):
    try:
        process = subprocess.Popen(command, cwd=root / 'work', env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8', errors='replace',
                                   start_new_session=os.name == 'posix')
    except OSError as error:
        return 127, '', str(error), False
    try:
        # Process creation cannot be interrupted by communicate's timeout. Charge
        # that elapsed time to the same deadline before granting any wait.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, 0)
        out, err = process.communicate(timeout=remaining)
        return process.returncode, out, err, False
    except subprocess.TimeoutExpired:
        try:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        try:
            out, err = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            process.stdout.close()
            process.stderr.close()
            process.wait(timeout=1)
            out, err = '', 'Owned probe pipes did not close before cleanup deadline'
        return process.returncode, out, err, True


def probe_install(version, *, uvx='uvx', attempts=8, seconds=300, delay=5, checkpoint=None):
    if not isinstance(version, str) or not re.fullmatch(VERSION, version):
        raise ValueError('Unsupported release version')
    if not isinstance(attempts, int) or not 1 <= attempts <= 8:
        raise ValueError('Attempt limit must be between 1 and 8')
    if (not isinstance(seconds, (int, float)) or not math.isfinite(seconds)
            or not 0 < seconds <= 300):
        raise ValueError('Shared deadline must be finite and between 0 and 300 seconds')
    if (not isinstance(delay, (int, float)) or not math.isfinite(delay) or not 0 <= delay <= 60):
        raise ValueError('Initial delay must be finite and between 0 and 60 seconds')
    started = time.monotonic()
    deadline = started + seconds
    result = {'schema_version': 1, 'version': version, 'status': 'incomplete',
              'attempts': [], 'limits': {'attempts': attempts, 'seconds': seconds,
                                        'initial_delay': delay, 'maximum_delay': 60},
              'operator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'owned_scratch_removed': False}
    expected = 'attocode-code-intel ' + version
    missing = re.compile(r'\bno version of attocode-code-intel==' + re.escape(version)
                         + r'(?![A-Za-z0-9.!+_-])', re.I)
    reason = 'attempts_exhausted'
    with tempfile.TemporaryDirectory(prefix='registry-install-') as temporary:
        root = Path(temporary)
        env = _environment(root)
        command = [str(uvx), '--python', str(Path(sys.executable).resolve()),
                   '--default-index', 'https://pypi.org/simple',
                   '--refresh-package', 'attocode-code-intel', '--from',
                   'attocode-code-intel==' + version, 'attocode-code-intel', '--version']
        result['command'] = command
        for attempt in range(1, attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = 'deadline_exceeded'
                break
            before = time.monotonic()
            code, out, err, timed_out = _invoke(command, root, env, deadline)
            if timed_out or time.monotonic() >= deadline:
                outcome = 'deadline_exceeded'
            elif code == 0:
                outcome = 'passed' if out.strip() == expected else 'unexpected_version'
            else:
                outcome = 'version_unavailable' if missing.search(err) else 'install_failed'
            result['attempts'].append({'attempt': attempt, 'exit_code': code, 'reason': outcome,
                                       'seconds': time.monotonic() - before,
                                       'stdout': out[:4096], 'stderr': err[:16384],
                                       'output_truncated': len(out) > 4096 or len(err) > 16384})
            if checkpoint:
                checkpoint(result)
            if outcome == 'passed':
                reason = None
                break
            if outcome != 'version_unavailable':
                reason = outcome
                break
            if attempt == attempts:
                break
            wait = min(delay * 2 ** (attempt - 1), 60)
            remaining = deadline - time.monotonic()
            if remaining <= wait:
                if remaining > 0:
                    time.sleep(remaining)
                reason = 'deadline_exceeded'
                break
            time.sleep(wait)
    result.update(status='passed' if reason is None else 'failed', reason=reason,
                  seconds=time.monotonic() - started, owned_scratch_removed=not root.exists())
    if not result['owned_scratch_removed']:
        result.update(status='failed', reason='cleanup_failed')
    return result


def _write(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.' + path.name,
                                     delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, indent=2)
        handle.write('\n')
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--allow-downloads', action='store_true')
    parser.add_argument('--attempts', type=int, default=8)
    parser.add_argument('--seconds', type=float, default=300)
    parser.add_argument('--delay', type=float, default=5)
    args = parser.parse_args(argv)
    last = {'version': args.version, 'status': 'incomplete', 'attempts': [],
            'owned_scratch_removed': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.report.open('x') as handle:
            json.dump(last, handle)
            handle.write('\n')
    except FileExistsError:
        print('Refusing to overwrite an existing Registry probe report', file=sys.stderr)
        return 1
    def checkpoint(value):
        nonlocal last
        last = value
        _write(args.report, value)
    try:
        if not args.allow_downloads:
            raise ValueError('Registry install probe requires --allow-downloads on CI/a disposable worker')
        result = probe_install(args.version, attempts=args.attempts, seconds=args.seconds,
                               delay=args.delay, checkpoint=checkpoint)
    except Exception as error:
        result = {**last, 'status': 'failed', 'reason': 'probe_error', 'error': str(error)}
    _write(args.report, result)
    print(json.dumps(result))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
