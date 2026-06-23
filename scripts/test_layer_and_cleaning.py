# TEST SCRIPT TO BE DELETED

from tcm_control.devices import CoughMachine
from tcm_control.interrupt_handling import set_active_tcm

from tcm_control.devices.camera import Camera
from tcm_control.devices.syringe_pump2 import SyringePump2
from tcm_control.devices.light import LightSwitchController
from tcm_control.film_height import determine_film_height, determine_plate_height
from scripts.make_layer_picture import tube_cleaning, make_layer

import time
import importlib
from pathlib import Path
import matplotlib.pyplot as plt

output_dir = Path("scripts/test_images")
specs_path = Path("src/tcm_control/config/config.toml")

# Create a coughmachine
tcm = CoughMachine(debug=False)

# Register device so interrupt cleanup can call quit() on it
set_active_tcm(tcm)

# Create a camera
camera = Camera(exposure_us=5000, output_dir=output_dir)


def imager():
    # Toggle the light on
    tcm.set_light(1)

    # Take a picture
    image_path = camera.snapshot()
    print(f"Saved image to: {image_path}")

    # Toggle light off
    tcm.set_light(0)


# # Take a before picture
# imager()

# Rinse the tubes
tube_cleaning()

# # Clean the channel
# PRESSURE_BAR = 4.0
# OPEN_DURATION_S = 2
# REPEATS = 3

# tcm.set_pressure(PRESSURE_BAR)

# # tcm.clean(pressure_bar=PRESSURE_BAR,
# #           open_duration_s=OPEN_DURATION_S, repeats=REPEATS)


# # # Make a layer and take an after picture
# # make_layer()
# imager()

# # Produce a cough and take a final picture
# tcm.clean(pressure_bar=PRESSURE_BAR,
#           open_duration_s=OPEN_DURATION_S, repeats=REPEATS)
# imager()

# tcm.set_pressure(1.5)

camera.close()
tcm.quit()
