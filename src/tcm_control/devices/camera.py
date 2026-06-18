from __future__ import annotations

from pathlib import Path
from typing import Optional
import time

import cv2
from ximea import xiapi
from tcm_control.devices.light import LightSwitchController


class Camera:
    """Class-based snapshot camera interface."""

    MIN_EXPOSURE_US = 0
    MAX_EXPOSURE_US = 5000

    def __init__(self, exposure_us: int = 1000, output_dir: Optional[str | Path] = None):
        self.script_dir = Path(__file__).parent.resolve()
        self.output_dir = Path(
            output_dir) if output_dir is not None else self.script_dir
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

    def snapshot(self, output_path: Optional[str | Path] = None) -> Path:
        """Capture one frame and save it to disk, returning the saved path."""
        self.start()

        self._cam.get_image(self._img)
        frame = self._img.get_image_data_numpy()

        if frame is None:
            raise RuntimeError("Camera returned an empty frame.")

        if output_path is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            save_path = self.output_dir / f"capture_{timestamp}.png"
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
    camera = Camera(exposure_us=4000)
    light = LightSwitchController()

    try:
        light.toggle_light()
        saved = camera.snapshot()
        print(f"Snapshot saved: {saved}")
        light.toggle_light()
    finally:
        camera.close()
        light.close()
