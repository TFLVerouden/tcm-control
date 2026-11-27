from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import numpy as np
import tifffile
from ximea import xiapi
from tcm_control.devices import CoughMachine
from tcm_utils.file_dialogs import ask_directory
from tcm_utils.time_utils import timestamp_str


# TODO: Update this value after the next camera calibration.
DEFAULT_SCALE_MM_PER_PX = 0.016089430575096462


def validate_roi(roi: object) -> tuple[int, int, int, int]:
    """Validate an ROI in (y_start, y_end, x_start, x_end) order."""
    if (not isinstance(roi, (tuple, list)) or len(roi) != 4
            or any(not isinstance(value, int) or isinstance(value, bool) for value in roi)):
        raise ValueError(
            "ROI must contain four integers (y_start, y_end, x_start, x_end).")
    return roi[0], roi[1], roi[2], roi[3]


def validate_flip(flip: object) -> str | None:
    if flip is None:
        return None
    if isinstance(flip, str) and flip in ("vertical", "horizontal", "both"):
        return flip
    raise ValueError("flip must be 'vertical', 'horizontal', 'both', or None")


def validate_gain(gain_db: object) -> float | None:
    if gain_db is None:
        return None
    if isinstance(gain_db, bool) or not isinstance(gain_db, (int, float)):
        raise ValueError("Camera gain must be a finite number in dB.")
    gain = float(gain_db)
    if not math.isfinite(gain):
        raise ValueError("Camera gain must be a finite number in dB.")
    return gain


class Camera:
    """Class-based snapshot camera interface."""

    MIN_EXPOSURE_US = 0
    MAX_EXPOSURE_US = 100000
    MAX_GAIN_DB = 20.0

    def __init__(self, exposure_us: int = 1000, output_dir: Optional[str | Path] = None,
                 roi: tuple[int, int, int, int] = (0, 0, 0, 0),
                 flip: str | None = None, gain_db: float | None = None):
        """"Initialize the Camera instance.

        Args:
            exposure_us: Exposure time in microseconds.
            output_dir: Directory to save camera snapshots.
            roi: Region of interest as (y_start, y_end, x_start, x_end).
                If y_end or x_end is negative, they are interpreted as an offset
                from the end of the image. If y_end or x_end is zero, it is
                interpreted as the full extent in that direction.
            flip: Image flip direction.
            gain_db: Camera gain in dB, or None to leave it unchanged.
        """
        self.roi = validate_roi(roi)
        self.flip = validate_flip(flip)
        self._gain_db = validate_gain(gain_db)
        self.output_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else ask_directory(key="tcm_camera_output_dir", title="Select output directory for camera snapshot")
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._cam = xiapi.Camera()
        self._img = xiapi.Image()
        self._is_open = False
        self._is_acquiring = False

        self._exposure_us = self._clamp_exposure(exposure_us)
        self._gain_db = self._clamp_gain(
            gain_db) if gain_db is not None else None

    def metadata(self) -> dict:
        """Return camera limits used to clamp configured exposure and gain."""
        return {
            "limits": {
                "min_exposure_us": self.MIN_EXPOSURE_US,
                "max_exposure_us": self.MAX_EXPOSURE_US,
                "max_gain_db": self.MAX_GAIN_DB,
            },
        }

    @staticmethod
    def _clamp_exposure(exposure_us: int) -> int:
        if exposure_us < Camera.MIN_EXPOSURE_US or exposure_us > Camera.MAX_EXPOSURE_US:
            print(
                f"Warning: Exposure {exposure_us} us is out of bounds. Clamping to valid range.")
        return max(Camera.MIN_EXPOSURE_US, min(Camera.MAX_EXPOSURE_US, int(exposure_us)))

    @staticmethod
    def _clamp_gain(gain_db: float) -> float:
        if gain_db < 0.0 or gain_db > Camera.MAX_GAIN_DB:
            print(
                f"Warning: Gain {gain_db} dB is out of bounds. Clamping to valid range.")
        return max(0.0, min(Camera.MAX_GAIN_DB, float(gain_db)))

    def open(self) -> None:
        if self._is_open:
            return
        self._cam.open_device()
        self._is_open = True
        name = self._cam.get_device_name().decode()
        serial = self._cam.get_device_sn().decode()
        print(f"Connected to camera {name} (SN {serial})")
        try:
            self.set_exposure(self._exposure_us)
            if self._gain_db is not None:
                self.set_gain(self._gain_db)
        except Exception:
            self.close()
            raise

    def start(self) -> None:
        if not self._is_open:
            self.open()
        if self._is_acquiring:
            return
        self._cam.start_acquisition()
        self._is_acquiring = True

    def set_exposure(self, exposure_us: int) -> None:
        self._exposure_us = self._clamp_exposure(exposure_us)
        if self._is_open:
            self._cam.set_exposure(self._exposure_us)

    @property
    def exposure_us(self) -> int:
        return self._exposure_us

    def set_gain(self, gain_db: float) -> None:
        gain = validate_gain(gain_db)
        if gain is None:
            raise ValueError("Camera gain must be a finite number in dB.")
        if self._is_open:
            self._cam.set_gain(gain)
        self._gain_db = gain

    @property
    def gain_db(self) -> float | None:
        return self._gain_db

    def capture_frame(self) -> np.ndarray:
        """Capture a frame with the configured flip and ROI."""
        self.start()

        self._cam.get_image(self._img)
        frame = self._img.get_image_data_numpy()

        if frame is None:
            raise RuntimeError("Camera returned an empty frame.")

        # Flip image
        if self.flip == "vertical":
            frame = np.flip(frame, axis=0)
        elif self.flip == "horizontal":
            frame = np.flip(frame, axis=1)
        elif self.flip == "both":
            frame = np.flip(frame, axis=(0, 1))

        # Crop image to ROI
        height, width = frame.shape[:2]
        y_start, y_end, x_start, x_end = self.roi
        y_start = height + y_start if y_start < 0 else y_start
        x_start = width + x_start if x_start < 0 else x_start
        y_end = height if y_end == 0 else height + y_end if y_end < 0 else y_end
        x_end = width if x_end == 0 else width + x_end if x_end < 0 else x_end
        if not (0 <= y_start < y_end <= height and 0 <= x_start < x_end <= width):
            raise ValueError(
                f"ROI {self.roi} is empty or out of bounds for image size {height}x{width}.")
        return frame[y_start:y_end, x_start:x_end].copy()

    def snapshot(self, output_path: Optional[str | Path] = None, filename: Optional[str] = None) -> Path:
        """Capture one frame as TIFF, returning the saved path."""
        if output_path is not None and Path(output_path).suffix.lower() not in (".tif", ".tiff"):
            raise ValueError(
                "Camera output_path must have a .tif or .tiff extension.")
        frame = self.capture_frame()

        # Save image
        if output_path is None:
            timestamp = timestamp_str()
            name = f"{timestamp}_{filename}" if filename else timestamp
            save_path = self.output_dir / f"{name}.tif"
        else:
            save_path = Path(output_path)
            if not save_path.is_absolute():
                save_path = self.output_dir / save_path

        save_path.parent.mkdir(parents=True, exist_ok=True)

        tifffile.imwrite(save_path, frame)

        return save_path

    def __call__(self, output_path: Optional[str | Path] = None) -> Path:
        """Allow instance(...) syntax to take a snapshot."""
        return self.snapshot(output_path=output_path)

    def close(self) -> None:
        if self._is_acquiring:
            self._cam.stop_acquisition()
            self._is_acquiring = False
        if self._is_open:
            self._cam.close_device()
            self._is_open = False

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


if __name__ == "__main__":
    camera = Camera(exposure_us=20000, flip="vertical",
                    output_dir=r"C:\Users\local2\Documents\GitHub\twente-cough-machine\control\src\tcm_control\devices\calibration")
    tcm = CoughMachine()

    try:
        tcm.set_light(1.0)
        saved = camera.snapshot(filename="calibration_500um-grid")
        print(f"Snapshot saved: {saved}")
        tcm.set_light(0.0)
    finally:
        camera.close()
        tcm.close()
