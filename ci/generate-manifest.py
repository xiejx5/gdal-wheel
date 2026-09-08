"""Release only a complete four-Python, three-platform tested wheel set."""

import argparse
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import quote

from packaging.utils import parse_wheel_filename


PLATFORMS = {"linux-x86_64", "windows-x86_64", "macos-arm64"}


def platform_name(tags):
    names = {tag.platform for tag in tags}
    if "win_amd64" in names:
        return "windows-x86_64"
    if all(name.startswith("macosx_") and name.endswith("_arm64") for name in names):
        return "macos-arm64"
    if "manylinux_2_28_x86_64" in names:
        return "linux-x86_64"
    raise ValueError(f"Unexpected wheel platform: {names}")


def python_key(tag):
    return int(tag[2:])


def generate(directory, results, release, repository):
    reports = [json.loads(path.read_text()) for path in results.rglob("test-result.json")]
    rows = []
    seen = set()

    for path in sorted(directory.glob("*.whl")):
        name, version, build, tags = parse_wheel_filename(path.name)
        if name != "gdal" or str(version) != release["version"] or build:
            raise ValueError(f"Unexpected wheel: {path.name}")

        interpreters = {tag.interpreter for tag in tags}
        if len(interpreters) != 1:
            raise ValueError(f"Unexpected multi-ABI wheel: {path.name}")

        python = interpreters.pop()
        if not python.startswith("cp") or not python[2:].isdigit():
            raise ValueError(f"Unsupported Python ABI: {python}")
        if {tag.abi for tag in tags} != {python}:
            raise ValueError(f"Unexpected ABI tag: {path.name}")

        platform = platform_name(tags)
        key = (python, platform)
        if key in seen:
            raise ValueError(f"Duplicate Python/platform wheel: {key}")
        seen.add(key)

        matching = [report for report in reports if report.get("wheel") == path.name]
        if len(matching) != 1:
            raise ValueError(f"Missing clean-test result: {path.name}")
        report = matching[0]

        if report.get("feature_tests") != "passed":
            raise ValueError(f"Feature tests failed: {path.name}")
        if report.get("coexistence_tests") != "passed":
            raise ValueError(f"Coexistence tests failed: {path.name}")

        expected_hdf4 = "not-supported" if platform == "windows-x86_64" else "passed"
        if report.get("hdf4") != expected_hdf4:
            raise ValueError(f"HDF4 contract mismatch: {path.name}")

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if report.get("sha256") != digest:
            raise ValueError(f"Tested wheel bytes changed: {path.name}")

        (directory / f"{path.name}.sha256").write_text(f"{digest}  {path.name}\n")
        rows.append(
            {
                "filename": path.name,
                "sha256": digest,
                "python": python,
                "platform": platform,
                "tags": sorted(str(tag) for tag in tags),
                "feature_tests": "passed",
                "coexistence_tests": "passed",
                "hdf4": report["hdf4"],
            }
        )

    pythons = sorted({python for python, _ in seen}, key=python_key)
    if len(pythons) != 4:
        raise ValueError(f"Expected four Python versions, got {pythons}")

    expected = {(python, platform) for python in pythons for platform in PLATFORMS}
    if seen != expected:
        raise ValueError(f"Incomplete release: expected {expected}, got {seen}")

    manifest = {
        "schema_version": 1,
        "complete": True,
        "version": release["version"],
        "python_versions": pythons,
        "upstream": release,
        "platforms": {platform: "passed" for platform in sorted(PLATFORMS)},
        "wheels": rows,
    }

    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    base = f"https://github.com/{repository}/releases/download/gdal-v{release['version']}"
    links = [
        f'<a href="{base}/{quote(row["filename"])}#sha256={row["sha256"]}">'
        f'{html.escape(row["filename"])}</a><br>'
        for row in rows
    ]
    (directory / "index.html").write_text(
        '<!doctype html>\n<html><head><meta charset="utf-8">'
        "<title>GDAL wheels</title></head><body>\n"
        + "\n".join(links)
        + "\n</body></html>\n"
    )

    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheels", type=Path, default=Path("wheelhouse"))
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--release", type=Path, default=Path("build/release.json"))
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()

    generate(
        args.wheels,
        args.results,
        json.loads(args.release.read_text()),
        args.repository,
    )
