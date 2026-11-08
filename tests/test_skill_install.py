"""Portable skill installation preserves explicit targets and application bindings."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.install_skill import CONFIG_NAME, install_skill


class SkillInstallationTests(unittest.TestCase):
    def setUp(self):
        self.output = (ROOT / 'test-output').resolve()
        self.output.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='wencheng-install-', dir=self.output)
        self.base = Path(self.temp.name)
        self.addCleanup(self.cleanup)
        self.app = self.make_app(self.base / 'Application 空格')
        self.target = self.base / 'Other project' / '.agents' / 'skills' / 'wencheng'
        self.cwd = self.base / 'Unrelated directory'
        self.cwd.mkdir()

    def cleanup(self):
        if self.base.resolve().parent != self.output or not self.base.name.startswith('wencheng-install-'):
            raise AssertionError('Refusing cleanup outside the test directory')
        self.temp.cleanup()

    def make_app(self, root):
        shutil.copytree(ROOT / 'skills' / 'wencheng', root / 'skills' / 'wencheng',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', CONFIG_NAME))
        (root / 'backend').mkdir()
        (root / 'backend' / 'docx_engine.py').write_text('# Application marker\n', encoding='utf-8')
        (root / 'scripts').mkdir()
        (root / 'scripts' / 'wencheng.py').write_text(
            'import json, sys\nfrom pathlib import Path\n'
            'print(json.dumps({"root":str(Path(__file__).resolve().parents[1]), "args":sys.argv[1:]}))\n',
            encoding='utf-8')
        return root

    def launch(self, *args, root=None):
        env = dict(os.environ)
        env.pop('WENCHENG_ROOT', None)
        if root is not None:
            env['WENCHENG_ROOT'] = str(root)
        return subprocess.run([sys.executable, str(self.target / 'scripts' / 'wencheng.py'), *args],
                              cwd=self.cwd, env=env, capture_output=True, text=True, encoding='utf-8')

    def test_copy_works_outside_application_and_preserves_argument_boundaries(self):
        install_skill(self.target, application_root=self.app)
        result = self.launch('append', 'project-id', '--text', '中文 "quoted" $value; `literal`')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            'root': str(self.app),
            'args': ['append', 'project-id', '--text', '中文 "quoted" $value; `literal`'],
        })
        self.assertTrue((self.target / 'references' / 'installation.md').is_file())
        self.assertEqual(json.loads((self.target / CONFIG_NAME).read_text(encoding='utf-8'))['application_root'], str(self.app))

    def test_existing_directory_is_not_overwritten_without_update(self):
        install_skill(self.target, application_root=self.app)
        skill = self.target / 'SKILL.md'
        skill.write_text('personal edit', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'not empty'):
            install_skill(self.target, application_root=self.app)
        self.assertEqual(skill.read_text(encoding='utf-8'), 'personal edit')

    def test_update_rebinds_application_and_keeps_extra_files(self):
        install_skill(self.target, application_root=self.app)
        note = self.target / 'personal-notes.txt'
        note.write_text('keep', encoding='utf-8')
        (self.target / 'SKILL.md').write_text('old skill', encoding='utf-8')
        moved = self.make_app(self.base / 'Relocated application')
        install_skill(self.target, update=True, application_root=moved)
        self.assertEqual(json.loads(self.launch('projects').stdout)['root'], str(moved))
        self.assertEqual(note.read_text(encoding='utf-8'), 'keep')
        self.assertEqual((self.target / 'SKILL.md').read_bytes(), (moved / 'skills' / 'wencheng' / 'SKILL.md').read_bytes())

    def test_update_does_not_overwrite_an_unrecognized_directory(self):
        self.target.mkdir(parents=True)
        note = self.target / 'SKILL.md'
        note.write_text('another skill', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unrecognized'):
            install_skill(self.target, update=True, application_root=self.app)
        self.assertEqual(list(self.target.iterdir()), [note])
        self.assertEqual(note.read_text(encoding='utf-8'), 'another skill')

    def test_explicit_environment_root_overrides_installation(self):
        install_skill(self.target, application_root=self.app)
        alternate = self.make_app(self.base / 'Alternate application')
        self.assertEqual(json.loads(self.launch('projects', root=alternate).stdout)['root'], str(alternate))
        missing = self.launch('projects', root=self.base / 'missing')
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('WENCHENG_ROOT', missing.stderr)

    def test_stale_binding_does_not_dispatch_to_a_different_workspace(self):
        install_skill(self.target, application_root=self.app)
        config = self.target / CONFIG_NAME
        config.write_text(json.dumps({'application_root': str(self.base / 'missing')}), encoding='utf-8')
        result = self.launch('projects')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('application not found', result.stderr)

    def test_source_and_ancestor_targets_are_rejected(self):
        source = self.app / 'skills' / 'wencheng'
        for target in (source, source / 'nested', source.parent, self.app):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'outside'):
                install_skill(target, application_root=self.app)

    def test_installer_cli_requires_explicit_destination(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'install_skill.py')],
                                cwd=self.cwd, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--target', result.stderr)

    def test_launcher_uses_application_virtual_environment(self):
        install_skill(self.target, application_root=self.app)
        path = self.target / 'scripts' / 'wencheng.py'
        spec = importlib.util.spec_from_file_location('wencheng_installed_launcher', path)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        executable = self.app / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        executable.parent.mkdir(parents=True)
        executable.touch()
        with patch.object(launcher, 'application_root', return_value=self.app), \
                patch.object(sys, 'argv', [str(path), 'append', 'id', '--text', 'quoted "text"']), \
                patch.object(launcher.subprocess, 'run', return_value=Mock(returncode=7)) as run:
            with self.assertRaises(SystemExit) as result:
                launcher.main()
        self.assertEqual(result.exception.code, 7)
        run.assert_called_once_with([str(executable), str(self.app / 'scripts' / 'wencheng.py'),
                                     'append', 'id', '--text', 'quoted "text"'], check=False)

    def test_same_resolved_executable_still_enters_application_virtual_environment(self):
        install_skill(self.target, application_root=self.app)
        path = self.target / 'scripts' / 'wencheng.py'
        spec = importlib.util.spec_from_file_location('wencheng_symlink_launcher', path)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        executable = self.app / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        executable.parent.mkdir(parents=True)
        executable.touch()
        # POSIX venv executables can point to the same binary as the system Python.
        # Emulate that path identity on Windows too, without requiring symlink privileges.
        resolve = Path.resolve
        system_binary = Path(sys.executable).resolve()
        def resolved(value, *args, **kwargs):
            return system_binary if value == executable else resolve(value, *args, **kwargs)
        with patch.object(Path, 'resolve', resolved), \
                patch.object(launcher, 'application_root', return_value=self.app), \
                patch.object(sys, 'prefix', str(self.base / 'system-python')), \
                patch.object(sys, 'argv', [str(path), 'projects']), \
                patch.object(launcher.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            self.assertEqual(executable.resolve(), Path(sys.executable).resolve())
            with self.assertRaises(SystemExit):
                launcher.main()
        run.assert_called_once_with([str(executable), str(self.app / 'scripts' / 'wencheng.py'), 'projects'], check=False)

    def test_current_application_virtual_environment_does_not_spawn_again(self):
        install_skill(self.target, application_root=self.app)
        path = self.target / 'scripts' / 'wencheng.py'
        spec = importlib.util.spec_from_file_location('wencheng_active_venv_launcher', path)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        executable = self.app / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        executable.parent.mkdir(parents=True)
        executable.touch()
        with patch.object(launcher, 'application_root', return_value=self.app), \
                patch.object(sys, 'prefix', str(self.app / '.venv')), \
                patch.object(sys, 'argv', [str(path), 'projects']), \
                patch.object(launcher.subprocess, 'run') as run, \
                patch.object(launcher.runpy, 'run_path') as dispatch:
            launcher.main()
        run.assert_not_called()
        dispatch.assert_called_once_with(str(self.app / 'scripts' / 'wencheng.py'), run_name='__main__')


if __name__ == '__main__':
    unittest.main()
