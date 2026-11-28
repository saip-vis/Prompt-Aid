"""Bounded, read-only test discovery. Never imports project code or runs scripts."""
import ast
import json
import os
import re
import tomllib
from pathlib import Path


def suggest_checks(root):
    root = Path(root)
    notices = []

    def regular_file(relative):
        path = root / relative
        return not path.is_symlink() and path.is_file()

    def read(relative):
        path = root / relative
        # Do not read manifests redirected to another project, or special files.
        if path.is_symlink():
            return ''
        try:
            if not path.is_file() or path.stat().st_size > 64000:
                return ''
            with path.open('rb') as stream:
                return stream.read(64001).decode('utf-8')[:64000]
        except (OSError, UnicodeError):
            return ''

    def test_directory(name):
        path = root / name
        if path.is_symlink() or not path.is_dir():
            return []
        samples = []
        with os.scandir(path) as entries:
            for index, entry in enumerate(entries):
                if index >= 256:
                    break
                if entry.name.startswith('test_') and entry.name.endswith('.py') and entry.is_file(follow_symlinks=False):
                    samples.append(read(name + '/' + entry.name))
                    if len(samples) == 8:
                        break
        return samples

    try:
        if json.loads(read('.promptaid-demo.json') or '{}').get('demo')=='creator-inbox-v1':
            from backend.creator_checks import checks
            return {'suggestions':[{'id':'creator-'+check['rule'],'title':check['label'],
                    'description':'Check the extractor against frozen fictional emails.',
                    'evidence':'Protected creator-offers-v1 evaluation pack','check':check} for check in checks()],
                    'notices':['Synthetic demo: starting code is deliberately flawed. Checks do not send messages.']}
    except (ValueError,AttributeError):pass

    def suggestion(id, title, description, evidence, argv):
        return {'id': id, 'title': title, 'description': description, 'evidence': evidence,
                'check': {'kind': 'command', 'label': title, 'argv': argv,
                          'timeout_seconds': 120}}

    suggestions = []
    package_text = read('package.json')
    if package_text:
        try:
            package = json.loads(package_text)
            script = package.get('scripts', {}).get('test')
            if isinstance(script, str) and script.strip() and len(script) <= 2000 and not re.search(r'no test (specified|defined)', script, re.I):
                manager = 'pnpm' if regular_file('pnpm-lock.yaml') else 'yarn' if regular_file('yarn.lock') else 'npm'
                suggestions.append(suggestion('node-tests', 'JavaScript / TypeScript tests',
                    'Run the test script this project already defines.', 'package.json → scripts.test', [manager, 'test']))
        except (ValueError, AttributeError):
            notices.append('Could not read the test setup in package.json.')

    pyproject = read('pyproject.toml')
    try:
        config = tomllib.loads(pyproject)
    except ValueError:
        config = {}
        notices.append('Could not read the Python project settings.')
    requirements = '\n'.join(read(name) for name in ['requirements.txt', 'requirements-dev.txt', 'requirements-test.txt'])
    project = config.get('project', {})
    if isinstance(project, dict):
        dependencies = project.get('dependencies', [])
        optional = project.get('optional-dependencies', {})
        if isinstance(optional, dict):
            dependencies = [*dependencies, *[item for group in optional.values() if isinstance(group, list) for item in group]] if isinstance(dependencies, list) else []
        if isinstance(dependencies, list):
            requirements += '\n' + '\n'.join(x for x in dependencies if isinstance(x, str))
    directories = [(name, test_directory(name)) for name in ['test', 'tests']]
    samples = '\n'.join(sample for _, files in directories for sample in files)
    unittest = False
    for _, files in directories:
        for sample in files:
            try:
                imports = ast.walk(ast.parse(sample))
                unittest = unittest or any(
                    isinstance(node, ast.Import) and any(alias.name == 'unittest' for alias in node.names)
                    or isinstance(node, ast.ImportFrom) and node.module == 'unittest' for node in imports)
            except (SyntaxError, ValueError, RecursionError):
                pass
    pytest = (isinstance(config.get('tool'), dict) and 'pytest' in config['tool']) or bool(read('pytest.ini')) or bool(re.search(r'(?mi)^\s*pytest(?:\s|[<>=!~\[]|$)', requirements)) or bool(re.search(r'\[tool:pytest\]', read('setup.cfg')))
    pytest = pytest or (not unittest and bool(re.search(r'(?m)^(?:import pytest|from pytest import|def test_)', samples)))
    # An installed project environment is reused read-only by Build mode.
    interpreter = '.venv/bin/python' if (root / '.venv/bin/python').is_file() else 'python3'
    if pytest:
        suggestions.append(suggestion('python-tests', 'Python tests',
            'Run this project’s pytest suite.', 'Python test configuration', [interpreter, '-m', 'pytest']))
    else:
        for directory, files in directories:
            if files and unittest:
                suggestions.append(suggestion('python-tests', 'Python tests',
                    'Discover and run the existing Python unit tests.', directory + '/test_*.py',
                    [interpreter, '-m', 'unittest', 'discover', '-s', directory, '-p', 'test_*.py']))
                break
    if read('Package.swift') and any((root / name).is_dir() and not (root / name).is_symlink() for name in ['native/Tests', 'Tests']):
        suggestions.append(suggestion('swift-tests', 'Swift tests',
            'Build and run the existing Swift package tests.', 'Package.swift and test directory', ['swift', 'test']))

    if not suggestions:
        notices.append('No supported test setup found. Add a custom check in Advanced options, or ask your coding assistant to help set up tests.')
    return {'suggestions': suggestions, 'notices': notices}
