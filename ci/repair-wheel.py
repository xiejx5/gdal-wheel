"""Bundle native GDAL dependencies into the wheel."""

from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PREFIX = ROOT / "gdal-libs"


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+", *command, flush=True)
    subprocess.run(command, env=env, check=True)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: repair-wheel.py WHEEL DESTINATION")

    wheel, destination = sys.argv[1:]
    env = os.environ.copy()

    if sys.platform == "linux":
        lib = PREFIX / "lib"
        env["LD_LIBRARY_PATH"] = str(lib)

        command = [
            "auditwheel",
            "repair",
            "--plat",
            "manylinux_2_28_x86_64",
            "-w",
            destination,
            wheel,
        ]

    elif sys.platform == "darwin":
        lib = PREFIX / "lib"
        env["DYLD_LIBRARY_PATH"] = str(lib)

        # Let delocate inspect the actual Mach-O deployment target.
        env.pop("MACOSX_DEPLOYMENT_TARGET", None)

        command = [
            "delocate-wheel",
            "--require-archs",
            "arm64",
            "-w",
            destination,
            wheel,
        ]

    else:
        dll_dir = PREFIX / "bin"

        if not dll_dir.is_dir():
            raise RuntimeError(f"Missing DLL directory: {dll_dir}")

        gdal_dll = dll_dir / "gdal.dll"
        if not gdal_dll.is_file():
            candidates = sorted(dll_dir.glob("gdal*.dll"))
            raise RuntimeError(
                f"GDAL DLL not found in {dll_dir}. "
                f"Candidates: {[p.name for p in candidates]}"
            )

        command = [
            "delvewheel",
            "repair",
            "--add-path",
            str(dll_dir),
            "-w",
            destination,
            wheel,
        ]

    run(command, env)


if __name__ == "__main__":
    main()
