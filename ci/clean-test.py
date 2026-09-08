"""Install and test one repaired GDAL wheel on a fresh runner."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE = ROOT / "wheelhouse"
RESULT = ROOT / "test-result.json"
JUNIT = ROOT / "feature-tests.xml"


def run(*args: object) -> None:
    print("+", *map(str, args), flush=True)
    subprocess.run([str(arg) for arg in args], check=True)


def install(*packages: object, no_deps: bool = False) -> None:
    command: list[object] = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--only-binary=:all:",
    ]
    if no_deps:
        command.append("--no-deps")
    command.extend(packages)
    run(*command)


def compatible_wheel() -> Path:
    from packaging.tags import sys_tags
    from packaging.utils import parse_wheel_filename

    supported = set(sys_tags())
    wheels = [
        wheel
        for wheel in WHEELHOUSE.glob("*.whl")
        if parse_wheel_filename(wheel.name)[3] & supported
    ]
    if len(wheels) != 1:
        raise RuntimeError(f"Expected one compatible wheel, found: {wheels}")
    return wheels[0]


def clean_environment() -> None:
    for name in (
        "GDAL_DATA",
        "PROJ_DATA",
        "PROJ_LIB",
        "GDAL_CONFIG",
        "GDAL_DRIVER_PATH",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "BUILD_PREFIX",
    ):
        os.environ.pop(name, None)

    os.environ["PROJ_NETWORK"] = "OFF"


def main() -> None:
    report = {
        "wheel": None,
        "sha256": None,
        "feature_tests": "failed",
        "coexistence_tests": "failed",
        "hdf4": "not-supported" if sys.platform == "win32" else "failed",
    }

    try:
        install("packaging", "pytest", "numpy")
        wheel = compatible_wheel()

        report["wheel"] = wheel.name
        report["sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()

        clean_environment()
        install(wheel, no_deps=True)

        run(sys.executable, ROOT / "ci/inspect-wheel.py", wheel)
        run(
            sys.executable,
            "-m",
            "pytest",
            ROOT / "tests/test_binary_features.py",
            "-q",
            f"--junitxml={JUNIT}",
        )

        report["feature_tests"] = "passed"
        if sys.platform != "win32":
            report["hdf4"] = "passed"

        install("rasterio", "fiona")
        run(sys.executable, ROOT / "tests/coexistence.py")
        report["coexistence_tests"] = "passed"

    finally:
        RESULT.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
