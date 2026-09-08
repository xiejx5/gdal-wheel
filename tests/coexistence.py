"""Fresh processes for each import order; exercise each package's own GDAL/PROJ."""

import subprocess
import sys

checks = {
    "osgeo": "from osgeo import gdal, osr; s=osr.SpatialReference(); assert s.ImportFromEPSG(4326)==0; assert gdal.GetDriverByName('GTiff')",
    "rasterio": "import rasterio; from rasterio.warp import transform; assert transform('EPSG:4326', 'EPSG:3857', [10], [45])[0][0]>1e6",
    "fiona": "import fiona; from fiona.transform import transform; assert transform('EPSG:4326', 'EPSG:3857', [10], [45])[0][0]>1e6",
}
for other in ("rasterio", "fiona"):
    for order in (("osgeo", other), (other, "osgeo")):
        subprocess.run(
            [sys.executable, "-c", "; ".join(checks[name] for name in order + order)],
            check=True,
        )
