"""Verified upstream release resolution and archive extraction (standard library only)."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def get_json(url):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'gdal-wheel'}
    if url.startswith('https://api.github.com/') and os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=120
    ) as response:
        return json.load(response)


def download(record, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = record['sha256']
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Missing or invalid SHA256')
    if (
        not destination.exists()
        or hashlib.sha256(destination.read_bytes()).hexdigest() != digest
    ):
        temporary = destination.with_suffix('.partial')
        with (
            urllib.request.urlopen(record['url'], timeout=180) as response,
            temporary.open('wb') as output,
        ):
            import shutil

            shutil.copyfileobj(response, output)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            temporary.unlink()
            raise ValueError(f'SHA256 mismatch: {record["url"]}')
        temporary.replace(destination)
    return destination


def extract(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        source.extractall(destination, filter='data')
    directories = [p for p in destination.iterdir() if p.is_dir()]
    if len(directories) != 1:
        raise ValueError(f'Expected one source directory in {archive}')
    return directories[0]


def resolve(version=None):
    base = 'https://api.github.com/repos/OSGeo/gdal'
    if version:
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise ValueError('Only stable semantic versions are supported')
        release = get_json(f'{base}/releases/tags/v{version}')
    else:
        releases = get_json(f'{base}/releases?per_page=100')
        stable = [
            r
            for r in releases
            if not r['draft']
            and not r['prerelease']
            and re.fullmatch(r'v\d+\.\d+\.\d+', r['tag_name'])
        ]
        release = max(
            stable, key=lambda r: tuple(map(int, r['tag_name'][1:].split('.')))
        )
    if release['draft'] or release['prerelease']:
        raise ValueError('Refusing draft or prerelease')
    version = release['tag_name'][1:]
    asset = next(a for a in release['assets'] if a['name'] == f'gdal-{version}.tar.gz')
    digest = asset.get('digest') or ''
    if not re.fullmatch('sha256:[0-9a-f]{64}', digest):
        raise ValueError(
            'Official source asset has no SHA256 digest; refusing to build'
        )
    commit = get_json(f'{base}/commits/{release["tag_name"]}')['sha']
    # Upstream's published sdist contains generated SWIG wrappers; no local SWIG fork.
    pypi = get_json(f'https://pypi.org/pypi/GDAL/{version}/json')
    sdist = next(a for a in pypi['urls'] if a['packagetype'] == 'sdist')
    return dict(
        version=version,
        tag=release['tag_name'],
        commit=commit,
        source=dict(url=asset['browser_download_url'], sha256=digest[7:]),
        bindings=dict(url=sdist['url'], sha256=sdist['digests']['sha256']),
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='')
    args = parser.parse_args()
    record = resolve(args.version)
    output = ROOT / 'build'
    output.mkdir(exist_ok=True)
    # Verification precedes every native build.
    download(record['source'], output / 'gdal.tar.gz')
    download(record['bindings'], output / 'bindings.tar.gz')
    (output / 'release.json').write_text(json.dumps(record, indent=2) + '\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write(f'version={record["version"]}\n')
    print(json.dumps(record, indent=2))
