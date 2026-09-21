"""Thin film layer creation and tube cleaning protocol."""

from pathlib import Path
import time
import tomllib

from tcm_control.devices.camera import Camera
from tcm_control.devices.cough_machine import CoughMachine
from tcm_control.devices.syringe_pump2 import SyringePump2


def take_snapshot(
    camera: Camera,
    tcm: CoughMachine,
    brightness: float = 1.0,
) -> Path:
    """Capture a camera snapshot with lighting control.

    Temporarily enables lighting, takes a snapshot, then disables lighting.

    Args:
        camera: Camera device to use for snapshot.
        tcm: Cough machine instance for light control.
        brightness: Brightness level (default: 1.0). Currently unused.

    Returns:
        Path to the saved image file.
    """
    # Enable lighting for image capture
    tcm.set_light(brightness)

    # Capture image
    image_path = camera.snapshot()
    print(f"Saved image to: {image_path}")

    # Disable lighting
    tcm.set_light(0)
    return image_path


if __name__ == "__main__":

    specs_path = Path("src/tcm_control/config/config_layer.toml")
    config: dict = {}
    if specs_path.exists():
        config = tomllib.load(specs_path.open("rb"))

    syringe_inputs = config["devices"]["pump"]["syringe"]
    clean_tube = config["devices"]["pump"]["clean_tube"]

    pump = SyringePump2(syringe_inputs["syringe_vendor_code"],
                        syringe_inputs["syringe_volume_mL"],
                        syringe_inputs["syringe_diameter_mm"],
                        syringe_inputs["syringe_gang"],
                        syringe_inputs["syringe_force_percent"])

    pump.clean_tubes(volume_ml_layer=clean_tube["volume_ml_layer"],
                     rate_ml_min_layer=clean_tube["rate_ml_min_layer"],
                     volume_ml_repetition=clean_tube["volume_ml_repetition"],
                     rate_ml_min_repetition=clean_tube["rate_ml_min_repetition"],
                     repetitions=clean_tube["repetitions"])

    # Clean channel
    tcm = CoughMachine()
    tcm.clean(clean_pressure_bar=5, valve_open_duration_s=1, cycle_count=1)
