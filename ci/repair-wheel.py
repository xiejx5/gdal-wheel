"""Platform repair; let delocate derive the truthful macOS deployment tag."""
import os
from pathlib import Path
import subprocess
import sys

wheel, destination = sys.argv[1:]
prefix = Path(os.environ['BUILD_PREFIX'])
env = os.environ.copy()
if sys.platform == 'linux':
    env['LD_LIBRARY_PATH'] = str(prefix / 'lib')
    command = ['auditwheel', 'repair', '--plat', 'manylinux_2_28_x86_64', '-w', destination, wheel]
elif sys.platform == 'darwin':
    env['DYLD_LIBRARY_PATH'] = str(prefix / 'lib')
    # Native compilation targets 11.0; repair must inspect actual Mach-O versions.
    env.pop('MACOSX_DEPLOYMENT_TARGET', None)
    command = ['delocate-wheel', '--require-archs', 'arm64', '-w', destination, wheel]
else:
    command = ['delvewheel', 'repair', '--add-path', str(prefix / 'bin'), '-w', destination, wheel]
subprocess.run(command, env=env, check=True)
