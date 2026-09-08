"""One controlled shared SDK per platform, reused by all CPython ABIs."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from sources import ROOT, download, extract

PREFIX = Path(os.environ['BUILD_PREFIX']).resolve()
WORK = ROOT / 'build' / 'native'
LOCK = json.loads((ROOT / 'ci/dependencies.json').read_text())
WINDOWS = os.name == 'nt'
MAC = platform.system() == 'Darwin'
JOBS = str(min(os.cpu_count() or 2, 8))

def run(*args, cwd=None):
    print('+', *map(str, args), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)

def cmake(source, name, options):
    binary = WORK / (name + '-build')
    common = [f'-DCMAKE_INSTALL_PREFIX={PREFIX}', f'-DCMAKE_PREFIX_PATH={PREFIX}',
              '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_INSTALL_LIBDIR=lib',
              '-DBUILD_SHARED_LIBS=ON', '-DBUILD_TESTING=OFF',
              '-DCMAKE_POSITION_INDEPENDENT_CODE=ON', '-DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF',
              '-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF', '-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF']
    if MAC:
        common += ['-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0', '-DCMAKE_OSX_ARCHITECTURES=arm64',
                   '-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew;/usr/local',
                   f'-DCMAKE_INSTALL_NAME_DIR={PREFIX}/lib']
    if shutil.which('ccache') and not WINDOWS:
        common += ['-DCMAKE_C_COMPILER_LAUNCHER=ccache', '-DCMAKE_CXX_COMPILER_LAUNCHER=ccache']
    if WINDOWS:
        vcpkg = Path(os.environ['VCPKG_INSTALLATION_ROOT'])
        common += [f'-DCMAKE_TOOLCHAIN_FILE={vcpkg}/scripts/buildsystems/vcpkg.cmake',
                   '-DVCPKG_TARGET_TRIPLET=x64-windows', '-DVCPKG_MANIFEST_MODE=OFF',
                   f'-DVCPKG_INSTALLED_DIR={ROOT}/build/vcpkg_installed',
                   f'-DVCPKG_OVERLAY_TRIPLETS={ROOT}/ci/triplets']
    run('cmake', '-S', source, '-B', binary, '-G', 'Ninja', *common, *['-D' + o for o in options])
    run('cmake', '--build', binary, '--parallel', JOBS)
    run('cmake', '--install', binary)

def build_dependency(name, record):
    stamp = PREFIX / 'share/stamps' / name
    fingerprint = hashlib.sha256((json.dumps(record, sort_keys=True) + Path(__file__).read_text()).encode()).hexdigest()
    if stamp.exists() and stamp.read_text() == fingerprint:
        print(f'Using cached {name}', flush=True)
        return
    source = extract(download(record, ROOT / 'build/downloads' / (name + '.tar')), WORK / name)
    if name == 'sqlite':
        run(source / 'configure', f'--prefix={PREFIX}', '--enable-shared', '--disable-static', '--enable-rtree', cwd=source)
        run('make', '-j' + JOBS, cwd=source)
        run('make', 'install', cwd=source)
    elif name == 'openssl':
        target = 'darwin64-arm64-cc' if MAC else 'linux-x86_64'
        run('perl', source / 'Configure', target, 'shared', 'no-tests', f'--prefix={PREFIX}', '--libdir=lib', cwd=source)
        run('make', '-j' + JOBS, cwd=source)
        run('make', 'install_sw', cwd=source)
    else:
        cmake(source / record['subdir'], name, record['cmake'])
    # Retain source license notices with the SDK and ultimately the wheel.
    notices = PREFIX / 'share/licenses' / name
    notices.mkdir(parents=True, exist_ok=True)
    for pattern in ('LICENSE*', 'COPYING*', 'COPYRIGHT*'):
        for path in source.glob(pattern):
            if path.is_file():
                shutil.copy2(path, notices / path.name)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(fingerprint)

if __name__ == '__main__':
    PREFIX.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    release = json.loads((ROOT / 'build/release.json').read_text())
    sdk_stamp = PREFIX / 'sdk.sha256'
    sdk_key = hashlib.sha256((json.dumps([LOCK, release], sort_keys=True) + Path(__file__).read_text() + (ROOT / 'ci/provenance.py').read_text()).encode()).hexdigest()
    if sdk_stamp.exists() and sdk_stamp.read_text() == sdk_key:
        print('Using complete cached native SDK', flush=True)
        raise SystemExit(0)
    os.environ['PATH'] = str(PREFIX / 'bin') + os.pathsep + os.environ['PATH']
    os.environ['PKG_CONFIG_LIBDIR'] = str(PREFIX / 'lib/pkgconfig')
    os.environ['PKG_CONFIG_PATH'] = str(PREFIX / 'lib/pkgconfig')
    if not WINDOWS:
        os.environ['CPPFLAGS'] = f'-I{PREFIX}/include'
        os.environ['LDFLAGS'] = f'-L{PREFIX}/lib -Wl,-rpath,{PREFIX}/lib'
        os.environ['CFLAGS'] = '-O2 -fPIC' + (' -arch arm64 -mmacosx-version-min=11.0' if MAC else '')
        os.environ['CXXFLAGS'] = os.environ['CFLAGS']
        os.environ['LD_LIBRARY_PATH'] = str(PREFIX / 'lib')
    if MAC:
        os.environ['MACOSX_DEPLOYMENT_TARGET'] = '11.0'
    for name, record in LOCK['dependencies'].items():
        if not WINDOWS:
            build_dependency(name, record)
    release = json.loads((ROOT / 'build/release.json').read_text())
    source = extract(download(release['source'], ROOT / 'build/gdal.tar.gz'), WORK / 'gdal')
    options = ['BUILD_PYTHON_BINDINGS=OFF', 'BUILD_JAVA_BINDINGS=OFF', 'BUILD_CSHARP_BINDINGS=OFF',
               'BUILD_APPS=OFF', 'GDAL_USE_EXTERNAL_LIBS=OFF', 'GDAL_USE_INTERNAL_LIBS=WHEN_NO_EXTERNAL',
               'GDAL_BUILD_OPTIONAL_DRIVERS=OFF', 'OGR_BUILD_OPTIONAL_DRIVERS=OFF',
               'GDAL_ENABLE_PLUGINS=OFF', 'GDAL_ENABLE_PLUGINS_NO_DEPS=OFF']
    for dependency in ('ZLIB','ZSTD','JPEG','PNG','WEBP','LERC','TIFF','OPENJPEG','SQLITE3','GEOS','CURL','OPENSSL','EXPAT','HDF4','HDF5','NETCDF'):
        options.append(f'GDAL_USE_{dependency}=' + ('OFF' if WINDOWS and dependency == 'HDF4' else 'ON'))
    for driver in ('GTIFF','VRT','HDF4','HDF5','NETCDF','PNG','JPEG','WEBP','JP2OPENJPEG'):
        options.append(f'GDAL_ENABLE_DRIVER_{driver}=' + ('OFF' if WINDOWS and driver == 'HDF4' else 'ON'))
    for driver in ('GPKG','SQLITE','GEOJSON','SHAPE','VRT'):
        options.append(f'OGR_ENABLE_DRIVER_{driver}=ON')
    cmake(source, 'gdal', options)
    cache = (WORK / 'gdal-build/CMakeCache.txt').read_text()
    for option in options:
        if option.startswith(('GDAL_USE_', 'GDAL_ENABLE_DRIVER_', 'OGR_ENABLE_DRIVER_')) and option.endswith('=ON'):
            key = option.split('=')[0]
            # UNINITIALIZED entries mean upstream did not consume an option: fail closed.
            if f'{key}:BOOL=ON' not in cache:
                raise RuntimeError(f'Required option was not enabled: {key}')
    shutil.copy2(ROOT / 'build/release.json', PREFIX / 'release.json')
    (PREFIX / 'dependencies.json').write_text(json.dumps(LOCK, indent=2) + '\n')
    from provenance import write
    write(PREFIX, LOCK, release)
    sdk_stamp.write_text(sdk_key)
