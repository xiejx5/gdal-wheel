"""Prepare the verified upstream GDAL Python bindings for a bundled wheel."""

import json
import os
from pathlib import Path
import shutil

from sources import ROOT, download, extract


JOBS = os.cpu_count() or 2


def patch_setup(package: Path) -> None:
    setup = package / "setup.py"
    text = setup.read_text()

    needle = "exclude_package_data = exclude_package_data,"
    if text.count(needle) != 1:
        raise RuntimeError("Upstream setup.py changed; review data packaging patch")

    package_data = (
        "    package_data={'osgeo': [str(p.relative_to('osgeo')) "
        "for p in __import__('pathlib').Path('osgeo/data').rglob('*') "
        "if p.is_file()]},"
    )
    text = text.replace(needle, f"{needle}\n{package_data}")

    text = text.replace(
        "extra_compile_args=extra_compile_args",
        "extra_compile_args=list(extra_compile_args)",
    )
    text = text.replace(
        "extra_link_args=extra_link_args",
        "extra_link_args=list(extra_link_args)",
    )

    marker = "\nsetup("
    if marker not in text:
        raise RuntimeError("Upstream setup.py changed; review free-threaded patch")

    free_threaded = """
if (__import__('os').name == 'nt' and
        __import__('sysconfig').get_config_var('Py_GIL_DISABLED')):
    for extension in ext_modules:
        extension.define_macros = list(extension.define_macros or [])
        extension.define_macros.append(('Py_GIL_DISABLED', '1'))
"""
    text = text.replace(marker, free_threaded + marker, 1)

    setup.write_text(text)


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
        required_path = origin / required

        if not required_path.is_file():
            raise RuntimeError(f"Missing mandatory bundled data: {required_path}")

        shutil.copytree(origin, osgeo / "data" / name)

    licenses = prefix / "share/licenses"

    if licenses.exists():
        shutil.copytree(licenses, osgeo / "data/licenses")

    for name in (
        "release.json",
        "dependencies.json",
        "provenance.json",
        "sbom.cdx.json",
    ):
        shutil.copy2(prefix / name, osgeo / "data" / name)

    with (osgeo / "__init__.py").open("a") as stream:
        stream.write("\n\n# Unofficial wheel: bundled data defaults.\n")
        stream.write((ROOT / "ci/bootstrap.py").read_text())

    with (package / "MANIFEST.in").open("a") as stream:
        stream.write("\nrecursive-include osgeo/data *\n")

    patch_setup(package)

    with (package / "setup.cfg").open("a") as stream:
        stream.write("\n[build_ext]\n")
        stream.write(f"include_dirs = {prefix / 'include'}\n")
        stream.write(f"library_dirs = {prefix / 'lib'}\n")
        stream.write("libraries = gdal\n")
        stream.write(f"parallel = {JOBS}\n")

        if os.name != "nt":
            stream.write(f"gdal_config = {prefix / 'bin/gdal-config'}\n")

    print(package)


if __name__ == "__main__":
    main()
