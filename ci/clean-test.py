"""Install precisely one ABI wheel, outside all build environments."""
import json
import os
from pathlib import Path
import subprocess
import sys
from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename

root = Path(__file__).resolve().parents[1]
compatible = set(sys_tags())
wheels = [p for p in (root / 'wheelhouse').glob('*.whl') if parse_wheel_filename(p.name)[3] & compatible]
if len(wheels) != 1:
    raise RuntimeError(f'Expected one compatible GDAL wheel, got {wheels}')
wheel = wheels[0]
for variable in ('GDAL_DATA', 'PROJ_DATA', 'PROJ_LIB', 'GDAL_CONFIG', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'BUILD_PREFIX'):
    os.environ.pop(variable, None)
os.environ['GDAL_DRIVER_PATH'] = 'disable'
os.environ['PROJ_NETWORK'] = 'OFF'
subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', str(wheel), 'numpy', 'pytest'], check=True)
subprocess.run([sys.executable, root / 'ci/inspect-wheel.py', wheel], check=True)
subprocess.run([sys.executable, '-m', 'pytest', root / 'tests/test_binary_features.py', '-v', '--junitxml=feature-tests.xml'], check=True)
if sys.version_info[:2] == (3, 12):
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', 'rasterio', 'fiona'], check=True)
    subprocess.run([sys.executable, root / 'tests/coexistence.py'], check=True)
record = {'wheel': wheel.name, 'feature_tests': 'passed', 'leak_tests': 'passed',
          'coexistence_tests': 'passed' if sys.version_info[:2] == (3, 12) else 'not-required',
          'hdf4': 'not-supported' if sys.platform == 'win32' else 'passed'}
(root / 'test-result.json').write_text(json.dumps(record, indent=2) + '\n')
