"""Build one shared native GDAL SDK per platform and reuse it for every ABI."""

import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess

from sources import ROOT, download, extract


PREFIX = Path(os.environ["BUILD_PREFIX"]).resolve()
WORK = ROOT / "build" / "native"
LOCK = json.loads((ROOT / "ci/dependencies.json").read_text())
NATIVE_TOOLS = (ROOT / "ci/native-requirements.txt").read_text()
WINDOWS = os.name == "nt"
MACOS = platform.system() == "Darwin"
JOBS = str(os.cpu_count() or 2)

# Bump this only when the way third-party dependencies are configured changes.
# Ordinary refactors of this file should not force every dependency to rebuild.
DEPENDENCY_RECIPE_VERSION = 2


def run(*args, cwd=None):
    print("+", *map(str, args), flush=True)
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def digest(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def dependency_key(name: str, record: dict) -> str:
    return digest(
        {
            "recipe": DEPENDENCY_RECIPE_VERSION,
            "name": name,
            "record": record,
            "native_tools": NATIVE_TOOLS,
        }
    )


def cmake(source: Path, name: str, options: list[str]) -> None:
    binary = WORK / f"{name}-build"
    common = [
        f"-DCMAKE_INSTALL_PREFIX={PREFIX}",
        f"-DCMAKE_PREFIX_PATH={PREFIX}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_INSTALL_LIBDIR=lib",
        "-DBUILD_SHARED_LIBS=ON",
        "-DBUILD_TESTING=OFF",
        "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
        "-DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF",
        "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF",
        "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF",
    ]

    if MACOS:
        common += [
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0",
            "-DCMAKE_OSX_ARCHITECTURES=arm64",
            "-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew;/usr/local",
            f"-DCMAKE_INSTALL_NAME_DIR={PREFIX}/lib",
        ]

    if WINDOWS:
        vcpkg = Path(os.environ["VCPKG_INSTALLATION_ROOT"])
        common += [
            f"-DCMAKE_TOOLCHAIN_FILE={vcpkg}/scripts/buildsystems/vcpkg.cmake",
            "-DVCPKG_TARGET_TRIPLET=x64-windows",
            "-DVCPKG_MANIFEST_MODE=OFF",
            f"-DVCPKG_INSTALLED_DIR={ROOT}/build/vcpkg_installed",
            f"-DVCPKG_OVERLAY_TRIPLETS={ROOT}/ci/triplets",
        ]

    run(
        "cmake",
        "-S",
        source,
        "-B",
        binary,
        "-G",
        "Ninja",
        *common,
        *(f"-D{option}" for option in options),
    )
    run("cmake", "--build", binary, "--parallel", JOBS)
    run("cmake", "--install", binary)


def save_licenses(name: str, source: Path) -> None:
    destination = PREFIX / "share/licenses" / name
    destination.mkdir(parents=True, exist_ok=True)
    for pattern in ("LICENSE*", "COPYING*", "COPYRIGHT*"):
        for path in source.glob(pattern):
            if path.is_file():
                shutil.copy2(path, destination / path.name)


def build_dependency(name: str, record: dict) -> None:
    stamp = PREFIX / "share/stamps" / name
    fingerprint = dependency_key(name, record)
    if stamp.exists() and stamp.read_text() == fingerprint:
        print(f"Using cached {name}", flush=True)
        return

    source = extract(
        download(record, ROOT / "build/downloads" / f"{name}.tar"),
        WORK / name,
    )

    if name == "sqlite":
        run(
            source / "configure",
            f"--prefix={PREFIX}",
            "--enable-shared",
            "--disable-static",
            "--enable-rtree",
            cwd=source,
        )
        run("make", f"-j{JOBS}", cwd=source)
        run("make", "install", cwd=source)
    elif name == "openssl":
        target = "darwin64-arm64-cc" if MACOS else "linux-x86_64"
        run(
            "perl",
            source / "Configure",
            target,
            "shared",
            "no-tests",
            f"--prefix={PREFIX}",
            "--libdir=lib",
            cwd=source,
        )
        run("make", f"-j{JOBS}", cwd=source)
        run("make", "install_sw", cwd=source)
    else:
        cmake(source / record["subdir"], name, record["cmake"])

    save_licenses(name, source)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(fingerprint)


def configure_environment() -> None:
    os.environ["PATH"] = str(PREFIX / "bin") + os.pathsep + os.environ["PATH"]
    os.environ["PKG_CONFIG_LIBDIR"] = str(PREFIX / "lib/pkgconfig")
    os.environ["PKG_CONFIG_PATH"] = str(PREFIX / "lib/pkgconfig")

    if not WINDOWS:
        os.environ["CPPFLAGS"] = f"-I{PREFIX}/include"
        os.environ["LDFLAGS"] = f"-L{PREFIX}/lib -Wl,-rpath,{PREFIX}/lib"
        flags = "-O2 -fPIC"
        if MACOS:
            flags += " -arch arm64 -mmacosx-version-min=11.0"
        os.environ["CFLAGS"] = flags
        os.environ["CXXFLAGS"] = flags
        os.environ["LD_LIBRARY_PATH"] = str(PREFIX / "lib")

    if MACOS:
        os.environ["MACOSX_DEPLOYMENT_TARGET"] = "11.0"


def gdal_options() -> list[str]:
    options = [
        "BUILD_PYTHON_BINDINGS=OFF",
        "BUILD_JAVA_BINDINGS=OFF",
        "BUILD_CSHARP_BINDINGS=OFF",
        "BUILD_APPS=OFF",
        "GDAL_USE_EXTERNAL_LIBS=OFF",
        "GDAL_USE_INTERNAL_LIBS=WHEN_NO_EXTERNAL",
        "GDAL_BUILD_OPTIONAL_DRIVERS=OFF",
        "OGR_BUILD_OPTIONAL_DRIVERS=OFF",
        "GDAL_ENABLE_PLUGINS=OFF",
        "GDAL_ENABLE_PLUGINS_NO_DEPS=OFF",
    ]

    dependencies = (
        "ZLIB",
        "ZSTD",
        "JPEG",
        "PNG",
        "WEBP",
        "LERC",
        "TIFF",
        "OPENJPEG",
        "SQLITE3",
        "GEOS",
        "CURL",
        "OPENSSL",
        "EXPAT",
        "HDF4",
        "HDF5",
        "NETCDF",
    )
    for dependency in dependencies:
        enabled = not (WINDOWS and dependency == "HDF4")
        options.append(f"GDAL_USE_{dependency}={'ON' if enabled else 'OFF'}")

    raster_drivers = ("GTIFF", "VRT", "HDF4", "HDF5", "NETCDF", "PNG", "JPEG", "WEBP", "JP2OPENJPEG")
    for driver in raster_drivers:
        enabled = not (WINDOWS and driver == "HDF4")
        options.append(f"GDAL_ENABLE_DRIVER_{driver}={'ON' if enabled else 'OFF'}")

    for driver in ("GPKG", "SQLITE", "GEOJSON", "SHAPE", "VRT"):
        options.append(f"OGR_ENABLE_DRIVER_{driver}=ON")

    return options


def verify_options(options: list[str]) -> None:
    cache = (WORK / "gdal-build/CMakeCache.txt").read_text()
    prefixes = ("GDAL_USE_", "GDAL_ENABLE_DRIVER_", "OGR_ENABLE_DRIVER_")
    for option in options:
        if option.startswith(prefixes) and option.endswith("=ON"):
            key = option.split("=", 1)[0]
            if f"{key}:BOOL=ON" not in cache:
                raise RuntimeError(f"Required option was not enabled: {key}")


def main() -> None:
    PREFIX.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    release = json.loads((ROOT / "build/release.json").read_text())
    sdk_stamp = PREFIX / "sdk.sha256"
    sdk_key = digest(
        json.dumps([LOCK, release], sort_keys=True)
        + Path(__file__).read_text()
        + NATIVE_TOOLS
        + (ROOT / "ci/provenance.py").read_text()
    )
    if sdk_stamp.exists() and sdk_stamp.read_text() == sdk_key:
        print("Using complete cached native SDK", flush=True)
        return

    configure_environment()

    if not WINDOWS:
        for name, record in LOCK["dependencies"].items():
            build_dependency(name, record)

    source = extract(
        download(release["source"], ROOT / "build/gdal.tar.gz"),
        WORK / "gdal",
    )
    options = gdal_options()
    cmake(source, "gdal", options)
    verify_options(options)

    shutil.copy2(ROOT / "build/release.json", PREFIX / "release.json")
    (PREFIX / "dependencies.json").write_text(json.dumps(LOCK, indent=2) + "\n")

    from provenance import write

    write(PREFIX, LOCK, release)
    sdk_stamp.write_text(sdk_key)


if __name__ == "__main__":
    main()
