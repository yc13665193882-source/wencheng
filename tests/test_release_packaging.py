"""The runtime ZIP contains only reviewed payloads and verifies its file hashes."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts.build_release import REQUIRED_FILES, build_release, collect_files, production_packages

ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'test-output'
        parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='release-packaging-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for filename in REQUIRED_FILES:
            self.write(filename, b'fixture payload\n')
        self.write('package.json', b'{"version":"0.1.0-rc.1"}')
        self.write('package-lock.json', b'{"packages":{"":{}}}')
        self.write('dist/index.html', b'<script src="/assets/app.js"></script>')
        self.write('dist/assets/app.js', b'console.log("release fixture");')
        self.write('licenses/frontend/manifest.json', json.dumps(dict(
            package_lock_sha256=sha256((self.root / 'package-lock.json').read_bytes()).hexdigest(),
            packages=[])).encode())

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_whitelist_excludes_state_and_build_is_reproducible_with_verified_manifest(self):
        for name in ('.env', '.wencheng/providers.json', 'node_modules/secret.txt',
                     'acceptance/original.docx', 'test-output/private.json',
                     'dist/assets/app.js.map', 'dist/assets/private.json',
                     'skills/wencheng/wencheng-install.json', 'backend/__pycache__/app.pyc'):
            self.write(name, b'PRIVATE_PAYLOAD_MUST_NOT_BE_PACKAGED')
        first = build_release(self.root, self.root / 'first', '0.1.0-rc.1')
        second = build_release(self.root, self.root / 'second', '0.1.0-rc.1')
        self.assertEqual(first['sha256'], second['sha256'])
        with ZipFile(first['file']) as archive:
            self.assertTrue(all('PRIVATE_PAYLOAD' not in archive.read(name).decode('utf-8') for name in archive.namelist()))
            prefix = 'wencheng-0.1.0-rc.1/'
            manifest = json.loads(archive.read(prefix + 'RELEASE-MANIFEST.json'))
            self.assertEqual(set(archive.namelist()), {prefix + f['path'] for f in manifest['files']} | {prefix + 'RELEASE-MANIFEST.json'})
            for entry in manifest['files']:
                data = archive.read(prefix + entry['path'])
                self.assertEqual(entry['sha256'], sha256(data).hexdigest())
                self.assertEqual(entry['bytes'], len(data))

    def test_missing_required_payload_and_stale_html_are_errors(self):
        (self.root / 'LICENSE').unlink()
        with self.assertRaisesRegex(ValueError, 'LICENSE'):
            collect_files(self.root)
        self.write('LICENSE', b'fixture')
        self.write('dist/index.html', b'<script src="/assets/missing.js"></script>')
        with self.assertRaisesRegex(ValueError, 'missing asset'):
            collect_files(self.root)

    def test_production_closure_includes_nested_dependencies_and_peers_but_not_dev(self):
        lock = {'packages': {
            '': {'dependencies': {'app': '1'}, 'devDependencies': {'dev-only': '1'}},
            'node_modules/app': {'version': '1', 'dependencies': {'nested': '1'}, 'peerDependencies': {'peer': '1'}},
            'node_modules/app/node_modules/nested': {'version': '1', 'dependencies': {'shared': '1'}},
            'node_modules/shared': {'version': '1'},
            'node_modules/peer': {'version': '1'},
            'node_modules/dev-only': {'version': '1'},
        }}
        self.assertEqual(set(production_packages(lock)), set(lock['packages']) - {'', 'node_modules/dev-only'})

    def test_stale_license_lock_and_non_allowlisted_license_path_fail(self):
        path = self.root / 'licenses/frontend/manifest.json'
        manifest = json.loads(path.read_text())
        manifest['package_lock_sha256'] = 'not the current lock'
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'stale'):
            collect_files(self.root)
        manifest['package_lock_sha256'] = sha256((self.root / 'package-lock.json').read_bytes()).hexdigest()
        manifest['packages'] = [{'files': [{'path': '.wencheng/providers.json'}]}]
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'outside the allowlist'):
            collect_files(self.root)

    def test_version_mismatch_cannot_be_published_as_another_version(self):
        with self.assertRaisesRegex(ValueError, 'differs'):
            build_release(self.root, self.root / 'out', '9.0.0')


if __name__ == '__main__':
    unittest.main()
