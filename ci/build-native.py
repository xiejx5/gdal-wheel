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
CACHE_SCHEMA = (ROOT / "ci/native-cache-version.txt").read_text().strip()
WINDOWS = os.name == "nt"
MACOS = platform.system() == "Darwin"
JOBS = str(os.cpu_count() or 2)


def run(*args, cwd=None) -> None:
    print("+", *map(str, args), flush=True)
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def digest(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def stamp_matches(path: Path, value: str) -> bool:
    return path.is_file() and path.read_text() == value


def write_stamp(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def platform_name() -> str:
    if WINDOWS:
        return "windows-x86_64"
    if MACOS:
        return "macos-arm64"
    return "linux-x86_64"


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
        "-DCMAKE_INSTALL_MESSAGE=LAZY",
    ]

    if not WINDOWS:
        # O2 materially shortens large C/C++ builds compared with the usual O3
        # Release flags while remaining an optimized production build.
        common += [
            "-DCMAKE_C_FLAGS_RELEASE=-O2 -DNDEBUG",
            "-DCMAKE_CXX_FLAGS_RELEASE=-O2 -DNDEBUG",
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
    # Building the install target directly avoids a second CMake/Ninja pass.
    run("cmake", "--build", binary, "--target", "install", "--parallel", JOBS)


def save_licenses(name: str, source: Path) -> None:
    destination = PREFIX / "share/licenses" / name
    destination.mkdir(parents=True, exist_ok=True)
    for pattern in ("LICENSE*", "COPYING*", "COPYRIGHT*"):
        for path in source.glob(pattern):
            if path.is_file():
                shutil.copy2(path, destination / path.name)


def dependency_key(name: str, record: dict) -> str:
    return digest(
        {
            "schema": CACHE_SCHEMA,
            "platform": platform_name(),
            "name": name,
            "record": record,
            "native_tools": NATIVE_TOOLS,
        }
    )


def build_dependency(name: str, record: dict) -> None:
    stamp = PREFIX / "share/stamps" / name
    fingerprint = dependency_key(name, record)
    if stamp_matches(stamp, fingerprint):
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
        run("make", f"-j{JOBS}", "install", cwd=source)
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
        run("make", f"-j{JOBS}", "install_sw", cwd=source)
    else:
        cmake(source / record["subdir"], name, record["cmake"])

    save_licenses(name, source)
    write_stamp(stamp, fingerprint)


def configure_environment() -> None:
    os.environ["PATH"] = str(PREFIX / "bin") + os.pathsep + os.environ["PATH"]
    os.environ["PKG_CONFIG_LIBDIR"] = str(PREFIX / "lib/pkgconfig")
    os.environ["PKG_CONFIG_PATH"] = str(PREFIX / "lib/pkgconfig")
    os.environ["CMAKE_BUILD_PARALLEL_LEVEL"] = JOBS

    if WINDOWS:
        return

    os.environ["MAKEFLAGS"] = f"-j{JOBS}"
    os.environ["CPPFLAGS"] = f"-I{PREFIX}/include"
    os.environ["LDFLAGS"] = f"-L{PREFIX}/lib -Wl,-rpath,{PREFIX}/lib"
    flags = "-O2 -pipe -fPIC"

    if MACOS:
        flags += " -arch arm64 -mmacosx-version-min=11.0"
        os.environ["MACOSX_DEPLOYMENT_TARGET"] = "11.0"
        os.environ["DYLD_LIBRARY_PATH"] = str(PREFIX / "lib")
    else:
        os.environ["LD_LIBRARY_PATH"] = str(PREFIX / "lib")

    os.environ["CFLAGS"] = flags
    os.environ["CXXFLAGS"] = flags


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

    raster_drivers = (
        "GTIFF",
        "VRT",
        "HDF4",
        "HDF5",
        "NETCDF",
        "PNG",
        "JPEG",
        "WEBP",
        "JP2OPENJPEG",
    )
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


def build_gdal(release: dict, options: list[str]) -> str:
    fingerprint = digest(
        {
            "schema": CACHE_SCHEMA,
            "platform": platform_name(),
            "release": release,
            "lock": LOCK,
            "native_tools": NATIVE_TOOLS,
            "options": options,
        }
    )
    stamp = PREFIX / "share/stamps/gdal"
    if stamp_matches(stamp, fingerprint):
        print("Using cached GDAL", flush=True)
        return fingerprint

    source = extract(
        download(release["source"], ROOT / "build/gdal.tar.gz"),
        WORK / "gdal",
    )
    cmake(source, "gdal", options)
    verify_options(options)
    save_licenses("gdal", source)
    write_stamp(stamp, fingerprint)
    return fingerprint


def write_metadata(release: dict) -> None:
    shutil.copy2(ROOT / "build/release.json", PREFIX / "release.json")
    (PREFIX / "dependencies.json").write_text(json.dumps(LOCK, indent=2) + "\n")

    from provenance import write

    write(PREFIX, LOCK, release)


def main() -> None:
    PREFIX.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    release = json.loads((ROOT / "build/release.json").read_text())
    options = gdal_options()
    gdal_fingerprint = digest(
        {
            "schema": CACHE_SCHEMA,
            "platform": platform_name(),
            "release": release,
            "lock": LOCK,
            "native_tools": NATIVE_TOOLS,
            "options": options,
        }
    )
    sdk_key = digest(
        {
            "gdal": gdal_fingerprint,
            "provenance": (ROOT / "ci/provenance.py").read_text(),
        }
    )
    sdk_stamp = PREFIX / "sdk.sha256"
    if stamp_matches(sdk_stamp, sdk_key):
        print("Using complete cached native SDK", flush=True)
        return

    configure_environment()

    if not WINDOWS:
        for name, record in LOCK["dependencies"].items():
            build_dependency(name, record)

    actual_gdal_fingerprint = build_gdal(release, options)
    if actual_gdal_fingerprint != gdal_fingerprint:
        raise RuntimeError("Internal GDAL cache key mismatch")

    write_metadata(release)
    write_stamp(sdk_stamp, sdk_key)


if __name__ == "__main__":
    main()
