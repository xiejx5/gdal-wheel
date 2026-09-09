"""Fast checks for source verification and the release gate."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ci'))

import sources

spec = importlib.util.spec_from_file_location(
    'manifest', ROOT / 'ci/generate-manifest.py'
)
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)

PLATFORMS = (
    ('linux-x86_64', 'manylinux_2_28_x86_64'),
    ('macos-arm64', 'macosx_11_0_arm64'),
    ('windows-x86_64', 'win_amd64'),
)
GDAL_VERSION = '9.9.9'


def python_versions():
    major, minor = sys.version_info[:2]
    normal = [f'{major}.{value}' for value in range(minor - 2, minor + 1)]
    return normal + [f'{normal[-1]}t']


def wheel_tags(version):
    threaded = version.endswith('t')
    digits = version.removesuffix('t').replace('.', '')
    interpreter = f'cp{digits}'
    return interpreter, interpreter + ('t' if threaded else '')


def make_release(tmp_path):
    wheels = tmp_path / 'wheels'
    results = tmp_path / 'results'
    wheels.mkdir()
    results.mkdir()

    for version in python_versions():
        interpreter, abi = wheel_tags(version)
        for platform, tag in PLATFORMS:
            name = f'gdal_wheel-{GDAL_VERSION}-{interpreter}-{abi}-{tag}.whl'
            wheel = wheels / name
            wheel.write_bytes(name.encode())

            result = results / f'{abi}-{platform}'
            result.mkdir()
            (result / 'test-result.json').write_text(
                json.dumps(
                    {
                        'wheel': name,
                        'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                        'feature_tests': 'passed',
                        'hdf4': (
                            'not-supported'
                            if platform == 'windows-x86_64'
                            else 'passed'
                        ),
                    }
                )
            )

    return wheels, results


def test_download_rejects_bad_hash(tmp_path):
    destination = tmp_path / 'source.tar'
    with patch('urllib.request.urlopen', return_value=io.BytesIO(b'wrong')):
        with pytest.raises(ValueError, match='SHA256 mismatch'):
            sources.download(
                {'url': 'https://example.org/source', 'sha256': '0' * 64},
                destination,
            )
    assert not destination.exists()


def test_archive_traversal_is_rejected(tmp_path):
    archive = tmp_path / 'evil.tar'
    with tarfile.open(archive, 'w') as output:
        member = tarfile.TarInfo('../../escaped')
        member.size = 1
        output.addfile(member, io.BytesIO(b'x'))

    with pytest.raises(tarfile.FilterError):
        sources.extract(archive, tmp_path / 'out')
    assert not (tmp_path / 'escaped').exists()


@pytest.mark.parametrize('version', ['1.2.3rc1', 'main', '../1.2.3'])
def test_version_requires_stable_semver(version):
    with pytest.raises(ValueError, match='stable semantic'):
        sources.resolve(version)


def test_complete_release_passes(tmp_path):
    wheels, results = make_release(tmp_path)
    record = manifest.generate(
        wheels,
        results,
        {'version': GDAL_VERSION},
        python_versions(),
    )

    assert record['complete']
    assert len(record['wheels']) == len(python_versions()) * len(PLATFORMS)


def test_tampered_wheel_is_rejected(tmp_path):
    wheels, results = make_release(tmp_path)
    report = json.loads(next(results.rglob('test-result.json')).read_text())
    (wheels / report['wheel']).write_bytes(b'tampered')

    with pytest.raises(ValueError, match='Tested wheel bytes changed'):
        manifest.generate(
            wheels,
            results,
            {'version': GDAL_VERSION},
            python_versions(),
        )


def test_bootstrap_preserves_application_data_path(tmp_path, monkeypatch):
    class Gdal:
        settings = {'GDAL_DATA': 'application'}

        def GetConfigOption(self, name):
            return self.settings.get(name)

        def SetConfigOption(self, name, value):
            self.settings[name] = value

        def PushFinderLocation(self, path):
            raise AssertionError(f'should not override application path with {path}')

    (tmp_path / 'data/gdal').mkdir(parents=True)
    (tmp_path / 'data/proj').mkdir()
    monkeypatch.setenv('PROJ_LIB', 'application')
    monkeypatch.delenv('PROJ_DATA', raising=False)

    gdal = Gdal()
    exec(
        (ROOT / 'ci/bootstrap.py').read_text(),
        {'__file__': str(tmp_path / '__init__.py'), '_gdal': gdal},
    )
    assert gdal.settings['GDAL_DATA'] == 'application'
