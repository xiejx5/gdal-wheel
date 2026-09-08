"""Minimal static checks for files that must be bundled in the wheel."""

from pathlib import Path
import sys
import zipfile


REQUIRED = {
    "osgeo/data/gdal/gdalvrt.xsd",
    "osgeo/data/proj/proj.db",
}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: inspect-wheel.py WHEEL")

    wheel = Path(sys.argv[1])
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    missing = sorted(REQUIRED - names)
    if missing:
        raise RuntimeError(f"Missing packaged data: {missing}")

    if not any(name.startswith("osgeo/_gdal") for name in names):
        raise RuntimeError("Missing osgeo._gdal extension module")

    print(f"Wheel content OK: {wheel.name}")


if __name__ == "__main__":
    main()
