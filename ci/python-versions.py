"""Select the latest four CPythons proven by conda-forge and cibuildwheel."""

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
        if "main" not in dist.get("labels", ["main"]):
            continue
        platform = dist["attrs"].get("subdir")
        match = re.search(r"py(\d+)", dist["attrs"].get("build", ""))
        if platform in found and match:
            found[platform].add("cp" + match.group(1))

    return set.intersection(*found.values())


identifiers = subprocess.check_output(
    [
        sys.executable,
        "-m",
        "cibuildwheel",
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
    if (match := re.match(r"^(cp\d+)-", line))
}

proven = conda_pythons(os.environ["GDAL_VERSION"])
selected = sorted(proven & cibw, key=lambda tag: int(tag[2:]))[-4:]

if len(selected) < 4:
    print("conda-forge is not ready:", ", ".join(sorted(proven)))
    output("ready", "false")
    raise SystemExit

versions = [f"{tag[2]}.{tag[3:]}" for tag in selected]

output("ready", "true")
output("python_versions", json.dumps(versions, separators=(",", ":")))
output("cibw_build", " ".join(f"{tag}-*" for tag in selected))
output("cibuildwheel_version", version("cibuildwheel"))

print("Python versions:", ", ".join(versions))
