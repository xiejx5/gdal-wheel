"""Only a complete, independently tested 12-wheel set can be released."""

import argparse
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import quote
from packaging.utils import parse_wheel_filename

PYTHONS = {"cp311", "cp312", "cp313", "cp314"}
PLATFORMS = {"linux-x86_64", "windows-x86_64", "macos-arm64"}


def platform_name(tags):
    names = {tag.platform for tag in tags}
    if "win_amd64" in names:
        return "windows-x86_64"
    if all(n.startswith("macosx_") and n.endswith("_arm64") for n in names):
        return "macos-arm64"
    if "manylinux_2_28_x86_64" in names:
        return "linux-x86_64"
    raise ValueError(f"Unexpected wheel platform: {names}")


def generate(directory, results, release, repository):
    reports = [json.loads(p.read_text()) for p in results.rglob("test-result.json")]
    rows, seen = [], set()
    for path in sorted(directory.glob("*.whl")):
        name, version, build, tags = parse_wheel_filename(path.name)
        if name != "gdal" or str(version) != release["version"] or build:
            raise ValueError(f"Unexpected wheel: {path.name}")
        interpreters = {t.interpreter for t in tags}
        if len(interpreters) != 1:
            raise ValueError("Unexpected multi-ABI wheel")
        python = interpreters.pop()
        if python not in PYTHONS or {t.abi for t in tags} != {python}:
            raise ValueError("Unsupported Python ABI")
        platform = platform_name(tags)
        if (python, platform) in seen:
            raise ValueError("Duplicate Python/platform wheel")
        seen.add((python, platform))
        report = [r for r in reports if r["wheel"] == path.name]
        if len(report) != 1 or any(
            report[0].get(k) != "passed" for k in ("feature_tests", "leak_tests")
        ):
            raise ValueError(f"Missing successful clean test: {path.name}")
        if python == "cp312" and report[0].get("coexistence_tests") != "passed":
            raise ValueError("Missing coexistence gate")
        expected_hdf4 = "not-supported" if platform == "windows-x86_64" else "passed"
        if report[0].get("hdf4") != expected_hdf4:
            raise ValueError("HDF4 feature contract mismatch")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if report[0].get("sha256") != digest:
            raise ValueError(f"Tested wheel bytes do not match artifact: {path.name}")
        (directory / (path.name + ".sha256")).write_text(f"{digest}  {path.name}\n")
        rows.append(
            dict(
                filename=path.name,
                sha256=digest,
                python=python,
                platform=platform,
                tags=sorted(str(t) for t in tags),
                **{k: v for k, v in report[0].items() if k not in ("wheel", "sha256")},
            )
        )
    if seen != {(python, platform) for python in PYTHONS for platform in PLATFORMS}:
        raise ValueError(f"Incomplete release: {seen}")
    manifest = dict(
        schema_version=1,
        complete=True,
        version=release["version"],
        upstream=release,
        platforms={p: "passed" for p in sorted(PLATFORMS)},
        wheels=rows,
    )
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    base = (
        f"https://github.com/{repository}/releases/download/gdal-v{release['version']}"
    )
    links = [
        f'<a href="{base}/{quote(r["filename"])}#sha256={r["sha256"]}">{html.escape(r["filename"])}</a><br>'
        for r in rows
    ]
    (directory / "index.html").write_text(
        '<!doctype html>\n<html><head><meta charset="utf-8"><title>GDAL wheels</title></head><body>\n'
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
        args.wheels, args.results, json.loads(args.release.read_text()), args.repository
    )
