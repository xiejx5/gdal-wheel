"""Verify GDAL, Rasterio, and Fiona coexist in either import order."""

import subprocess
import sys


CHECKS = {
    "osgeo": (
        "from osgeo import gdal,osr; "
        "s=osr.SpatialReference(); assert s.ImportFromEPSG(4326)==0; "
        "assert gdal.GetDriverByName('GTiff')"
    ),
    "rasterio": (
        "import rasterio; from rasterio.warp import transform; "
        "x,y=transform('EPSG:4326','EPSG:3857',[10],[45]); "
        "assert x[0] > 1e6 and y[0] > 5e6"
    ),
    "fiona": (
        "import fiona; from fiona.transform import transform; "
        "x,y=transform('EPSG:4326','EPSG:3857',[10],[45]); "
        "assert x[0] > 1e6 and y[0] > 5e6"
    ),
}


for other in ("rasterio", "fiona"):
    for order in (("osgeo", other), (other, "osgeo")):
        print("Checking:", " -> ".join(order), flush=True)
        subprocess.run(
            [sys.executable, "-c", "; ".join(CHECKS[name] for name in order)],
            check=True,
        )
