"""The published feature contract. Run against installed, repaired wheels only."""
import functools
import http.server
import os
from pathlib import Path
import subprocess
import sys
import threading

import numpy as np
import pytest
from osgeo import gdal, gdal_array, ogr, osr

gdal.UseExceptions()
DATA = Path(__file__).parent / 'data'
HDF4_REQUIRED = sys.platform != 'win32'
DRIVERS = ['GTiff', 'COG', 'VRT', 'MEM', 'HDF5', 'HDF5Image', 'netCDF',
           'PNG', 'JPEG', 'WEBP', 'JP2OpenJPEG', 'GPKG', 'SQLite', 'GeoJSON', 'ESRI Shapefile']
if HDF4_REQUIRED:
    DRIVERS += ['HDF4', 'HDF4Image']

@pytest.mark.parametrize('name', DRIVERS)
def test_driver(name):
    assert gdal.GetDriverByName(name) is not None, name

def test_zstd(tmp_path):
    path = str(tmp_path / 'zstd.tif')
    pixels = np.arange(256, dtype=np.uint16).reshape(16, 16)
    with gdal.GetDriverByName('GTiff').Create(path, 16, 16, 1, gdal.GDT_UInt16, ['COMPRESS=ZSTD']) as ds:
        ds.GetRasterBand(1).WriteArray(pixels)
    with gdal.Open(path) as ds:
        assert ds.GetMetadata('IMAGE_STRUCTURE')['COMPRESSION'] == 'ZSTD'
        np.testing.assert_array_equal(ds.ReadAsArray(), pixels)

@pytest.mark.parametrize('name', ['tiny_hdf4.hdf', 'tiny_hdf5.h5'])
def test_hdf_subdatasets(name):
    if name.endswith('.hdf') and not HDF4_REQUIRED:
        pytest.skip('Windows HDF4 is explicitly outside the initial feature contract')
    with gdal.Open(str(DATA / name)) as container:
        subdatasets = container.GetSubDatasets()
        assert len(subdatasets) >= 2
        target = next(uri for uri, description in subdatasets if 'fapar' in uri.lower())
        with gdal.Open(target) as raster:
            assert raster.RasterXSize == 3 and raster.RasterYSize == 2
            assert raster.ReadRaster() == bytes([0, 20, 40, 60, 80, 100])

def test_proj():
    source, target = osr.SpatialReference(), osr.SpatialReference()
    source.ImportFromEPSG(4326)
    target.ImportFromEPSG(3857)
    source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    x, y, _ = osr.CoordinateTransformation(source, target).TransformPoint(10, 45)
    assert x == pytest.approx(1113194.9079, abs=0.01)
    assert y == pytest.approx(5621521.4862, abs=0.01)

def test_array():
    pixels = np.arange(12, dtype=np.float32).reshape(3, 4)
    with gdal_array.OpenArray(pixels) as ds:
        np.testing.assert_array_equal(ds.ReadAsArray(), pixels)

def test_bundled_data():
    import osgeo
    root = Path(osgeo.__file__).parent / 'data'
    assert (root / 'gdal/gdalvrt.xsd').is_file()
    assert (root / 'proj/proj.db').is_file()
    assert Path(gdal.GetConfigOption('GDAL_DATA')).resolve() == (root / 'gdal').resolve()
    assert str(root / 'proj') in osr.GetPROJSearchPaths()

def test_explicit_paths_and_escape_hatch(tmp_path):
    script = 'from osgeo import gdal; import os; assert gdal.GetConfigOption("GDAL_DATA") == os.environ["GDAL_DATA"]; assert os.environ["PROJ_DATA"] == "explicit-proj"'
    subprocess.run([sys.executable, '-c', script], env={**os.environ, 'GDAL_DATA': str(tmp_path), 'PROJ_DATA': 'explicit-proj'}, check=True)
    env = {k: v for k, v in os.environ.items() if k not in ('GDAL_DATA','PROJ_DATA','PROJ_LIB')}
    subprocess.run([sys.executable, '-c', 'import osgeo, os; assert "PROJ_DATA" not in os.environ'], env={**env, 'SKIP_GDAL_DATA_CHECK': '1'}, check=True)

def test_vsicurl(tmp_path):
    path = tmp_path / 'remote.tif'
    with gdal.GetDriverByName('GTiff').Create(str(path), 3, 2) as ds:
        ds.GetRasterBand(1).WriteRaster(0, 0, 3, 2, bytes(range(6)))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with gdal.Open(f'/vsicurl/http://127.0.0.1:{server.server_port}/remote.tif') as ds:
            assert ds.ReadRaster() == bytes(range(6))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

def test_netcdf(tmp_path):
    path = str(tmp_path / 'roundtrip.nc')
    with gdal.GetDriverByName('MEM').Create('', 3, 2) as source:
        source.GetRasterBand(1).WriteRaster(0, 0, 3, 2, bytes(range(6)))
        with gdal.GetDriverByName('netCDF').CreateCopy(path, source):
            pass
    with gdal.Open(path) as ds:
        assert ds.ReadRaster() == bytes(range(6))

@pytest.mark.parametrize('driver,suffix', [('PNG','png'),('JPEG','jpg'),('WEBP','webp'),('JP2OpenJPEG','jp2'),('COG','tif')])
def test_raster_codecs(tmp_path, driver, suffix):
    with gdal.GetDriverByName('MEM').Create('', 16, 16, 3) as source:
        for band in range(1, 4):
            source.GetRasterBand(band).Fill(50)
        path = str(tmp_path / ('codec.' + suffix))
        with gdal.GetDriverByName(driver).CreateCopy(path, source):
            pass
        with gdal.Open(path) as ds:
            assert ds.RasterXSize == 16 and ds.RasterCount == 3
            assert ds.ReadRaster()

@pytest.mark.parametrize('driver,suffix', [('GPKG','gpkg'),('SQLite','sqlite'),('GeoJSON','json'),('ESRI Shapefile','shp')])
def test_vector_roundtrip(tmp_path, driver, suffix):
    path = str(tmp_path / ('vector.' + suffix))
    ds = ogr.GetDriverByName(driver).CreateDataSource(path)
    layer = ds.CreateLayer('points', geom_type=ogr.wkbPoint)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(ogr.CreateGeometryFromWkt('POINT (10 45)'))
    assert layer.CreateFeature(feature) == 0
    feature = layer = ds = None
    ds = ogr.Open(path)
    assert ds.GetLayer(0).GetFeatureCount() == 1
    ds = None
