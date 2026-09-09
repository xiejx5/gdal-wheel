"""Select proven Python ABIs for the wheel matrix."""

from importlib.metadata import version
import json
import os
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import urlopen


PLATFORMS = {'linux-64', 'osx-arm64', 'win-64'}


def output(name, value):
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
        print(f'{name}={value}', file=stream)


def tag_key(tag):
    digits = tag[2:].removesuffix('t')
    return int(digits[0]), int(digits[1:])


def python_version(tag):
    major, minor = tag_key(tag)
    return f'{major}.{minor}' + ('t' if tag.endswith('t') else '')


def conda_pythons(gdal_version):
    url = f'https://api.anaconda.org/release/conda-forge/gdal/{gdal_version}'
    try:
        with urlopen(url, timeout=30) as response:
            distributions = json.load(response)['distributions']
    except HTTPError as error:
        if error.code == 404:
            return set()
        raise

    found = {platform: set() for platform in PLATFORMS}

    for dist in distributions:
        if 'main' not in dist.get('labels', ['main']):
            continue

        attrs = dist['attrs']
        platform = attrs.get('subdir')
        if platform not in found:
            continue

        for dependency in attrs.get('depends', []):
            match = re.search(r'python_abi .* \*_(cp\d+t?)', dependency)
            if match:
                found[platform].add(match.group(1))

    return set.intersection(*found.values())


identifiers = subprocess.check_output(
    [
        sys.executable,
        '-m',
        'cibuildwheel',
        'build/bindings.tar.gz',
        '--platform',
        'linux',
        '--archs',
        'x86_64',
        '--print-build-identifiers',
    ],
    text=True,
)

cibw = {
    match.group(1)
    for line in identifiers.splitlines()
    if (match := re.match(r'^(cp\d+t?)-', line))
}
# actions/setup-python "3.x" gives this job the latest stable CPython.
# This prevents a release-candidate ABI from entering the matrix early.
stable = sys.version_info[:2]

supported = {
    tag
    for tag in conda_pythons(os.environ['GDAL_VERSION']) & cibw
    if tag_key(tag) <= stable
}

normal = sorted(
    (tag for tag in supported if not tag.endswith('t')),
    key=tag_key,
)[-3:]
if len(normal) < 3:
    print('conda-forge is not ready:', ', '.join(sorted(supported, key=tag_key)))
    output('ready', 'false')
    raise SystemExit

threaded = [f'{tag}t' for tag in normal if f'{tag}t' in supported]
selected = normal + threaded

output('ready', 'true')
output(
    'python_versions',
    json.dumps([python_version(tag) for tag in selected], separators=(',', ':')),
)
output('python_abis', '-'.join(selected))
output('build_python', normal[-1])
output('cibw_build', ' '.join(f'{tag}-*' for tag in selected))
output('cibuildwheel_version', version('cibuildwheel'))

print('Python versions:', ', '.join(python_version(tag) for tag in selected))
