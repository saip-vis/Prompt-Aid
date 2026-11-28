"""Identify narrow installed runtime resources and non-project preflight probes."""
import re
import shutil
import sys
from pathlib import Path


def runtime_reads(source, checks):
    executables = [Path(sys.executable), Path(source)/'.venv/bin/python']
    for check in checks:
        if check['kind'] != 'command':
            continue
        name = check['argv'][0]
        path = Path(source)/name if '/' in name and not Path(name).is_absolute() else Path(shutil.which(name) or name)
        executables.append(path)
    reads = set()
    for executable in executables:
        if not executable.is_file():
            continue
        path = executable.resolve()
        parts = path.parts
        # Python.org builds keep their shared library beside bin/, outside :minimal.
        if str(path).startswith('/Library/Frameworks/Python.framework/Versions/') and len(parts) >= 7:
            reads.add(str(Path(*parts[:6])))
        # A Homebrew formula's runtime and modules, never the whole Cellar/home.
        for base in ['/opt/homebrew/Cellar', '/usr/local/Cellar']:
            try:
                relative = path.relative_to(base)
                if len(relative.parts) >= 3:
                    reads.add(str(Path(base, *relative.parts[:2])))
            except ValueError:
                pass
    return sorted(reads)


def runtime_probe(check):
    if check['kind'] != 'command':
        return None
    argv = check['argv']; name = Path(argv[0]).name
    if re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', name):
        code = 'import sys; print("Python runtime ready", sys.version.split()[0])'
        if len(argv) >= 3 and argv[1:3] == ['-m', 'pytest']:
            code = 'import pytest; ' + code
        return [argv[0], '-I', '-c', code]
    if name in {'node', 'npm', 'pnpm', 'yarn', 'swift', 'cargo', 'go'}:
        return [argv[0], '--version'] if name != 'go' else [argv[0], 'version']
    # Never guess a --version flag for arbitrary project commands.
    return None
