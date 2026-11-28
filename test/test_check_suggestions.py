import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.check_suggestions import suggest_checks


class CheckSuggestionTests(unittest.TestCase):
    def test_detects_multiple_suites_without_executing_project_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text(json.dumps({'scripts': {'test': 'touch SHOULD_NOT_EXIST'}}))
            (root / 'test').mkdir()
            (root / 'test/test_example.py').write_text('import unittest\nclass Example(unittest.TestCase): pass\n')
            (root / 'Package.swift').write_text('// swift-tools-version: 5.9')
            (root / 'Tests').mkdir()
            checks = suggest_checks(root)['suggestions']
            self.assertEqual([c['id'] for c in checks], ['node-tests', 'python-tests', 'swift-tests'])
            self.assertEqual(checks[1]['check']['argv'], ['python3', '-m', 'unittest', 'discover', '-s', 'test', '-p', 'test_*.py'])
            self.assertFalse((root / 'SHOULD_NOT_EXIST').exists())
            self.assertTrue(all(c['check']['timeout_seconds'] == 120 for c in checks))

    def test_pytest_configuration_and_project_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pyproject.toml').write_text('[project.optional-dependencies]\ntest = ["pytest>=8"]\n')
            (root / '.venv/bin').mkdir(parents=True)
            (root / '.venv/bin/python').symlink_to(sys.executable)
            self.assertEqual(suggest_checks(root)['suggestions'][0]['check']['argv'], ['.venv/bin/python', '-m', 'pytest'])
            (root / 'pyproject.toml').unlink()
            (root / 'tests').mkdir()
            (root / 'tests/test_example.py').write_text('def test_example(): assert True\n')
            self.assertEqual(suggest_checks(root)['suggestions'][0]['check']['argv'][-1], 'pytest')

    def test_no_false_success_checks_for_unknown_or_placeholder_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for content in ['{}', '{broken', json.dumps({'scripts': {'test': 'echo "Error: no test specified" && exit 1'}})]:
                (root / 'package.json').write_text(content)
                result = suggest_checks(root)
                self.assertEqual(result['suggestions'], [])
                self.assertTrue(result['notices'])

    def test_symlinked_and_oversized_manifests_are_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / 'outside.json'
            outside.write_text(json.dumps({'scripts': {'test': 'never run me'}}))
            root = Path(directory) / 'project'; root.mkdir()
            (root / 'package.json').symlink_to(outside)
            (root / 'tests').symlink_to(Path(directory), target_is_directory=True)
            self.assertEqual(suggest_checks(root)['suggestions'], [])
            (root / 'package.json').unlink()
            (root / 'package.json').write_text(' ' * 64001)
            self.assertEqual(suggest_checks(root)['suggestions'], [])

    def test_lockfile_selects_package_manager_without_reading_large_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text(json.dumps({'scripts': {'test': 'vitest run'}}))
            (root / 'pnpm-lock.yaml').write_text('x' * 65000)
            self.assertEqual(suggest_checks(root)['suggestions'][0]['check']['argv'], ['pnpm', 'test'])
