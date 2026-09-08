"""Select the latest four stable CPython versions supported by cibuildwheel."""

from importlib.metadata import version
import json
import os
import re
import subprocess
import sys


def output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise RuntimeError("GITHUB_OUTPUT is not set")
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(f"{name}={value}\n")


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

tags = {
    match.group(1)
    for line in identifiers.splitlines()
    if (match := re.match(r"^(cp\d+)-", line))
}

selected = sorted(tags, key=lambda tag: int(tag[2:]))[-4:]
if len(selected) != 4:
    raise RuntimeError(f"Expected at least four supported CPython versions, got {selected}")

versions = []
for tag in selected:
    digits = tag[2:]
    versions.append(f"{digits[0]}.{digits[1:]}")

output("python_versions", json.dumps(versions, separators=(",", ":")))
output("cibw_build", " ".join(f"{tag}-*" for tag in selected))
output("cibuildwheel_version", version("cibuildwheel"))

print("Python versions:", ", ".join(versions))
print("CIBW_BUILD:", " ".join(f"{tag}-*" for tag in selected))
print("cibuildwheel:", version("cibuildwheel"))
