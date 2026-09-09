"""Select proven normal and free-threaded CPython versions."""

from importlib.metadata import version
import json
import os
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import urlopen


PLATFORMS = {"linux-64", "osx-arm64", "win-64"}


def output(name, value):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        print(f"{name}={value}", file=stream)


def conda_pythons(gdal_version):
    url = f"https://api.anaconda.org/release/conda-forge/gdal/{gdal_version}"

    try:
        with urlopen(url, timeout=30) as response:
            distributions = json.load(response)["distributions"]
    except HTTPError as error:
        if error.code == 404:
            return set()
        raise

    found = {platform: set() for platform in PLATFORMS}

    for dist in distributions:
        attrs = dist["attrs"]
        platform = attrs.get("subdir")

        if platform not in found:
            continue

        for dependency in attrs.get("depends", []):
            match = re.search(r"python_abi .* \*_(cp\d+t?)", dependency)
            if match:
                found[platform].add(match.group(1))

    return set.intersection(*found.values())


def tag_key(tag):
    return int(tag[2:].removesuffix("t"))


def python_version(tag):
    digits = tag[2:].removesuffix("t")
    suffix = "t" if tag.endswith("t") else ""
    return f"{digits[0]}.{digits[1:]}{suffix}"


identifiers = subprocess.check_output(
    [
        sys.executable,
        "-m",
        "cibuildwheel",
        "build/bindings.tar.gz",
        "--platform",
        "linux",
        "--archs",
        "x86_64",
        "--print-build-identifiers",
    ],
    text=True,
)

cibw = {
    match.group(1)
    for line in identifiers.splitlines()
    if (match := re.match(r"^(cp\d+t?)-", line))
}

supported = conda_pythons(os.environ["GDAL_VERSION"]) & cibw

normal = sorted(
    (tag for tag in supported if not tag.endswith("t")),
    key=tag_key,
)[-4:]

threaded = sorted(
    (tag for tag in supported if tag.endswith("t")),
    key=tag_key,
)[-1:]

if len(normal) < 4 or not threaded:
    print("conda-forge is not ready:", ", ".join(sorted(supported, key=tag_key)))
    output("ready", "false")
    raise SystemExit

selected = normal + threaded

output("ready", "true")
output(
    "python_versions",
    json.dumps([python_version(tag) for tag in selected], separators=(",", ":")),
)
output("cibw_build", " ".join(f"{tag}-*" for tag in selected))
output("cibuildwheel_version", version("cibuildwheel"))

print("Python versions:", ", ".join(python_version(tag) for tag in selected))
