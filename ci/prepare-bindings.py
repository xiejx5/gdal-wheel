"""Keep upstream SWIG bindings; add only native paths, data and notices."""
import json
import os
from pathlib import Path
import shutil
from sources import ROOT, download, extract

release = json.loads((ROOT / 'build/release.json').read_text())
source = extract(download(release['bindings'], ROOT / 'build/bindings.tar.gz'), ROOT / 'build/bindings-source')
package = ROOT / 'build/python'
if package.exists():
    shutil.rmtree(package)
shutil.copytree(source, package)
prefix = Path(os.environ['BUILD_PREFIX']).resolve()
osgeo = package / 'osgeo'
for name in ('gdal', 'proj'):
    origin = prefix / 'share' / name
    required = 'proj.db' if name == 'proj' else 'gdalvrt.xsd'
    if not (origin / required).is_file():
        raise RuntimeError(f'Missing mandatory bundled data: {origin / required}')
    shutil.copytree(origin, osgeo / 'data' / name)
if (prefix / 'share/licenses').exists():
    shutil.copytree(prefix / 'share/licenses', osgeo / 'data/licenses')
for name in ('release.json', 'dependencies.json'):
    shutil.copy2(prefix / name, osgeo / 'data' / name)
with (osgeo / '__init__.py').open('a') as stream:
    stream.write('\n\n# Unofficial wheel: bundled data defaults.\n')
    stream.write((ROOT / 'ci/bootstrap.py').read_text())
with (package / 'MANIFEST.in').open('a') as stream:
    stream.write('\nrecursive-include osgeo/data *\n')
# Explicit package_data is needed even when upstream disables include_package_data.
setup = package / 'setup.py'
text = setup.read_text()
needle = 'exclude_package_data = exclude_package_data,'
if text.count(needle) != 1:
    raise RuntimeError('Upstream setup.py changed; review data packaging patch')
text = text.replace(needle, needle + "\n    package_data={'osgeo': [str(p.relative_to('osgeo')) for p in __import__('pathlib').Path('osgeo/data').rglob('*') if p.is_file()]},")
setup.write_text(text)
with (package / 'setup.cfg').open('a') as stream:
    stream.write('\n[build_ext]\n')
    stream.write(f'include_dirs = {prefix / "include"}\nlibrary_dirs = {prefix / "lib"}\nlibraries = gdal\n')
    if os.name != 'nt':
        stream.write(f'gdal_config = {prefix / "bin/gdal-config"}\n')
print(package)
