"""Small runtime contract for published GDAL wheels."""

from pathlib import Path
import sys

import numpy as np
import pytest
from osgeo import gdal, gdal_array, ogr, osr


gdal.UseExceptions()
DATA = Path(__file__).parent / "data"

# Change to True when Windows HDF4 becomes part of the wheel contract.
HDF4_REQUIRED = sys.platform != "win32"


def test_required_drivers() -> None:
    required = [
        "GTiff",
        "VRT",
        "MEM",
        "HDF5",
        "HDF5Image",
        "netCDF",
        "GPKG",
        "GeoJSON",
    ]
    if HDF4_REQUIRED:
        required += ["HDF4", "HDF4Image"]

    missing = [name for name in required if gdal.GetDriverByName(name) is None]
    assert not missing, f"Missing GDAL drivers: {missing}"


def test_bundled_gdal_and_proj_data() -> None:
    import osgeo

    root = Path(osgeo.__file__).resolve().parent / "data"
    gdal_data = root / "gdal"
    proj_data = root / "proj"

    assert (gdal_data / "gdalvrt.xsd").is_file()
    assert (proj_data / "proj.db").is_file()
    assert Path(gdal.GetConfigOption("GDAL_DATA")).resolve() == gdal_data.resolve()
    assert proj_data.resolve() in {Path(p).resolve() for p in osr.GetPROJSearchPaths()}


def test_proj_transform() -> None:
    source = osr.SpatialReference()
    target = osr.SpatialReference()
    assert source.ImportFromEPSG(4326) == 0
    assert target.ImportFromEPSG(3857) == 0

    source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    x, y, _ = osr.CoordinateTransformation(source, target).TransformPoint(10, 45)

    assert x == pytest.approx(1113194.9079, abs=0.01)
    assert y == pytest.approx(5621521.4862, abs=0.01)


def test_numpy_binding() -> None:
    values = np.arange(12, dtype=np.float32).reshape(3, 4)
    with gdal_array.OpenArray(values) as dataset:
        np.testing.assert_array_equal(dataset.ReadAsArray(), values)


def test_zstd_geotiff(tmp_path: Path) -> None:
    path = tmp_path / "zstd.tif"
    values = np.arange(256, dtype=np.uint16).reshape(16, 16)

    with gdal.GetDriverByName("GTiff").Create(
        str(path),
        16,
        16,
        1,
        gdal.GDT_UInt16,
        ["TILED=YES", "COMPRESS=ZSTD"],
    ) as dataset:
        dataset.GetRasterBand(1).WriteArray(values)

    with gdal.Open(str(path)) as dataset:
        assert dataset.GetMetadata("IMAGE_STRUCTURE").get("COMPRESSION") == "ZSTD"
        np.testing.assert_array_equal(dataset.ReadAsArray(), values)


@pytest.mark.parametrize("filename", ["tiny_hdf4.hdf", "tiny_hdf5.h5"])
def test_hdf_fapar_fixture(filename: str) -> None:
    if filename.endswith(".hdf") and not HDF4_REQUIRED:
        pytest.skip("HDF4 is not part of the current Windows wheel contract")

    with gdal.Open(str(DATA / filename)) as container:
        target = next(
            uri
            for uri, description in container.GetSubDatasets()
            if "fapar" in (uri + description).lower()
        )

    with gdal.Open(target) as raster:
        assert (raster.RasterXSize, raster.RasterYSize) == (3, 2)
        assert raster.ReadRaster() == bytes([0, 20, 40, 60, 80, 100])


def test_netcdf_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "roundtrip.nc"

    with gdal.GetDriverByName("MEM").Create("", 3, 2) as source:
        source.GetRasterBand(1).WriteRaster(0, 0, 3, 2, bytes(range(6)))
        with gdal.GetDriverByName("netCDF").CreateCopy(str(path), source):
            pass

    with gdal.Open(str(path)) as dataset:
        assert dataset.ReadRaster() == bytes(range(6))


def test_geopackage_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "point.gpkg"

    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    layer = datasource.CreateLayer("points", geom_type=ogr.wkbPoint)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(ogr.CreateGeometryFromWkt("POINT (10 45)"))
    assert layer.CreateFeature(feature) == 0

    feature = None
    layer = None
    datasource = None

    datasource = ogr.Open(str(path))
    assert datasource is not None
    assert datasource.GetLayer(0).GetFeatureCount() == 1
