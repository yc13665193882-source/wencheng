#!/usr/bin/env python3
"""Build the portable, prebuilt-frontend ZIP from an explicit file allowlist.

Refresh tracked frontend notices after `npm ci` with --refresh-licenses.
The build uses only the standard library; no runtime state is traversed.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    'README.md', 'README.en.md', 'requirements.txt', 'constraints.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
    'start.cmd', 'setup.cmd', 'dist/index.html',
    'backend/__init__.py', 'backend/ai.py', 'backend/app.py', 'backend/docx_engine.py',
    'backend/i18n.py', 'backend/proof.py', 'backend/rules.py', 'backend/store.py',
    'scripts/wencheng.py', 'scripts/setup.py', 'scripts/install_skill.py',
    'skills/wencheng/SKILL.md', 'skills/wencheng/agents/openai.yaml',
    'skills/wencheng/references/writing.md', 'skills/wencheng/references/installation.md',
    'skills/wencheng/scripts/wencheng.py',
)
OPTIONAL_FILES = ('docs/VALIDATION.md', 'docs/RELEASE.md', 'RELEASE.md', 'RELEASE_NOTES.md')
ASSET_SUFFIXES = {'.js', '.css', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.woff', '.woff2', '.ttf', '.otf'}


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def checked_file(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise ValueError(f'Unsafe package path: {relative}')
    source = root.joinpath(*path.parts)
    if not source.resolve().is_relative_to(root.resolve()) or source.is_symlink():
        raise ValueError(f'Package input resolves outside the project or is a symlink: {relative}')
    if not source.is_file():
        raise ValueError(f'Required package file is missing: {relative}')
    return source


def production_packages(lock: dict) -> dict:
    """Resolve the locked production dependency + peer closure, including nesting."""
    packages = lock['packages']
    selected = {}

    def resolve(owner, name):
        current = PurePosixPath(owner)
        while True:
            candidate = str(current / 'node_modules' / name)
            if candidate in packages:
                return candidate
            if str(current) == '.':
                raise ValueError(f'Locked production dependency is missing: {owner or "root"} -> {name}')
            current = current.parent

    def visit(owner, name):
        key = resolve(owner, name)
        if key in selected:
            return
        entry = packages[key]
        if entry.get('link') or not entry.get('version'):
            raise ValueError(f'Production dependency must be a locked npm package: {key}')
        selected[key] = entry
        dependencies = dict(entry.get('dependencies', {}))
        optional_peers = entry.get('peerDependenciesMeta', {})
        dependencies.update({n: v for n, v in entry.get('peerDependencies', {}).items()
                             if not optional_peers.get(n, {}).get('optional')})
        for dependency in sorted(dependencies):
            visit(key, dependency)

    for name in sorted(packages[''].get('dependencies', {})):
        visit('', name)
    return dict(sorted(selected.items()))


def refresh_licenses(root: Path):
    lock_bytes = (root / 'package-lock.json').read_bytes()
    packages = production_packages(json.loads(lock_bytes))
    records = []
    for relative, locked in packages.items():
        package_dir = root / relative
        metadata = json.loads(checked_file(root, relative + '/package.json').read_text('utf-8'))
        if metadata['version'] != locked['version']:
            raise ValueError(f'Installed version differs from lockfile: {relative}; run npm ci.')
        legal = [p for p in package_dir.iterdir() if p.is_file()
                 and re.match(r'^(?:licen[cs]e|copying|notice)(?:[.\-_]|$)', p.name, re.I)]
        # These locked packages store complete legal texts outside a root LICENSE file.
        extra_notices = {'pako': ('lib/zlib/README',), 'isarray': ('README.md',)}
        for extra in extra_notices.get(metadata['name'], ()):
            legal.append(checked_file(root, relative + '/' + extra))
        if not legal:
            raise ValueError(f'No license text found for {relative}; review it before packaging.')
        slug = metadata['name'].replace('@', '').replace('/', '__') + '-' + metadata['version']
        files = []
        for source in sorted(legal):
            original = source.relative_to(package_dir).as_posix()
            filename = original.replace('/', '__')
            destination = f'licenses/frontend/{slug}/{filename}'
            data = checked_file(root, source.relative_to(root).as_posix()).read_bytes()
            target = root / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files.append(dict(path=destination, original_path=original, bytes=len(data), sha256=digest(data)))
        records.append(dict(name=metadata['name'], version=metadata['version'],
            license=metadata.get('license', locked.get('license', 'See included license')),
            package_path=relative, resolved=locked.get('resolved'), integrity=locked.get('integrity'), files=files))
    manifest = dict(schema='wencheng.frontend-licenses.v1', package_lock_sha256=digest(lock_bytes), packages=records)
    destination = root / 'licenses/frontend/manifest.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(json_bytes(manifest))
    lines = [
        '# Third-party notices', '',
        'The prebuilt frontend includes code from the locked production dependencies below.',
        'This list conservatively includes their transitive dependencies and required peers, even when tree-shaking removes some code.',
        'License and notice texts are copied verbatim from the exact installed npm package versions; upstream terms apply.',
        'Pako also includes the full zlib notice from `lib/zlib/README`.', '',
        'isarray stores its complete MIT license in its README; that file is included verbatim.', '',
        'Reproduce from the source repository: `npm ci`, then `python scripts/build_release.py --refresh-licenses`.',
        'The machine-readable file `licenses/frontend/manifest.json` records package versions, npm integrity, source paths, and text SHA256 hashes.', '',
        '| Package | Version | Declared license | Full text |', '| --- | --- | --- | --- |',
    ]
    for record in records:
        links = ', '.join(f'[{PurePosixPath(f["path"]).name}]({f["path"]})' for f in record['files'])
        label = str(record['license']).replace('|', '\\|')
        lines.append(f'| {record["name"]} | {record["version"]} | {label} | {links} |')
    lines.extend(['', 'Python and its dependencies are installed separately by pip and are not vendored in the ZIP.',
                  'Their distributions retain their own licenses. The Python requirements are listed in `requirements.txt`.', ''])
    (root / 'THIRD_PARTY_NOTICES.md').write_text('\n'.join(lines), encoding='utf-8')
    return manifest


def collect_files(root: Path) -> dict[str, bytes]:
    result = {name: checked_file(root, name).read_bytes() for name in REQUIRED_FILES}
    for name in OPTIONAL_FILES:
        if (root / name).exists():
            result[name] = checked_file(root, name).read_bytes()
    assets = root / 'dist/assets'
    for file in sorted(assets.rglob('*')):
        if file.is_file() and file.suffix.lower() in ASSET_SUFFIXES:
            relative = file.relative_to(root).as_posix()
            result[relative] = checked_file(root, relative).read_bytes()
    if not any(p.startswith('dist/assets/') and p.endswith('.js') for p in result):
        raise ValueError('No prebuilt JavaScript assets found; run npm ci and npm run build.')
    manifest_path = 'licenses/frontend/manifest.json'
    manifest_bytes = checked_file(root, manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest['package_lock_sha256'] != digest((root / 'package-lock.json').read_bytes()):
        raise ValueError('Frontend license manifest is stale; rerun --refresh-licenses after npm ci.')
    result[manifest_path] = manifest_bytes
    for package in manifest['packages']:
        for entry in package['files']:
            name = entry['path']
            if not name.startswith('licenses/frontend/'):
                raise ValueError(f'License path outside the allowlist: {name}')
            data = checked_file(root, name).read_bytes()
            if digest(data) != entry['sha256'] or len(data) != entry['bytes']:
                raise ValueError(f'License text differs from recorded source: {name}')
            result[name] = data
    # Resolve every local HTML asset reference, so an old index cannot silently ship missing chunks.
    html = result['dist/index.html'].decode('utf-8')
    for reference in re.findall(r'(?:src|href)=["\'](/assets/[^"\']+)["\']', html):
        if 'dist' + reference not in result:
            raise ValueError(f'HTML references a missing asset: {reference}')
    return result


def build_release(root: Path, output: Path, version: str) -> dict:
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?', version):
        raise ValueError('Use a release version such as 0.1.0-rc.1.')
    package = json.loads((root / 'package.json').read_text('utf-8'))
    if package['version'] != version:
        raise ValueError(f'Package version {package["version"]} differs from requested release {version}.')
    files = collect_files(root)
    files['VERSION'] = (version + '\n').encode('ascii')
    manifest = dict(schema='wencheng.release.v1', version=version, python_requires='>=3.11',
        frontend_prebuilt=True, node_required_for_runtime=False,
        checksum_scope='Every payload file except this manifest; the ZIP SHA256 is in the adjacent .sha256 file.',
        files=[dict(path=path, bytes=len(data), sha256=digest(data)) for path, data in sorted(files.items())])
    files['RELEASE-MANIFEST.json'] = json_bytes(manifest)
    output.mkdir(parents=True, exist_ok=True)
    name = f'wencheng-{version}'
    destination = output / f'{name}.zip'
    temporary = destination.with_suffix('.zip.tmp')
    with ZipFile(temporary, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, data in sorted(files.items()):
            info = ZipInfo(f'{name}/{relative}', date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
    temporary.replace(destination)
    checksum = digest(destination.read_bytes())
    destination.with_suffix('.zip.sha256').write_text(f'{checksum}  {destination.name}\n', encoding='ascii')
    return dict(file=str(destination.resolve()), version=version, files=len(files),
                bytes=destination.stat().st_size, sha256=checksum)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-licenses', action='store_true', help='Copy locked npm license/notice texts, then stop.')
    parser.add_argument('--version', help='Must match package.json; defaults to its version.')
    parser.add_argument('--output', type=Path, default=ROOT / 'release')
    args = parser.parse_args()
    if args.refresh_licenses:
        result = refresh_licenses(ROOT)
        print(json.dumps(dict(packages=len(result['packages']), manifest='licenses/frontend/manifest.json')))
        return
    version = args.version or json.loads((ROOT / 'package.json').read_text('utf-8'))['version']
    print(json.dumps(build_release(ROOT, args.output.resolve(), version), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(f'Release build failed: {error}', file=sys.stderr)
        raise SystemExit(1)
