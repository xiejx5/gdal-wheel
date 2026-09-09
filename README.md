# GDAL binary wheel

Unofficial, self-contained [GDAL](https://github.com/OSGeo/gdal) binary wheels with NumPy bindings.

Wheels are built for Linux, macOS, and Windows, tested on clean runners, and published to PyPI and GitHub Releases.

## Install

```bash
uv add gdal-wheel
```

The distribution name is `gdal-wheel`; the Python import remains the standard GDAL import:

```python
from osgeo import gdal
print(gdal.VersionInfo("--version"))
```

Do not install the separate `GDAL` distribution in the same environment because both provide `osgeo`.

## Releases

GitHub Actions checks every three months for the newest stable GDAL release.

A release is published only after the complete wheel set passes clean-runner tests on:

- Linux x86_64
- macOS ARM64
- Windows x86_64
- the latest three proven-compatible CPython versions
- all proven free-threaded counterparts of those selected Python versions

The version of `gdal-wheel` follows the upstream GDAL version.

Browse the [GitHub Releases](https://github.com/xiejx5/gdal-wheel/releases).
