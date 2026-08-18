# TEST SCRIPT TO BE DELETED

import cv2

from tcm_control.devices.camera import Camera
from tcm_control.devices.syringe_pump2 import SyringePump2
from tcm_control.devices.light import LightSwitchController
from tcm_control.film_height import determine_film_height, determine_plate_height

import re
import time
import importlib
from pathlib import Path
import matplotlib.pyplot as plt

tomllib = importlib.import_module("tomllib")
specs_path = Path(__file__).resolve().parent.parent / \
    "config" / "config.toml"

pxm = 0.020562e-3  # m/px

if __name__ == "__main__":

    output_dir = Path(__file__).parent / "Film_Images"
    # light = LightSwitchController()
    # camera = Camera(exposure_us=4000, output_dir=output_dir)

    # # BACKGROUND IMAGE
    # # Turn on the light
    # light.toggle_light()
    # time.sleep(0.1)  # Wait for the light to turn on

    # Capture a snapshot
    # image_path = camera.snapshot()
    # if image_path is not None:
    #     print(f"Snapshot saved: {image_path}")

    #     image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    #     if image is None:
    #         raise RuntimeError(
    #             f"Failed to read captured image from: {image_path}")
    #     image = image[::-1, :]

    #     top_x, top_y, plate_height = determine_plate_height(image)
    #     print(f"Determined plate height: {plate_height:.1f} px")

    #     plt.figure()
    #     plt.imshow(image, cmap='gray', origin='lower')
    #     plt.scatter(top_x, top_y, s=1, color='green')
    #     plt.title(f"Plate Height: {plate_height:.1f} px")
    #     plt.savefig(output_dir / "background.png")
    #     plt.close()
    #     # plt.show()

    # Toggle the light off
    # light.toggle_light()

    # PUMP CONTROL
    specs: dict = {}
    if specs_path.exists():
        specs = tomllib.load(specs_path.open("rb"))

    pump = SyringePump2(specs)

    profile = pump.get_active_profile()
    infuse_step = pump.get_first_action_step("infuse")
    withdraw_step = pump.get_first_action_step("withdraw")

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
