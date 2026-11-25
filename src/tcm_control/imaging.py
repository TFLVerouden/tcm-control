"""Camera and light control."""

from pathlib import Path
from contextlib import contextmanager
import time
import tomllib

import cv2
import numpy as np

from tcm_control.devices.camera import Camera
from tcm_control.devices.cough_machine import CoughMachine
from tcm_control.devices.syringe_pump import SyringePump
from tcm_control.processing.determine_film_height import measure_film_frame


def take_snapshot(
    camera: Camera,
    tcm: CoughMachine,
    filename: str | None = None,
    brightness: float = 1.0,
) -> Path:
    """Capture a camera snapshot with lighting control.

    Temporarily enables lighting, takes a snapshot, then disables lighting.

    Args:
        camera: Camera device to use for snapshot.
        tcm: Cough machine instance for light control.
        filename: Optional filename for the saved image.
        brightness: Brightness level (default: 1.0).

    Returns:
        Path to the saved image file.
    """
    # Enable lighting for image capture
    tcm.set_light(brightness)

    try:
        image_path = camera.snapshot(filename=filename)
        print(f"Saved image to: {image_path}")
    finally:
        tcm.set_light(0)
    return image_path


class LayerPreview:
    """Local, unsaved preview of the layer and its provisional measurements."""

    WINDOW = "Layer formation - provisional measurements (q to close)"

    def __init__(self, camera: Camera, tcm: CoughMachine,
                 plate_measurement: tuple[float, float, np.ndarray, np.ndarray, tuple[int, int]],
                 scale_mm_per_px: float | None):
        self.camera = camera
        self.tcm = tcm
        self.plate_measurement = plate_measurement
        self.scale_mm_per_px = scale_mm_per_px
        self.active = False

    def open(self) -> None:
        cv2.namedWindow(self.WINDOW, cv2.WINDOW_NORMAL)
        self.active = True
        self.tcm.set_light(1.0)

    def update(self) -> None:
        if not self.active:
            return
        try:
            visible = cv2.getWindowProperty(
                self.WINDOW, cv2.WND_PROP_VISIBLE) >= 1
        except cv2.error as exc:
            print(f"Preview window is unavailable: {exc}")
            visible = False
        if not visible:
            self.close()
            return
        frame = self.camera.capture_frame()
        if frame.dtype == np.uint16:
            frame = (frame >> 8).astype(np.uint8)
        if frame.dtype != np.uint8 or frame.ndim not in (2, 3):
            raise ValueError(
                f"Unsupported preview frame: {frame.dtype}, shape {frame.shape}")
        if frame.ndim == 3 and frame.shape[2] == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        elif frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        elif frame.ndim == 3:
            raise ValueError(f"Unsupported preview frame shape: {frame.shape}")
        try:
            _, display = measure_film_frame(
                frame, self.plate_measurement, self.scale_mm_per_px)
        except ValueError as exc:
            display = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            cv2.putText(display, f"Measurement unavailable: {exc}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
        cv2.imshow(self.WINDOW, display)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            self.close()

    def close(self) -> None:
        if self.active:
            self.active = False
            try:
                try:
                    cv2.destroyWindow(self.WINDOW)
                except cv2.error as exc:
                    print(f"Warning: Could not close preview window: {exc}")
            finally:
                self.tcm.set_light(0)


@contextmanager
def layer_preview(camera: Camera, tcm: CoughMachine,
                  plate_measurement: tuple[float, float, np.ndarray, np.ndarray, tuple[int, int]],
                  scale_mm_per_px: float | None):
    preview = LayerPreview(camera, tcm, plate_measurement, scale_mm_per_px)
    try:
        preview.open()
        yield preview
    finally:
        preview.close()


def wait_with_preview(wait_s: float, preview: LayerPreview) -> None:
    """Continue refreshing the preview during the final settling period."""
    print("Waiting for layer to settle...")
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        preview.update()
        remaining = end - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.1, remaining))


if __name__ == "__main__":

    output_path = Path(
        r"C:\Users\local2\Documents\GitHub\twente-cough-machine\control\temp")

    take_snapshot(
        camera=Camera(exposure_us=1000, flip="vertical",
                      output_dir=output_path,
                      roi=(512, 0, 0, 0)),
        # camera=Camera(exposure_us=12000, flip="vertical", gain_db=0.0,
        #   output_dir=output_path),
        tcm=CoughMachine(),
        filename="withdraw_40s",
        brightness=1.0
    )

    # specs_path = Path("src/tcm_control/config/config_layer.toml")
    # config: dict = {}
    # if specs_path.exists():
    #     config = tomllib.load(specs_path.open("rb"))

    # syringe_inputs = config["devices"]["syringe_pump"]
    # layer = config["film"]["layer"]
    # clean_tube = config["film"]["clean_tube"]

    # pump = SyringePump(syringe_inputs["syringe_vendor_code"],
    #                    syringe_inputs["syringe_volume_mL"],
    #                    syringe_inputs["syringe_diameter_mm"],
    #                    syringe_inputs["syringe_gang"],
    #                    syringe_inputs["syringe_force_percent"])

    # # pump.make_layer(infuse_volume_ml=layer["infuse_volume_ml"],
    # #                 infuse_rate_ml_min=layer["infuse_rate_ml_min"],
    # #                 withdraw_volume_ml=layer["withdraw_volume_ml"],
    # #                 withdraw_rate_ml_min=layer["withdraw_rate_ml_min"],
    # #                 settling_time_s=layer["film_settling_time_s"])

    # pump.clean_tubes(volume_ml_layer=clean_tube["volume_ml_layer"],
    #                  rate_ml_min_layer=clean_tube["rate_ml_min_layer"],
    #                  volume_ml_repetition=clean_tube["volume_ml_repetition"],
    #                  rate_ml_min_repetition=clean_tube["rate_ml_min_repetition"],
    #                  repetitions=clean_tube["repetitions"])

    # # Clean channel
    # # tcm = CoughMachine()
    # # tcm.clean(clean_pressure_bar=5, valve_open_duration_s=1, cycle_count=1)

    # # camera = Camera()
    # # tcm = CoughMachine()

    # # take_snapshot(camera, tcm, filename="test_snapshot.png", brightness=1.0)
