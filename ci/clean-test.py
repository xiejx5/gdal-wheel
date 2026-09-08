"""Install and validate exactly one ABI wheel on a clean runner."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parents[1]


def run(*args, env=None) -> None:
    subprocess.run([str(arg) for arg in args], env=env, check=True)


def create_test_environment() -> None:
    environment = Path(".test-venv").resolve()
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    requirements = ["packaging", "pytest", "numpy"]
    requirements += {
        "linux": ["auditwheel"],
        "darwin": ["delocate==0.13.0"],
        "win32": ["delvewheel==1.13.1", "pefile"],
    }[sys.platform]
    run(python, "-m", "pip", "install", *requirements)

    env = {**os.environ, "PATH": str(python.parent) + os.pathsep + os.environ["PATH"]}
    run(python, Path(__file__).resolve(), "--inside-venv", env=env)


def test_wheel() -> None:
    # Import only inside the test venv so the workflow itself needs no launcher deps.
    from packaging.tags import sys_tags
    from packaging.utils import parse_wheel_filename

    compatible = set(sys_tags())
    wheels = [
        path
        for path in (ROOT / "wheelhouse").glob("*.whl")
        if parse_wheel_filename(path.name)[3] & compatible
    ]
    if len(wheels) != 1:
        raise RuntimeError(f"Expected one compatible GDAL wheel, got {wheels}")
    wheel = wheels[0]

    for variable in (
        "GDAL_DATA",
        "PROJ_DATA",
        "PROJ_LIB",
        "GDAL_CONFIG",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "BUILD_PREFIX",
    ):
        os.environ.pop(variable, None)
    os.environ["GDAL_DRIVER_PATH"] = "disable"
    os.environ["PROJ_NETWORK"] = "OFF"

    # numpy/pytest are already installed in this isolated venv.
    run(sys.executable, "-m", "pip", "install", "--no-deps", wheel)
    run(sys.executable, ROOT / "ci/inspect-wheel.py", wheel)
    run(
        sys.executable,
        "-m",
        "pytest",
        ROOT / "tests/test_binary_features.py",
        "-v",
        "--junitxml=feature-tests.xml",
    )

    coexistence = "not-required"
    if sys.version_info[:2] == (3, 12):
        run(
            sys.executable,
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            "rasterio",
            "fiona",
        )
        run(sys.executable, ROOT / "tests/coexistence.py")
        coexistence = "passed"

    result = {
        "wheel": wheel.name,
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "feature_tests": "passed",
        "leak_tests": "passed",
        "coexistence_tests": coexistence,
        "hdf4": "not-supported" if sys.platform == "win32" else "passed",
    }
    (ROOT / "test-result.json").write_text(json.dumps(result, indent=2) + "\n")


def main() -> None:
    if "--inside-venv" in sys.argv:
        test_wheel()
    else:
        create_test_environment()


if __name__ == "__main__":
    main()
