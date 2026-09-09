"""Small CycloneDX inventory of the native sources represented by a wheel."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess


def write(prefix, lock, release):
    prefix = Path(prefix)
    components = [
        dict(
            type='library',
            name='GDAL',
            version=release['version'],
            hashes=[{'alg': 'SHA-256', 'content': release['source']['sha256']}],
            externalReferences=[
                {'type': 'distribution', 'url': release['source']['url']}
            ],
        )
    ]
    if os.name == 'nt':
        receipt = prefix / 'vcpkg-packages.json'
        packages = json.loads(receipt.read_text(encoding='utf-8-sig'))
        for package in packages.values():
            components.append(
                dict(
                    type='library',
                    name=package['package_name'],
                    version=package['version'],
                )
            )
    else:
        for name, dependency in lock['dependencies'].items():
            components.append(
                dict(
                    type='library',
                    name=name,
                    version=dependency['version'],
                    hashes=[{'alg': 'SHA-256', 'content': dependency['sha256']}],
                    externalReferences=[
                        {'type': 'distribution', 'url': dependency['url']}
                    ],
                )
            )
    cache = prefix.parent / 'build/native/gdal-build/CMakeCache.txt'
    # Compiler path/version and resolved dependency locations are retained in CI logs.
    metadata = dict(
        os=platform.platform(),
        architecture=platform.machine(),
        git_commit=os.environ.get('GITHUB_SHA', 'local-validation'),
        workflow_run=os.environ.get('GITHUB_RUN_ID'),
        macos_deployment_target='11.0' if platform.system() == 'Darwin' else None,
        timestamp=datetime.now(timezone.utc).isoformat(),
        vcpkg_baseline=lock['vcpkg_baseline'] if os.name == 'nt' else None,
    )
    (prefix / 'provenance.json').write_text(json.dumps(metadata, indent=2) + '\n')
    sbom = dict(
        bomFormat='CycloneDX', specVersion='1.5', version=1, components=components
    )
    (prefix / 'sbom.cdx.json').write_text(json.dumps(sbom, indent=2) + '\n')
