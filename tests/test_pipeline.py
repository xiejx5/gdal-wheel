"""Fast checks for source integrity and the release gate."""

import hashlib
import io
import json
from pathlib import Path
from runpy import run_path
import sys
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ci'))

import sources

manifest = run_path(ROOT / 'ci/generate-manifest.py')['generate']
PLATFORMS = {
    'linux-x86_64': 'manylinux_2_28_x86_64',
    'macos-arm64': 'macosx_11_0_arm64',
    'windows-x86_64': 'win_amd64',
}


def make_release(tmp_path):
    version = '1.0'
    python = f'{sys.version_info.major}.{sys.version_info.minor}'
    abi = f'cp{python.replace(".", "")}'
    wheels = tmp_path / 'wheels'
    results = tmp_path / 'results'
    wheels.mkdir()
    results.mkdir()

    for platform, tag in PLATFORMS.items():
        name = f'gdal_wheel-{version}-{abi}-{abi}-{tag}.whl'
        wheel = wheels / name
        wheel.write_bytes(name.encode())

        result = results / platform
        result.mkdir()
        (result / 'test-result.json').write_text(
            json.dumps(
                {
                    'wheel': name,
                    'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    'feature_tests': 'passed',
                    'hdf4': 'not-supported' if platform == 'windows-x86_64' else 'passed',
                }
            )
        )

    return wheels, results, version, [python]


def test_source_validation(tmp_path, monkeypatch):
    destination = tmp_path / 'source.tar'
    monkeypatch.setattr(sources.urllib.request, 'urlopen', lambda *_a, **_k: io.BytesIO(b'bad'))

    with pytest.raises(ValueError, match='SHA256 mismatch'):
        sources.download({'url': 'https://example.org', 'sha256': '0' * 64}, destination)

    for version in ('1.2.3rc1', 'main', '../1.2.3'):
        with pytest.raises(ValueError, match='stable semantic'):
            sources.resolve(version)


def test_archive_traversal_is_rejected(tmp_path):
    archive = tmp_path / 'evil.tar'
    with tarfile.open(archive, 'w') as output:
        member = tarfile.TarInfo('../../escaped')
        member.size = 1
        output.addfile(member, io.BytesIO(b'x'))

    with pytest.raises(tarfile.FilterError):
        sources.extract(archive, tmp_path / 'out')


def test_release_gate(tmp_path):
    wheels, results, version, pythons = make_release(tmp_path)
    record = manifest(wheels, results, {'version': version}, pythons)
    assert record['complete']
    assert len(record['wheels']) == len(PLATFORMS)

    report = json.loads(next(results.rglob('test-result.json')).read_text())
    (wheels / report['wheel']).write_bytes(b'tampered')

    with pytest.raises(ValueError, match='Tested wheel bytes changed'):
        manifest(wheels, results, {'version': version}, pythons)
