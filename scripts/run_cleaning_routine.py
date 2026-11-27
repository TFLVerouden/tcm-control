"""Run the cough-machine channel cleaning routine without a TOML config."""

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.devices import Camera, CoughMachine
from tcm_control.clean_channel import clean_channel

# Strong Cough
PRESSURE_BAR = 5
OPEN_DURATION_S = 5
DRY_PRESSURE_BAR = 2
DRY_DURATION_S = 60
DRY_VALVE_CURRENT_MA = 13
REPEATS = 3
USE_CAMERA = True

if __name__ == "__main__":
    tcm = CoughMachine(debug=False)
    camera = None
    try:
        if USE_CAMERA:
            camera = Camera()
            camera.open()
        print("Starting channel cleaning routine...")
        clean_channel(tcm,
                      camera=camera,
                      clean_pressure_bar=PRESSURE_BAR,
                      clean_valve_open_duration_s=OPEN_DURATION_S,
                      clean_cycle_count=REPEATS,
                      dry_pressure_bar=DRY_PRESSURE_BAR,
                      dry_duration_s=DRY_DURATION_S,
                      dry_valve_current_ma=DRY_VALVE_CURRENT_MA)
        print("Cleaning routine completed.")
    finally:
        try:
            if camera is not None:
                camera.close()
        finally:
            tcm.close()
