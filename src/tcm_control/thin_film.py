from pathlib import Path

from tcm_control.devices.camera import Camera
from tcm_control.devices.cough_machine import CoughMachine
from tcm_control.devices.syringe_pump2 import SyringePump2
import time


def take_snapshot(camera: Camera, tcm: CoughMachine, brightness: float = 1.0) -> Path:
    # Toggle the light on
    tcm.set_light(1)

    # Take a picture
    image_path = camera.snapshot()
    print(f"Saved image to: {image_path}")

    # Toggle light off
    tcm.set_light(0)
    return image_path


def tube_cleaning(pump: SyringePump2, specs):

    pump = SyringePump2(specs)
    try:
        profile = pump.get_active_profile()
        step = pump.get_first_action_step("clean_tube")
        pump.prepare(profile)

        if step is not None:
            # Make a layer
            pump.infuse(
                volume_ml=step["volume_ml_layer"],
                rate_ml_min=step["rate_ml_min_layer"]
            )

            # Seasaw the fluid through the tubes
            for _ in range(step["repetitions"]):
                pump.withdraw(
                    volume_ml=step["volume_ml_repetition"],
                    rate_ml_min=step["rate_ml_min_repetition"]
                )
                pump.infuse(
                    volume_ml=step["volume_ml_repetition"],
                    rate_ml_min=step["rate_ml_min_repetition"]
                )

        if step is None:
            pump._log_info(
                "SyringePump config has no clean_tube steps")
    except Exception as exc:
        pump._log_error(str(exc))
        raise
    finally:
        pump.stop()


def make_layer(pump: SyringePump2, specs):

    pump = SyringePump2(specs)
    try:
        profile = pump.get_active_profile()
        infuse_step = pump.get_first_action_step("infuse")
        withdraw_step = pump.get_first_action_step("withdraw")
        pump.prepare(profile)

        if infuse_step is not None:
            pump.infuse(
                volume_ml=infuse_step["volume_ml"],
                rate_ml_min=infuse_step["rate_ml_min"]
            )

        time.sleep(5)  # Wait for the pump system to relax

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
