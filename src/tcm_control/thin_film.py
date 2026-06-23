"""Thin film layer creation and tube cleaning protocol."""

from pathlib import Path
import time

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


def tube_cleaning(pump: SyringePump2) -> None:
    """Perform tube cleaning routine on the syringe pump.

    Executes a cleaning sequence that infuses fluid and seesaws it through
    the tubing to clear any residual material. Cleans up resources via finally
    block even if an error occurs.

    Args:
        pump: Syringe pump instance to perform cleaning on.

    Raises:
        Exception: Any exception from the pump operations is re-raised after cleanup.
    """
    try:
        # Retrieve cleaning configuration
        profile = pump.get_active_profile()
        step = pump.get_first_action_step("clean_tube")
        pump.prepare(profile)

        if step is not None:
            # Initial infusion to create fluid layer
            pump.infuse(
                volume_ml=step["volume_ml_layer"],
                rate_ml_min=step["rate_ml_min_layer"]
            )

            # Seesaw fluid back and forth through tubes to clean them
            for _ in range(step["repetitions"]):
                pump.withdraw(
                    volume_ml=step["volume_ml_repetition"],
                    rate_ml_min=step["rate_ml_min_repetition"]
                )
                pump.infuse(
                    volume_ml=step["volume_ml_repetition"],
                    rate_ml_min=step["rate_ml_min_repetition"]
                )
        else:
            pump._log_info("SyringePump config has no clean_tube steps")

    except Exception as exc:
        pump._log_error(str(exc))
        raise
    finally:
        # Always stop the pump after operation
        pump.stop()


def make_layer(pump: SyringePump2) -> None:
    """Create a thin film layer using the syringe pump.

    Executes a layer creation sequence: infuse fluid to form a layer,
    wait for the system to relax, then partially withdraw. Cleans up resources
    via finally block even if an error occurs.

    Args:
        pump: Syringe pump instance to use for layer creation.

    Raises:
        Exception: Any exception from the pump operations is re-raised after cleanup.
    """
    try:
        # Retrieve layer creation configuration
        profile = pump.get_active_profile()
        infuse_action = pump.get_first_action_step("infuse")
        withdraw_action = pump.get_first_action_step("withdraw")
        pump.prepare(profile)

        # Infuse fluid to create the layer
        if infuse_action is not None:
            pump.infuse(
                volume_ml=infuse_action["volume_ml"],
                rate_ml_min=infuse_action["rate_ml_min"]
            )

        # Allow the pump system and fluid to relax
        time.sleep(5)

        # Partially withdraw to stabilize the layer
        if withdraw_action is not None:
            pump.withdraw(
                volume_ml=withdraw_action["volume_ml"],
                rate_ml_min=withdraw_action["rate_ml_min"]
            )
        else:
            pump._log_info(
                "SyringePump config has no infuse/withdraw steps"
            )

    except Exception as exc:
        pump._log_error(str(exc))
        raise
    finally:
        # Always stop the pump after operation
        pump.stop()
