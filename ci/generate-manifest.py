"""Validate the complete tested wheel matrix."""

import os
import argparse
import hashlib
import json
from pathlib import Path

from packaging.utils import parse_wheel_filename


PLATFORMS = {'linux-x86_64', 'windows-x86_64', 'macos-arm64'}


def platform_name(tags):
    names = {tag.platform for tag in tags}
    if 'win_amd64' in names:
        return 'windows-x86_64'
    if all(name.startswith('macosx_') and name.endswith('_arm64') for name in names):
        return 'macos-arm64'
    if 'manylinux_2_28_x86_64' in names:
        return 'linux-x86_64'
    raise ValueError(f'Unexpected wheel platform: {names}')


def abi_tag(version):
    threaded = version.endswith('t')
    digits = version.removesuffix('t').replace('.', '')
    return f'cp{digits}' + ('t' if threaded else '')


def python_key(tag):
    return int(tag[2:].removesuffix('t')), tag.endswith('t')


def generate(directory, results, release, python_versions):
    reports = [
        json.loads(path.read_text()) for path in results.rglob('test-result.json')
    ]
    expected_pythons = {abi_tag(version) for version in python_versions}
    if not expected_pythons:
        raise ValueError('No Python versions selected')

    rows = []
    seen = set()

    for path in sorted(directory.glob('*.whl')):
        name, version, build, tags = parse_wheel_filename(path.name)
        if name != 'gdal-wheel' or str(version) != release['version'] or build:
            raise ValueError(f'Unexpected wheel: {path.name}')

        interpreters = {tag.interpreter for tag in tags}
        abis = {tag.abi for tag in tags}
        if len(interpreters) != 1 or len(abis) != 1:
            raise ValueError(f'Unexpected wheel ABI: {path.name}')

        interpreter = interpreters.pop()
        python = abis.pop()
        expected_interpreter = python[:-1] if python.endswith('t') else python
        if (
            not python.startswith('cp')
            or not python[2:].removesuffix('t').isdigit()
            or interpreter != expected_interpreter
        ):
            raise ValueError(f'Unsupported Python ABI: {path.name}')

        platform = platform_name(tags)
        key = (python, platform)
        if key in seen:
            raise ValueError(f'Duplicate Python/platform wheel: {key}')
        seen.add(key)

        matching = [report for report in reports if report.get('wheel') == path.name]
        if len(matching) != 1:
            raise ValueError(f'Missing clean-test result: {path.name}')
        report = matching[0]

        if report.get('feature_tests') != 'passed':
            raise ValueError(f'Feature tests failed: {path.name}')
        expected_hdf4 = 'not-supported' if platform == 'windows-x86_64' else 'passed'
        if report.get('hdf4') != expected_hdf4:
            raise ValueError(f'HDF4 contract mismatch: {path.name}')

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if report.get('sha256') != digest:
            raise ValueError(f'Tested wheel bytes changed: {path.name}')

        rows.append(
            {
                'filename': path.name,
                'sha256': digest,
                'python': python,
                'platform': platform,
                'tags': sorted(str(tag) for tag in tags),
                'feature_tests': 'passed',
                'hdf4': report['hdf4'],
            }
        )

    pythons = sorted({python for python, _ in seen}, key=python_key)
    if set(pythons) != expected_pythons:
        raise ValueError(f'Expected Python ABIs {expected_pythons}, got {set(pythons)}')

    expected = {
        (python, platform) for python in expected_pythons for platform in PLATFORMS
    }
    if seen != expected:
        raise ValueError(f'Incomplete release: expected {expected}, got {seen}')

    record = {
        'schema_version': 1,
        'complete': True,
        'version': release['version'],
        'python_versions': pythons,
        'upstream': release,
        'platforms': {platform: 'passed' for platform in sorted(PLATFORMS)},
        'wheels': rows,
    }
    (directory / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--wheels', type=Path, default=Path('wheelhouse'))
    parser.add_argument('--results', type=Path, default=Path('results'))
    parser.add_argument('--release', type=Path, default=Path('build/release.json'))
    args = parser.parse_args()
    generate(
        args.wheels,
        args.results,
        json.loads(args.release.read_text()),
        json.loads(os.environ['PYTHON_VERSIONS']),
    )
