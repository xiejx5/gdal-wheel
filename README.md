# GDAL binary wheels

Unofficial, self-contained [GDAL](https://github.com/OSGeo/gdal) binary wheels with NumPy bindings.

Wheels are built for Linux, macOS, and Windows and published as GitHub Release assets instead of PyPI.

## Install with uv

Add the following to your `pyproject.toml`:

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

If these tables already exist, merge the entries instead of creating duplicates.

Then install GDAL:

```bash
uv add gdal
```

Verify the installation:

```bash
uv run python -c 'from osgeo import gdal; print(gdal.VersionInfo("--version"))'
```

`no-build-package` prevents `uv` from falling back to building GDAL from source.

The explicit flat index is used only for `gdal`; other dependencies continue to use your normal package indexes.

See the [uv index documentation](https://docs.astral.sh/uv/concepts/indexes/) for details.

## Releases

GitHub Actions checks daily for new stable GDAL releases.

A release is published only after the complete wheel set passes clean-runner tests on:

- Linux x86_64
- macOS ARM64
- Windows x86_64
- the latest four proven-compatible CPython versions

Browse the published [GitHub Releases](https://github.com/xiejx5/gdal-wheels/releases).
