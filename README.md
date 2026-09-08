# GDAL binary wheels

Unofficial, self-contained [GDAL](https://github.com/OSGeo/gdal) wheels with NumPy bindings. They are published as GitHub Release assets, not to PyPI.

## Install with uv

In the application that uses GDAL, add these `uv` settings in `pyproject.toml`:

```toml
[tool.uv]
no-build-package = ["gdal"]

[tool.uv.sources]
gdal = { index = "gdal-wheels" }

[[tool.uv.index]]
name = "gdal-wheels"
url = "https://gdal.xiejx5.workers.dev"
format = "flat"
explicit = true
```

If those tables already exist, merge the entries instead of creating duplicate tables. Then add and install GDAL:

```bash
uv add gdal
uv sync
uv run python -c 'from osgeo import gdal; print(gdal.VersionInfo("--version"))'
```

`no-build-package` prevents uv from falling back to compiling GDAL from source. The explicit flat index is used only for `gdal`; other dependencies continue to use the normal index configuration. See uv's [index configuration](https://docs.astral.sh/uv/concepts/indexes/).

## Releases

GitHub Actions checks daily for a new stable GDAL release. A new version is built, tested on all three platforms and four Python versions, and published only when the complete test matrix passes.

Browse the published [GitHub Releases](https://github.com/xiejx5/gdal-wheels/releases).
