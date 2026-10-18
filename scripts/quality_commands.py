"""Bounded command planner for trusted project checks, not a code sandbox.

Expands npm scripts and lifecycle hooks into explicit argv steps. It never
runs npm/npx, installs packages, evaluates a shell or authorizes project code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

BLOCKED = {'deploy', 'publish', 'release', 'push', 'migrate', 'migration', 'seed',
           'sync', 'start', 'dev', 'serve', 'upload', 'send', 'production', 'prod'}
TOOLS = {'tsc', 'vue-tsc', 'eslint', 'vitest', 'jest', 'prettier', 'vite', 'webpack',
         'rollup', 'tsup', 'astro', 'svelte-check', 'ruff', 'pytest', 'mypy', 'next'}
MODULES = {'pytest', 'unittest', 'compileall', 'ruff', 'mypy'}
UNSAFE = re.compile(r'[;&|<>`$%!^()\r\n\x00]')
MAX_STEPS = 128
POLICY_VERSION = '2.0'


class Refused(ValueError):
    pass


def tokens(command):
    if isinstance(command, str):
        if len(command) > 8192:
            raise Refused('Command too long')
        if any(c in command for c in '\r\n\x00') or re.search(r'''\\['"]''', command):
            raise Refused('Multiline commands and escaped quotes require manual review')
        quote = None
        i = 0
        while i < len(command):
            c = command[i]
            if c in "'\"":
                if quote == c: quote = None
                elif quote is None: quote = c
            if c == '&':
                if quote or command[i:i+2] != '&&' or i == 0 or i+2 == len(command) or not command[i-1].isspace() or not command[i+2].isspace():
                    raise Refused('Only literal whitespace-separated && chains are supported')
                i += 1
            i += 1
        try:
            parts = shlex.split(command, posix=True)
        except ValueError:
            raise Refused('Unbalanced command quoting') from None
    elif isinstance(command, list):
        parts = list(command)
        if '&&' in parts:
            raise Refused('An argv array is one command, not a shell chain')
    else:
        raise Refused('Command must be a string or argv array')
    if not parts or len(parts) > 256 or any(not isinstance(x, str) or not x or len(x) > 4096 for x in parts):
        raise Refused('Invalid command arguments')
    if any(UNSAFE.search(x) for x in parts if x != '&&'):
        raise Refused('Shell expansion, operators or dynamic arguments require manual review')
    return parts


def package(project):
    path = Path(project) / 'package.json'
    if not path.exists():
        return {}, None
    with path.open('rb') as stream:
        data = stream.read(1_000_001)
    if len(data) > 1_000_000:
        raise Refused('package.json too large')
    try:
        value = json.loads(data.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise Refused('Invalid package.json') from None
    scripts = value.get('scripts', {}) if isinstance(value, dict) else None
    if not isinstance(scripts, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in scripts.items()):
        raise Refused('package.json scripts must map names to command strings')
    return scripts, hashlib.sha256(data).hexdigest()


def blocked(value):
    return any(re.search(r'\b' + word + r'\b', value.lower()) for word in BLOCKED)


def local_entry(project, value, extensions):
    path = (Path(project) / value).resolve()
    if Path(project).resolve() not in path.parents or path.suffix.lower() not in extensions or not path.is_file():
        raise Refused('Check entry point must be an existing project file')


def compile_plan(project, command):
    project = Path(project).resolve()
    scripts, fingerprint = package(project)
    steps = []

    def script(name, stack, forwarded=(), hooks=True):
        if name in stack or len(stack) >= 16:
            raise Refused('Cyclic or excessively deep npm script reference')
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,119}', name) or blocked(name):
            raise Refused('Unsafe npm script name')
        if name not in scripts:
            raise Refused('Referenced npm script is missing')
        path = stack + (name,)
        if hooks and 'pre' + name in scripts:
            script('pre' + name, path, hooks=False)
        before = len(steps)
        body = tokens(scripts[name])
        if forwarded and ('&&' in body or body[0] == 'npm'):
            raise Refused('Forwarding through nested npm or a chain requires explicit check commands')
        expand(body, path)
        if len(steps) == before:
            raise Refused('Empty npm script')
        if forwarded:
            steps[-1]['argv'].extend(forwarded)
        hook = 'post' + name
        if hooks and hook in scripts:
            script(hook, path, hooks=False)

    def leaf(argv, stack):
        if len(steps) >= MAX_STEPS:
            raise Refused('Too many expanded command steps')
        if any(blocked(x) for x in argv):
            raise Refused('Deployment, external write or long-running command refused')
        executable = argv[0]
        # Explicit paths are supported only for the current Python interpreter.
        python = executable.lower() in {'python', 'python3', 'python.exe', 'python3.exe'} or executable == sys.executable
        name = Path(executable).name.lower().removesuffix('.exe')
        if not python and (executable != name or '/' in executable or '\\' in executable):
            raise Refused('Executable paths require manual review')
        if python:
            if len(argv) >= 3 and argv[1] == '-m' and argv[2] in MODULES:
                pass
            elif len(argv) >= 2 and not argv[1].startswith('-'):
                local_entry(project, argv[1], {'.py'})
            else:
                raise Refused('Inline Python or unsupported interpreter options refused')
            argv = [sys.executable, *argv[1:]]
        elif name == 'node':
            if len(argv) < 2:
                raise Refused('Node needs a check entry point')
            if argv[1] in {'--test', '--check'}:
                # --test may discover files; reject additional executable-loading options.
                if any(x in {'-e', '--eval', '-p', '--print', '-r', '--require', '--import', '--loader'}
                       or x.startswith(('--eval=', '--require=', '--import=', '--loader=')) for x in argv[2:]):
                    raise Refused('Dynamic Node entry point refused')
            elif not argv[1].startswith('-'):
                local_entry(project, argv[1], {'.js', '.mjs', '.cjs'})
            else:
                raise Refused('Inline Node or unsupported runtime options refused')
        elif name in TOOLS:
            if any(x.split('=')[0] in {'--watch', '--watchAll', '-w', '--write', '--install-types', '--init',
                                      '--updateSnapshot', '--update-snapshots', '-u'} or x.startswith('--fix') for x in argv[1:]):
                raise Refused('Watch and source-rewriting modes are not automatic checks')
            if name in {'vite', 'vitest'} and (len(argv) < 2 or argv[1] != ('build' if name == 'vite' else 'run')):
                raise Refused('Only finite build/run tool modes are supported')
            if name == 'prettier' and not any(x in {'--check', '--list-different'} for x in argv[1:]):
                raise Refused('Prettier automatic checks require --check or --list-different')
            if name == 'ruff' and (len(argv) < 2 or argv[1] not in {'check', 'format'}
                                    or (argv[1] == 'format' and '--check' not in argv[2:])):
                raise Refused('Ruff requires check or format --check')
            if name in {'next', 'astro'} and (len(argv) < 2 or argv[1] not in {'build', 'check', 'lint'}):
                raise Refused('Only finite check/build tool modes are supported')
            if name in {'vitest', 'jest'} and any(x in {'--watch', '--watchAll'} for x in argv[1:]):
                raise Refused('Watch mode is not a finite check')
        else:
            raise Refused('Executable is outside the check-tool allowlist')
        steps.append({'argv': argv, 'script_path': list(stack)})

    def expand(argv, stack=()):
        if '&&' in argv:
            start = 0
            for i in range(len(argv) + 1):
                if i == len(argv) or argv[i] == '&&':
                    if i == start:
                        raise Refused('Empty command in chain')
                    expand(argv[start:i], stack)
                    start = i + 1
            return
        if any(blocked(x) for x in argv):
            raise Refused('Deployment, external write or long-running command refused')
        if argv[0] == 'npm':
            if len(argv) == 2 and argv[1] == 'test':
                script('test', stack)
            elif len(argv) >= 3 and argv[1] in {'run', 'run-script'}:
                if len(argv) > 3 and argv[3] != '--':
                    raise Refused('npm forwarding requires a literal -- separator')
                script(argv[2], stack, argv[4:])
            else:
                raise Refused('Only explicit npm test/run scripts are supported')
        elif argv[0] == 'npx':
            if len(argv) < 3 or argv[1] != '--no-install':
                raise Refused('npx requires --no-install; package installation is not allowed')
            leaf(argv[2:], stack)
        else:
            leaf(argv, stack)

    expand(tokens(command))
    return {'steps': steps, 'package_sha256': fingerprint}


def verify_snapshot(project, plan):
    if package(project)[1] != plan['package_sha256']:
        raise Refused('package.json changed after preflight; start a fresh gate')


def resolve_argv(project, argv):
    if argv[0] == sys.executable:
        return argv
    name = argv[0]
    search = os.environ.get('PATH', '')
    if name in TOOLS:
        search = str(Path(project) / 'node_modules' / '.bin') + os.pathsep + search
    executable = shutil.which(name, path=search)
    if not executable:
        raise Refused('Required check executable is not installed')
    return [executable, *argv[1:]]
