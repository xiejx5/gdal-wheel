"""Bundled data defaults; appended to upstream osgeo initialization after _gdal loads."""


def _setup_bundled_data():
    import os
    from pathlib import Path

    if 'SKIP_GDAL_DATA_CHECK' in os.environ:
        return
    root = Path(__file__).resolve().parent / 'data'
    gdal_data, proj_data = root / 'gdal', root / 'proj'
    if (
        'GDAL_DATA' not in os.environ
        and _gdal.GetConfigOption('GDAL_DATA') is None
        and gdal_data.is_dir()
    ):
        path = str(gdal_data)
        _gdal.SetConfigOption('GDAL_DATA', path)
        _gdal.PushFinderLocation(path)
    # Explicit application/environment PROJ paths always win, including legacy PROJ_LIB.
    # Do not import osr here: that can reset application state or create import cycles.
    if proj_data.is_dir() and not any(
        os.environ.get(k) for k in ('PROJ_DATA', 'PROJ_LIB')
    ):
        os.environ['PROJ_DATA'] = str(proj_data)


_setup_bundled_data()
del _setup_bundled_data
