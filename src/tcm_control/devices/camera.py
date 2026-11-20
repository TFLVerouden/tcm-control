from __future__ import annotations

from pathlib import Path
from typing import Optional
import time

import cv2
from ximea import xiapi
from tcm_control.devices import CoughMachine
from tcm_utils.file_dialogs import ask_directory


def validate_roi(roi: object) -> tuple[int, int, int, int]:
    """Validate an ROI in (y_start, y_end, x_start, x_end) order."""
    if (not isinstance(roi, (tuple, list)) or len(roi) != 4
            or any(not isinstance(value, int) or isinstance(value, bool) for value in roi)):
        raise ValueError("ROI must contain four integers (y_start, y_end, x_start, x_end).")
    return roi[0], roi[1], roi[2], roi[3]


class Camera:
    """Class-based snapshot camera interface."""

    MIN_EXPOSURE_US = 0
    MAX_EXPOSURE_US = 10000

    def __init__(self, exposure_us: int = 1000, output_dir: Optional[str | Path] = None,
                 roi: tuple[int, int, int, int] = (0, 0, 0, 0)):

        self.roi = validate_roi(roi)
        self.output_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else ask_directory(key="tcm_camera_output_dir", title="Select output directory for camera snapshot")
        )
        if self.output_dir is None:
            raise RuntimeError(
                "No output directory selected for camera snapshot.")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._cam = xiapi.Camera()
        self._img = xiapi.Image()
        self._is_open = False
        self._is_acquiring = False

        self._exposure_us = self._clamp_exposure(exposure_us)

    @staticmethod
    def _clamp_exposure(exposure_us: int) -> int:
        return max(Camera.MIN_EXPOSURE_US, min(Camera.MAX_EXPOSURE_US, int(exposure_us)))

    def open(self) -> None:
        if self._is_open:
            return
        self._cam.open_device()
        self._is_open = True
        name = self._cam.get_device_name().decode()
        serial = self._cam.get_device_sn().decode()
        print(f"Connected to camera {name} (SN {serial})")
        self.set_exposure(self._exposure_us)

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

    def snapshot(self, output_path: Optional[str | Path] = None, filename: Optional[str] = None) -> Path:
        """Capture one frame and save it to disk, returning the saved path."""
        self.start()

        self._cam.get_image(self._img)
        frame = self._img.get_image_data_numpy()

        if frame is None:
            raise RuntimeError("Camera returned an empty frame.")

        height, width = frame.shape[:2]
        y_start, y_end, x_start, x_end = self.roi
        y_start = height + y_start if y_start < 0 else y_start
        x_start = width + x_start if x_start < 0 else x_start
        y_end = height if y_end == 0 else height + y_end if y_end < 0 else y_end
        x_end = width if x_end == 0 else width + x_end if x_end < 0 else x_end
        if not (0 <= y_start < y_end <= height and 0 <= x_start < x_end <= width):
            raise ValueError(f"ROI {self.roi} is empty or out of bounds for image size {height}x{width}.")
        frame = frame[y_start:y_end, x_start:x_end]

        if output_path is None:
            # Use timestamped filename containing only the time
            timestamp = time.strftime("%H%M%S")
            save_path = self.output_dir / f"{filename}_{timestamp}.png"
        else:
            save_path = Path(output_path)
            if not save_path.is_absolute():
                save_path = self.output_dir / save_path

        save_path.parent.mkdir(parents=True, exist_ok=True)

        if not cv2.imwrite(str(save_path), frame):
            raise RuntimeError(f"Failed to save image to: {save_path}")

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
    camera = Camera(exposure_us=10000)
    tcm = CoughMachine()

    try:
        tcm.set_light(1.0)
        saved = camera.snapshot()
        print(f"Snapshot saved: {saved}")
        tcm.set_light(0.0)
    finally:
        camera.close()
        tcm.close()
