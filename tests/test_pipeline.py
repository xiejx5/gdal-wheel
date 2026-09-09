"""Fast integrity and release-gate tests; no native SDK required."""

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


def python_abis():
    """Three synthetic normal ABIs and all their free-threaded variants."""
    major, minor = sys.version_info[:2]
    normal = tuple(f'cp{major}{value}' for value in range(minor - 2, minor + 1))
    return normal + tuple(f'{python}t' for python in normal)


def wheel_tags(python):
    return (python[:-1], python) if python.endswith('t') else (python, python)


def test_digest_mismatch_never_replaces_archive(tmp_path):
    destination = tmp_path / 'source.tar'
    with patch('urllib.request.urlopen', return_value=io.BytesIO(b'wrong')):
        with pytest.raises(ValueError, match='SHA256 mismatch'):
            sources.download(
                {
                    'url': 'https://example.org/source',
                    'sha256': '0' * 64,
                },
                destination,
            )

    assert not destination.exists()
    assert not destination.with_suffix('.partial').exists()


def test_verified_cache_avoids_network(tmp_path):
    destination = tmp_path / 'source.tar'
    destination.write_bytes(b'good')

    with patch(
        'urllib.request.urlopen',
        side_effect=AssertionError('network'),
    ):
        sources.download(
            {
                'url': 'https://example.org/source',
                'sha256': hashlib.sha256(b'good').hexdigest(),
            },
            destination,
        )


def test_archive_traversal_rejected(tmp_path):
    archive = tmp_path / 'evil.tar'

    with tarfile.open(archive, 'w') as output:
        member = tarfile.TarInfo('../../escaped')
        member.size = 1
        output.addfile(member, io.BytesIO(b'x'))

    with pytest.raises(tarfile.FilterError):
        sources.extract(archive, tmp_path / 'out')

    assert not (tmp_path / 'escaped').exists()


@pytest.mark.parametrize(
    'version',
    ['3.14.0rc1', 'main', '../3.13.3', '3.13.3;echo no'],
)
def test_version_rejects_nonstable_input(version):
    with pytest.raises(ValueError, match='stable semantic'):
        sources.resolve(version)


def make_release(tmp_path):
    wheels = tmp_path / 'wheels'
    results = tmp_path / 'results'

    wheels.mkdir()
    results.mkdir()
    platforms = [
        ('linux-x86_64', 'manylinux_2_28_x86_64'),
        ('macos-arm64', 'macosx_11_0_arm64'),
        ('windows-x86_64', 'win_amd64'),
    ]

    for python in python_abis():
        interpreter, abi = wheel_tags(python)

        for platform, tag in platforms:
            name = f'gdal_wheel-3.13.3-{interpreter}-{abi}-{tag}.whl'
            wheel = wheels / name
            wheel.write_bytes(name.encode())

            result = results / f'{python}-{platform}'
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


def test_complete_release_has_integrity_links(tmp_path):
    wheels, results = make_release(tmp_path)

    record = manifest.generate(
        wheels,
        results,
        {'version': '3.13.3'},
        'owner/repo',
    )

    expected = len(python_abis()) * 3
    assert record['complete']
    assert len(record['wheels']) == expected
    assert (
        len([python for python in record['python_versions'] if python.endswith('t')])
        == 3
    )
    assert (wheels / 'index.html').read_text().count('#sha256=') == expected
    assert not list(wheels.glob('*.sha256'))


def test_partial_threaded_matrix_is_valid(tmp_path):
    wheels, results = make_release(tmp_path)
    threaded = [python for python in python_abis() if python.endswith('t')]
    for python in threaded[:2]:
        interpreter, abi = wheel_tags(python)
        for wheel in list(wheels.glob(f'gdal_wheel-*-{interpreter}-{abi}-*.whl')):
            name = wheel.name
            wheel.unlink()
            for report in list(results.rglob('test-result.json')):
                if json.loads(report.read_text()).get('wheel') == name:
                    report.unlink()
    record = manifest.generate(
        wheels,
        results,
        {'version': '3.13.3'},
        'owner/repo',
    )

    assert record['complete']
    assert len([p for p in record['python_versions'] if p.endswith('t')]) == 1


@pytest.mark.parametrize(
    'fault',
    [
        'missing-wheel',
        'missing-test',
        'failed-test',
        'hdf4',
        'tampered-wheel',
    ],
)
def test_incomplete_release_rejected(tmp_path, fault):
    wheels, results = make_release(tmp_path)
    report_path = next(results.rglob('test-result.json'))
    report = json.loads(report_path.read_text())
    if fault == 'missing-wheel':
        (wheels / report['wheel']).unlink()
    elif fault == 'tampered-wheel':
        (wheels / report['wheel']).write_bytes(b'tampered')
    elif fault == 'missing-test':
        report_path.unlink()
    else:
        field = {
            'failed-test': 'feature_tests',
            'hdf4': 'hdf4',
        }[fault]

        report[field] = 'failed'
        report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        manifest.generate(
            wheels,
            results,
            {'version': '3.13.3'},
            'owner/repo',
        )

    assert not (wheels / 'manifest.json').exists()


def test_bootstrap_preserves_application_setting(tmp_path):
    class Gdal:
        settings = {'GDAL_DATA': 'application'}

        def GetConfigOption(self, name):
            return self.settings.get(name)

        def SetConfigOption(self, name, value):
            self.settings[name] = value

    (tmp_path / 'data/gdal').mkdir(parents=True)
    (tmp_path / 'data/proj').mkdir()

    gdal = Gdal()

    with patch.dict(
        'os.environ',
        {'PROJ_LIB': 'legacy-user-proj'},
        clear=True,
    ):
        exec(
            (ROOT / 'ci/bootstrap.py').read_text(),
            {
                '__file__': str(tmp_path / '__init__.py'),
                '_gdal': gdal,
            },
        )
        import os

        assert gdal.settings['GDAL_DATA'] == 'application'
        assert 'PROJ_DATA' not in os.environ
