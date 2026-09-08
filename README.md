# GDAL binary wheels

Unofficial, self-contained wheels of upstream [`GDAL`](https://github.com/OSGeo/gdal), including NumPy bindings. No system GDAL installation is needed. Wheels are intended for GitHub Releases, never the official GDAL project on PyPI.

**Status: initial build validation. No release has been published yet.** The first target is dynamically resolved from official stable upstream releases (currently 3.13.3). Automatic scheduling and publication will be added after the manual build passes on all three platforms.

| Platform | Python | HDF4 / MODIS HDF-EOS2 | HDF5 / netCDF |
|---|---|---|---|
| Linux x86_64, manylinux_2_28 | 3.11–3.14 | Required | Required |
| macOS Apple Silicon | 3.11–3.14 | Required | Required |
| Windows x64 | 3.11–3.14 | Not included initially | Required |

macOS dependencies target 11.0. Delocate inspects the actual binaries and determines the final compatibility tag; it is never renamed by hand. Python is CPython with the standard GIL build. Additional architectures can be added to the build/test matrix.

MODIS LAI/FPAR products such as MOD15A2H and MCD15A2H are distributed as HDF-EOS2 (HDF4). The initial Windows wheels cannot open those original files. HDF5 does not substitute for HDF4. See [NASA's MOD15A2H file specification](https://ladsweb.modaps.eosdis.nasa.gov/filespec/MODIS/6/MOD15A2H).

## Build

Run **Actions → GDAL wheels → Run workflow**. Leave the version blank for the latest stable release, or supply a version such as `3.13.3`.

The workflow:

1. Resolves an official stable OSGeo/GDAL release, requires the release asset's SHA256 digest, and verifies both native source and the upstream Python sdist before building.
2. Builds one shared native SDK per platform. Linux uses the same manylinux image as cibuildwheel. macOS builds from pinned sources. Windows uses a pinned vcpkg registry for dependencies and builds the selected GDAL release separately.
3. Builds all four Python ABIs against that SDK using cibuildwheel. The only Python package modifications are explicit SDK paths, bundled data/notices, and a small data-path bootstrap.
4. Repairs wheels with auditwheel, delocate, or delvewheel, preserving their native-library isolation mechanisms.
5. Installs the repaired wheels in **12 fresh runner jobs**, tests real features, and inspects native links. Python 3.12 also tests both import orders with Rasterio and Fiona.
6. Requires all 12 successful results before generating `manifest.json`, wheel SHA256 sidecars, and a hash-linked `index.html` in the `tested-release` Actions artifact.

Actions artifacts are validation outputs, not permanent distribution. A release/index URL will be documented once publication is validated.

## Keeping compilation fast

- One native build per OS/architecture, not per Python version.
- Release builds with Ninja and bounded parallel compilation; no expensive link-time optimization.
- Only the required GDAL drivers; no Java, C#, native command-line applications, or native test suites.
- Cache native dependencies across GDAL patch releases. Cache identity includes runner, dependency lock and build recipes. Each completed dependency also has a content-based stamp; a failed build never writes a stamp.
- vcpkg binary cache on Windows; native dependencies remain fixed when GDAL changes.
- The build matrix runs platforms independently and reports every platform failure.

## Feature contract

Required everywhere: GTiff, COG, VRT, MEM, ZSTD GeoTIFF write/read, HDF5/HDF5Image, netCDF, PNG, JPEG, WEBP, JP2OpenJPEG, GPKG, SQLite, GeoJSON, Shapefile, coordinate transforms, NumPy arrays, and `/vsicurl/`. HDF4/HDF4Image and real HDF4 reads are additionally mandatory on Linux/macOS.

Tests use small committed synthetic HDF4 and HDF5 files with known values and two subdatasets. They test the container → subdataset → raster read path. They are not real MODIS granules; an HDF-EOS2 fixture is a useful future addition. `tests/data/generate.py` documents how to reproduce them.

The wheel includes the complete installed GDAL and PROJ data directories under `osgeo/data`, native source license notices, and source/dependency provenance. The bootstrap respects explicit GDAL configuration, `GDAL_DATA`, `PROJ_DATA`, and legacy `PROJ_LIB`. Set `SKIP_GDAL_DATA_CHECK=1` to disable it. PROJ's search path is initialized from the bundled `PROJ_DATA` before `osr` is imported.

`ci/dependencies.json` pins Unix source versions, URLs, and verified SHA256 values. Windows dependency versions and SHA512-verified source downloads are pinned by the vcpkg baseline; they may differ from Unix versions. No mutable registry or upstream branch is used for release source builds.

Native hash/name mangling and wheel SHA256 serve different purposes: the former reduces library collisions, while the latter verifies downloadable artifacts. Coexistence tests are a compatibility gate, not a guarantee of isolation from every native package.

## Development checks

```bash
python -m pip install pytest packaging
python -m pytest tests/test_pipeline.py
```

These tests cover corrupted downloads, archive traversal, rejected versions, missing feature results, release completeness, integrity links, and bootstrap precedence. Native runtime tests require an installed repaired wheel:

```bash
python -m pip install numpy pytest
python -m pytest tests/test_binary_features.py
python tests/coexistence.py  # requires Rasterio and Fiona
```

The architecture follows [Rasterio's wheel workflow](https://github.com/rasterio/rasterio/blob/main/.github/workflows/build-wheels.yaml) and [native build configuration](https://github.com/rasterio/rasterio/blob/main/ci/config.sh), with an explicit HDF4 contract on Unix platforms and uniform SHA256 checking of the Unix source stack.
