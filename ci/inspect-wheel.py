"""Reject native dependencies outside the wheel except OS ABI libraries."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

LINUX_SYSTEM = set('libc.so.6 libm.so.6 libdl.so.2 librt.so.1 libpthread.so.0 libutil.so.1 libgcc_s.so.1 libstdc++.so.6 libresolv.so.2 ld-linux-x86-64.so.2'.split())
WINDOWS_SYSTEM = set('kernel32.dll user32.dll advapi32.dll shell32.dll ole32.dll oleaut32.dll ws2_32.dll crypt32.dll bcrypt.dll ncrypt.dll secur32.dll normaliz.dll userenv.dll wldap32.dll winmm.dll version.dll shlwapi.dll gdi32.dll comdlg32.dll comctl32.dll rpcrt4.dll ntdll.dll iphlpapi.dll psapi.dll netapi32.dll msvcrt.dll ucrtbase.dll vcruntime140.dll vcruntime140_1.dll msvcp140.dll'.split())

def output(*args):
    result = subprocess.check_output(args, text=True)
    print(result)
    return result

def inspect(wheel):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(root)
        assert (root / 'osgeo/data/proj/proj.db').is_file()
        assert (root / 'osgeo/data/gdal/gdalvrt.xsd').is_file()
        files = [p for p in root.rglob('*') if p.is_file()]
        if sys.platform == 'linux':
            output('auditwheel', 'show', str(wheel))
            for path in files:
                if path.read_bytes()[:4] != b'\x7fELF':
                    continue
                linked = output('ldd', str(path))
                if 'not found' in linked:
                    raise RuntimeError(f'Unresolved dependency: {path}')
                for name, target in re.findall(r'^\s*(\S+) => (\S+)', linked, re.M):
                    if name not in LINUX_SYSTEM and not Path(target).resolve().is_relative_to(root):
                        raise RuntimeError(f'External native dependency: {name} => {target}')
        elif sys.platform == 'darwin':
            output('delocate-listdeps', str(wheel))
            for path in files:
                if path.suffix not in ('.so', '.dylib'):
                    continue
                for line in output('otool', '-L', str(path)).splitlines()[1:]:
                    name = line.strip().split(' (')[0]
                    if not name.startswith(('@loader_path/', '@rpath/', '/usr/lib/', '/System/Library/')):
                        raise RuntimeError(f'Non-wheel macOS install name: {name}')
                commands = output('otool', '-l', str(path))
                for name in re.findall(r'\n\s*path (.*?) \(offset', commands):
                    if name.startswith('/') and not name.startswith(('/usr/lib/', '/System/Library/')):
                        raise RuntimeError(f'Absolute build rpath: {name}')
        else:
            import pefile
            output('delvewheel', 'show', str(wheel))
            bundled = {p.name.lower() for p in files}
            for path in files:
                if path.suffix.lower() not in ('.pyd', '.dll'):
                    continue
                binary = pefile.PE(str(path))
                for entry in getattr(binary, 'DIRECTORY_ENTRY_IMPORT', []) + getattr(binary, 'DIRECTORY_ENTRY_DELAY_IMPORT', []):
                    name = entry.dll.decode().lower()
                    if name in bundled or name in WINDOWS_SYSTEM or name.startswith(('api-ms-win-', 'ext-ms-win-')) or re.fullmatch(r'python3\d*\.dll', name):
                        continue
                    raise RuntimeError(f'Unbundled DLL: {path.name} -> {name}')
                binary.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('wheel', type=Path)
    inspect(parser.parse_args().wheel)
