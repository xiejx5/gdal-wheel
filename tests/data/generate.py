"""Recreate tiny synthetic fixtures: pip install numpy h5py pyhdf.

Two scientific datasets force the GDAL container/subdataset read path.
These are synthetic HDF4 SDS / HDF5 fixtures, not MODIS HDF-EOS products.
"""

from pathlib import Path
import numpy as np
import h5py
from pyhdf.SD import SD, SDC

root = Path(__file__).parent
pixels = np.array([[0, 20, 40], [60, 80, 100]], dtype=np.uint8)
with h5py.File(root / "tiny_hdf5.h5", "w") as file:
    file.create_dataset("fapar", data=pixels)
    file.create_dataset("quality", data=np.zeros_like(pixels))
file = SD(str(root / "tiny_hdf4.hdf"), SDC.WRITE | SDC.CREATE | SDC.TRUNC)
for name, data in [("fapar", pixels), ("quality", np.zeros_like(pixels))]:
    dataset = file.create(name, SDC.UINT8, pixels.shape)
    dataset[:] = data
    dataset.endaccess()
file.end()
