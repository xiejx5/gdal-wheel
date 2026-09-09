# GDAL wheel

Unofficial, self-contained [GDAL](https://github.com/OSGeo/gdal) binary wheels with NumPy bindings for Linux, macOS, and Windows.

There are two ways to install them.

## 1. Install `gdal-wheel` from PyPI

```bash
uv add gdal-wheel
```

The package name is `gdal-wheel`, but the Python import stays the same:

```python
from osgeo import gdal
```

## 2. Install `gdal` from the Cloudflare wheel index

Package index: [gdal.xiejx5.workers.dev](https://gdal.xiejx5.workers.dev)

Add this to `pyproject.toml`:

```toml
[tool.uv]
no-build-package = ["gdal"]

[tool.uv.sources]
gdal = { index = "gdal-wheel" }

[[tool.uv.index]]
name = "gdal-wheel"
url = "https://gdal.xiejx5.workers.dev"
format = "flat"
explicit = true
```

Then install:

```bash
uv add gdal
```

## Releases

The GitHub Action checks once a month for a new stable GDAL release.

`gdal-wheel` uses the same version as GDAL. For example, GDAL `3.13.3` is published as `gdal-wheel==3.13.3`.

- PyPI receives the `gdal-wheel` wheels.
- GitHub Releases keep `GDAL`-named wheels for the Cloudflare index.
