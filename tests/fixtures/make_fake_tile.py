"""Write tiny VNP46A2 / VNP46A1 HDF5 files with the real layer paths, dtypes, fill attributes and file names."""

from pathlib import Path

import h5py
import numpy as np

GROUP = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields"


def _put(group: h5py.Group, name: str, data: np.ndarray, fill, **attrs) -> None:
    ds = group.create_dataset(name, data=data, fillvalue=0)
    ds.attrs["_FillValue"] = np.array([fill], dtype=data.dtype)  # stored as a 1-element array, as in the real files
    for key, value in attrs.items():
        ds.attrs[key] = np.array([value], dtype=np.float32)


def write_a2(folder: Path, name: str, radiance, quality=None, cloud=None, snow=None, gap_filled=None,
             lunar=None) -> Path:
    radiance = np.asarray(radiance, dtype=np.float32)
    shape = radiance.shape
    quality = np.zeros(shape, np.uint8) if quality is None else np.asarray(quality, np.uint8)
    cloud = np.full(shape, 50, np.uint16) if cloud is None else np.asarray(cloud, np.uint16)  # 50: bits 6-7 = 00
    snow = np.zeros(shape, np.uint8) if snow is None else np.asarray(snow, np.uint8)
    gap_filled = radiance if gap_filled is None else np.asarray(gap_filled, np.float32)
    lunar = np.full(shape, 20, np.uint16) if lunar is None else np.asarray(lunar, np.uint16)
    path = Path(folder) / name
    with h5py.File(path, "w") as h5:
        g = h5.create_group(GROUP)
        _put(g, "DNB_BRDF-Corrected_NTL", radiance, np.float32(-999.9), scale_factor=1.0, offset=0.0)
        _put(g, "Gap_Filled_DNB_BRDF-Corrected_NTL", gap_filled, np.float32(-999.9), scale_factor=1.0, offset=0.0)
        _put(g, "Mandatory_Quality_Flag", quality, np.uint8(255))
        _put(g, "QF_Cloud_Mask", cloud, np.uint16(65535))
        _put(g, "Snow_Flag", snow, np.uint8(255))
        _put(g, "DNB_Lunar_Irradiance", lunar, np.uint16(65535), scale_factor=0.1, offset=0.0)
    return path


def write_a1(folder: Path, name: str, utc_time, sensor_zenith=None) -> Path:
    utc_time = np.asarray(utc_time, dtype=np.float32)
    zenith = np.full(utc_time.shape, 2000, np.int16) if sensor_zenith is None else np.asarray(sensor_zenith, np.int16)
    path = Path(folder) / name
    with h5py.File(path, "w") as h5:
        g = h5.create_group(GROUP)
        _put(g, "UTC_Time", utc_time, np.float32(-999.9), scale_factor=1.0, add_offset=0.0)
        _put(g, "Sensor_Zenith", zenith, np.int16(-32768), scale_factor=0.01, add_offset=0.0)
    return path
