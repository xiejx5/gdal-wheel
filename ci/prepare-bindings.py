"""Prepare the verified upstream Python bindings for a self-contained wheel."""

import json
import os
from pathlib import Path
import re
import shutil

from sources import ROOT, download, extract


def replace_checked(text: str, pattern: str, replacement: str, expected: int, label: str) -> str:
    text, count = re.subn(pattern, replacement, text)
    if count != expected:
        raise RuntimeError(f"Upstream setup.py changed; review {label} patch (found {count}, expected {expected})")
    return text


def main() -> None:
    release = json.loads((ROOT / "build/release.json").read_text())
    source = extract(
        download(release["bindings"], ROOT / "build/bindings.tar.gz"),
        ROOT / "build/bindings-source",
    )
    package = ROOT / "build/python"
    if package.exists():
        shutil.rmtree(package)
    shutil.copytree(source, package)

    prefix = Path(os.environ["BUILD_PREFIX"]).resolve()
    osgeo = package / "osgeo"

    for name, required in (("gdal", "gdalvrt.xsd"), ("proj", "proj.db")):
        origin = prefix / "share" / name
        if not (origin / required).is_file():
            raise RuntimeError(f"Missing mandatory bundled data: {origin / required}")
        shutil.copytree(origin, osgeo / "data" / name)

    licenses = prefix / "share/licenses"
    if licenses.exists():
        shutil.copytree(licenses, osgeo / "data/licenses")

    for name in ("release.json", "dependencies.json", "provenance.json", "sbom.cdx.json"):
        shutil.copy2(prefix / name, osgeo / "data" / name)

    with (osgeo / "__init__.py").open("a") as stream:
        stream.write("\n\n# Unofficial wheel: bundled data defaults.\n")
        stream.write((ROOT / "ci/bootstrap.py").read_text())

    with (package / "MANIFEST.in").open("a") as stream:
        stream.write("\nrecursive-include osgeo/data *\n")

    setup = package / "setup.py"
    text = setup.read_text()

    # Upstream disables include_package_data, so explicitly include bundled data.
    needle = "exclude_package_data = exclude_package_data,"
    if text.count(needle) != 1:
        raise RuntimeError("Upstream setup.py changed; review data packaging patch")
    package_data = (
        "    package_data={'osgeo': [str(p.relative_to('osgeo')) "
        "for p in __import__('pathlib').Path('osgeo/data').rglob('*') if p.is_file()]},"
    )
    text = text.replace(needle, f"{needle}\n{package_data}")

    # GDAL's sdist reuses the same mutable argument lists for all Extension
    # objects. On macOS that leaks -std=c++11 into gdalconst_wrap.c and clang
    # rejects the C compilation. Give every extension its own list instead.
    text = replace_checked(
        text,
        r"\bextra_compile_args=extra_compile_args\b",
        "extra_compile_args=list(extra_compile_args)",
        expected=6,
        label="extension compile-argument isolation",
    )
    text = replace_checked(
        text,
        r"\bextra_link_args=extra_link_args\b",
        "extra_link_args=list(extra_link_args)",
        expected=6,
        label="extension link-argument isolation",
    )
    setup.write_text(text)

    with (package / "setup.cfg").open("a") as stream:
        stream.write("\n[build_ext]\n")
        stream.write(f"include_dirs = {prefix / 'include'}\n")
        stream.write(f"library_dirs = {prefix / 'lib'}\n")
        stream.write("libraries = gdal\n")
        if os.name != "nt":
            stream.write(f"gdal_config = {prefix / 'bin/gdal-config'}\n")

    print(package)


if __name__ == "__main__":
    main()
