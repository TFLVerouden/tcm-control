from tcm_control.devices.syringe_pump2 import get_active_profile, get_first_action_step
from tcm_control.devices.camera import Camera
from tcm_control.devices.syringe_pump2 import SyringePump2
from tcm_control.devices.light import LightSwitchController
import re
import time
import importlib
from pathlib import Path

tomllib = importlib.import_module("tomllib")
specs_path = Path(__file__).resolve().parent.parent / \
    "config" / "config.toml"

if __name__ == "__main__":

    specs: dict = {}
    if specs_path.exists():
        specs = tomllib.load(specs_path.open("rb"))
    profile = get_active_profile(specs)
    infuse_step = get_first_action_step(specs, "infuse")
    withdraw_step = get_first_action_step(specs, "withdraw")

    pump = SyringePump2(specs)
    try:
        pump.prepare(profile)

        if infuse_step is not None:
            pump.infuse(
                volume_ml=infuse_step["volume_ml"],
                rate_ml_min=infuse_step["rate_ml_min"]
            )

        if withdraw_step is not None:
            pump.withdraw(
                volume_ml=withdraw_step["volume_ml"],
                rate_ml_min=withdraw_step["rate_ml_min"]
            )

        if infuse_step is None and withdraw_step is None:
            pump._log_info(
                "SyringePump config has no infuse/withdraw steps")
    except Exception as exc:
        pump._log_error(str(exc))
        raise
    finally:
        pump.stop()

    output_dir = Path(__file__).parent / "Film_Images"
    light = LightSwitchController()
    camera = Camera(exposure_us=4000, output_dir=output_dir)

    try:
        # Turn on the light
        light.connect()
        light.toggle_light()

        # Capture a snapshot
        saved = camera.snapshot()
        print(f"Snapshot saved: {saved}")

        # Toggle the light off
        light.toggle_light()
    finally:
        # Close the devices
        camera.close()
        light.close()
