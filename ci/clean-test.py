"""Test every wheel for this platform in an isolated uv environment."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE = ROOT / 'wheelhouse'
RESULTS = ROOT / 'results'
REQUIRED_FILES = {
    'osgeo/data/gdal/gdalvrt.xsd',
    'osgeo/data/proj/proj.db',
}


def run(*args: object) -> None:
    print('+', *map(str, args), flush=True)
    subprocess.run([str(arg) for arg in args], check=True)


def wheel_tags(version: str) -> tuple[str, str]:
    threaded = version.endswith('t')
    digits = version.removesuffix('t').replace('.', '')
    interpreter = f'cp{digits}'
    abi = interpreter + ('t' if threaded else '')
    return interpreter, abi


def wheel_for(version: str) -> Path:
    interpreter, abi = wheel_tags(version)
    wheels = list(WHEELHOUSE.glob(f'gdal_wheel-*-{interpreter}-{abi}-*.whl'))
    if len(wheels) != 1:
        raise RuntimeError(f'Expected one {abi} wheel, found: {wheels}')
    return wheels[0]


def inspect_wheel(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    missing = sorted(REQUIRED_FILES - names)
    if missing:
        raise RuntimeError(f'Missing packaged data: {missing}')
    if not any(name.startswith('osgeo/_gdal') for name in names):
        raise RuntimeError('Missing osgeo._gdal extension')


def clean_environment() -> None:
    for name in (
        'GDAL_DATA',
        'PROJ_DATA',
        'PROJ_LIB',
        'GDAL_CONFIG',
        'GDAL_DRIVER_PATH',
        'LD_LIBRARY_PATH',
        'DYLD_LIBRARY_PATH',
        'BUILD_PREFIX',
    ):
        os.environ.pop(name, None)
    os.environ['PROJ_NETWORK'] = 'OFF'


def test_one(wheel: Path, result_dir: Path) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    report = {
        'wheel': wheel.name,
        'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
        'feature_tests': 'failed',
        'hdf4': 'not-supported' if sys.platform == 'win32' else 'failed',
    }
    try:
        clean_environment()
        inspect_wheel(wheel)
        run(
            sys.executable,
            '-m',
            'pytest',
            ROOT / 'tests/test_binary_features.py',
            '-q',
            f'--junitxml={result_dir / "feature-tests.xml"}',
        )
        report['feature_tests'] = 'passed'
        if sys.platform != 'win32':
            report['hdf4'] = 'passed'
    finally:
        (result_dir / 'test-result.json').write_text(
            json.dumps(report, indent=2) + '\n'
        )


def main() -> None:
    if '--ready' in sys.argv:
        test_one(Path(sys.argv[2]), Path(sys.argv[3]))
        return

    for version in json.loads(os.environ['PYTHON_VERSIONS']):
        wheel = wheel_for(version)
        _, abi = wheel_tags(version)
        run('uv', 'python', 'install', version)
        run(
            'uv',
            'run',
            '--isolated',
            '--no-project',
            '--python',
            version,
            '--with',
            str(wheel),
            '--with',
            'numpy',
            '--with',
            'pytest',
            '--',
            'python',
            __file__,
            '--ready',
            wheel,
            RESULTS / abi,
        )


if __name__ == '__main__':
    main()
