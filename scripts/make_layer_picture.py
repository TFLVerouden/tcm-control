import cv2

from tcm_control.devices.camera import Camera
from tcm_control.devices.syringe_pump2 import SyringePump2
from tcm_control.devices.light import LightSwitchController
from tcm_control.SingleFilmHeight import determine_film_height, determine_plate_height
from tcm_control.devices import CoughMachine

import re
import time
import importlib
from pathlib import Path
import matplotlib.pyplot as plt

tomllib = importlib.import_module("tomllib")
specs_path = Path(__file__).resolve().parent.parent / \
    "config" / "config.toml"

pxm = 0.020562e-3  # m/px


def tube_cleaning(specs_path: Path = specs_path):

    specs: dict = {}
    if specs_path.exists():
        specs = tomllib.load(specs_path.open("rb"))

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


def make_layer(specs_path: Path = specs_path):

    # PUMP CONTROL
    specs: dict = {}
    if specs_path.exists():
        specs = tomllib.load(specs_path.open("rb"))

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


if __name__ == "__main__":

    output_dir = Path(
        r"C:\CoughMachineData\260622_test_film_cough\260622_134021_VierdeLaagje\camera")
    image_path = Path(
        r"C:\CoughMachineData\260622_test_film_cough\260622_134021_VierdeLaagje\camera\capture_20260622_134450.png")
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(
            f"Failed to read captured image from: {image_path}")
    image = image[::-1, :]

    top_x, top_y, plate_height = determine_plate_height(image)
    print(f"Determined plate height: {plate_height:.1f} px")

    plt.figure()
    plt.imshow(image, cmap='gray', origin='lower')
    plt.scatter(top_x, top_y, s=1, color='green')
    plt.title(f"Plate Height: {plate_height:.1f} px")
    plt.savefig(output_dir / "background.png")
    plt.close()
    plt.show()

    # Toggle the light off
    # light.toggle_light()

    # clean the tubes before making the layer
    # tube_cleaning(specs_path)

    # Make the layer
    # make_layer(specs_path)

    # time.sleep(10)  # Wait for the pump system to relax
    # # FILM LAYER PICTURE
    # # Turn on the light
    # light.toggle_light()
    # time.sleep(0.1)  # Wait for the light to turn on

    # try:
    #     light.toggle_light()
    #     # Capture a snapshot
    #     image_path = camera.snapshot()
    #     if image_path is not None:
    #         print(f"Snapshot saved: {image_path}")

    #         image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    #         if image is None:
    #             raise RuntimeError(
    #                 f"Failed to read captured image from: {image_path}")
    #         image = image[::-1, :]
    #         rim_x, rim_y, film_height = determine_film_height(
    #             image, plate_height)
    #         print(f"Determined film height: {film_height:.2f} px")

    #         plt.figure()
    #         plt.imshow(image, cmap='gray', origin='lower')
    #         plt.scatter(rim_x, rim_y, s=1, color='blue')
    #         plt.scatter(top_x, top_y, s=1, color='green')
    #         plt.title(f"Film Height: {film_height * pxm * 1e3:.4f} mm")

    #         timestamp = time.strftime("%Y%m%d_%H%M%S")
    #         plt.savefig(output_dir / f"film_height_{timestamp}.png")
    #         plt.close()

    #         print(f"Film height in mm: {film_height * pxm * 1e3:.4f} mm")
    #         # plt.show()

    #     # Toggle the light off
    #     light.toggle_light()
    # finally:
    #     # Close the devices
    #     camera.close()
    #     light.close()
