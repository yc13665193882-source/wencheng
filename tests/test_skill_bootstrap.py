"""A skills CLI copy can install and bind its separately shipped application."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


class SkillBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.output = (ROOT / 'test-output').resolve()
        self.output.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='skill-bootstrap-', dir=self.output)
        self.base = Path(self.temp.name)
        self.addCleanup(self.cleanup)
        self.skill = self.base / 'Agent project' / 'skills' / 'wencheng'
        shutil.copytree(ROOT / 'skills/wencheng', self.skill,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'wencheng-install.json'))
        script = self.skill / 'scripts/wencheng.py'
        spec = importlib.util.spec_from_file_location('wencheng_bootstrap_under_test', script)
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)
        self.application = self.base / '应用 空格' / 'app'
        self.config = self.skill / 'wencheng-install.json'

    def cleanup(self):
        if self.base.resolve().parent != self.output or not self.base.name.startswith('skill-bootstrap-'):
            raise AssertionError('Refusing cleanup outside the test directory')
        self.temp.cleanup()

    def release_bytes(self, extra=None):
        data = io.BytesIO()
        folder = 'wencheng-' + self.launcher.RELEASE_VERSION
        with ZipFile(data, 'w') as package:
            payload = {
                'RELEASE-MANIFEST.json': json.dumps({'schema': 'wencheng.release.v1',
                                                    'version': self.launcher.RELEASE_VERSION}),
                'backend/docx_engine.py': '# runtime marker',
                'scripts/wencheng.py': '# shared CLI',
                'scripts/setup.py': '# dependency installer',
                'dist/index.html': '<html>Prebuilt editor</html>',
            }
            for name, value in payload.items():
                package.writestr(folder + '/' + name, value)
            if extra:
                package.writestr(extra, 'unexpected')
        return data.getvalue()

    def install(self, *, setup_failure=None):
        data = self.release_bytes()
        run = Mock(side_effect=setup_failure)
        with patch.object(self.launcher, 'RELEASE_SHA256', sha256(data).hexdigest()), \
                patch.object(self.launcher.urllib.request, 'urlopen', return_value=io.BytesIO(data)) as request, \
                patch.object(self.launcher.subprocess, 'run', run):
            result = self.launcher.setup(['--app-dir', str(self.application)])
        return result, request, run

    def test_fresh_copy_downloads_verified_release_and_binds_exact_path(self):
        result, request, run = self.install()
        self.assertTrue(result['setup_complete'])
        self.assertTrue(result['downloaded'])
        self.assertEqual(result['application_root'], str(self.application))
        self.assertEqual(json.loads(self.config.read_text('utf-8'))['application_root'], str(self.application))
        self.assertEqual((self.application / 'dist/index.html').read_text(), '<html>Prebuilt editor</html>')
        self.assertEqual(request.call_count, 1)
        run.assert_called_once_with([sys.executable, str(self.application / 'scripts/setup.py')],
                                    cwd=self.application, stdout=sys.stderr, check=True)
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(self.launcher.application_root(), self.application)

    def test_bad_checksum_never_extracts_or_runs_setup(self):
        with patch.object(self.launcher.urllib.request, 'urlopen', return_value=io.BytesIO(b'not the release')), \
                patch.object(self.launcher.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                self.launcher.setup(['--app-dir', str(self.application)])
        run.assert_not_called()
        self.assertFalse(self.application.exists())
        self.assertFalse(self.config.exists())

    def test_failed_dependencies_can_retry_without_download_or_premature_binding(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.install(setup_failure=subprocess.CalledProcessError(1, 'setup'))
        self.assertFalse(self.config.exists())
        with patch.object(self.launcher, 'download_release') as download, \
                patch.object(self.launcher.subprocess, 'run'):
            result = self.launcher.setup(['--app-dir', str(self.application)])
        download.assert_not_called()
        self.assertFalse(result['downloaded'])
        self.assertTrue(self.config.is_file())

    def test_unrelated_nonempty_directory_is_preserved(self):
        self.application.mkdir(parents=True)
        note = self.application / 'notes.txt'
        note.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'not empty'):
            self.launcher.setup(['--app-dir', str(self.application)])
        self.assertEqual(note.read_text(), 'keep')
        self.assertFalse(self.config.exists())

    def test_binding_existing_app_does_not_download_or_install(self):
        self.install()
        with patch.object(self.launcher, 'download_release') as download, \
                patch.object(self.launcher.subprocess, 'run') as run:
            result = self.launcher.setup(['--bind', str(self.application)])
        download.assert_not_called()
        run.assert_not_called()
        self.assertTrue(result['bound_existing'])
        self.assertEqual(json.loads(self.config.read_text('utf-8'))['application_root'], str(self.application))

    def test_copied_skill_finds_default_runtime_without_old_machine_binding(self):
        self.install()
        self.config.unlink()
        with patch.dict('os.environ', {}, clear=True), \
                patch.object(self.launcher, 'default_application_root', return_value=self.application), \
                patch.object(Path, 'cwd', return_value=Path(self.base.anchor) / 'wencheng-test-unrelated-cwd'):
            self.assertEqual(self.launcher.application_root(), self.application)
            manifest = self.application / 'RELEASE-MANIFEST.json'
            manifest.write_text(json.dumps({'schema': 'other-app', 'version': self.launcher.RELEASE_VERSION}))
            with self.assertRaisesRegex(FileNotFoundError, 'application not found'):
                self.launcher.application_root()

    def test_stale_binding_does_not_fall_through_to_default_runtime(self):
        self.install()
        self.config.write_text(json.dumps({'application_root': str(self.base / 'missing')}))
        with patch.dict('os.environ', {}, clear=True), \
                patch.object(self.launcher, 'default_application_root', return_value=self.application):
            with self.assertRaisesRegex(FileNotFoundError, 'application not found'):
                self.launcher.application_root()

    def test_setup_keeps_runtime_outside_installed_skill(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.launcher.setup(['--app-dir', str(self.skill / 'runtime')])
        self.assertFalse((self.skill / 'runtime').exists())

    def test_archive_cannot_extract_outside_release_folder(self):
        archive = self.base / 'bad.zip'
        archive.write_bytes(self.release_bytes('../escaped.txt'))
        with self.assertRaisesRegex(ValueError, 'archive path'):
            self.launcher.unpack_release(archive, self.base / 'unpacked')
        self.assertFalse((self.base / 'escaped.txt').exists())


if __name__ == '__main__':
    unittest.main()
