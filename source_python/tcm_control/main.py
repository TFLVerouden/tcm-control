from pathlib import Path

from importlib import resources
import time

from tcm_control.devices import CoughMachine, SprayTecLift, SyringePump
from tcm_control import logger
from tcm_utils.io_utils import prompt_input


def ask_user_for_comments(experiment_dir: Path) -> str:
    # Ask user for comments about the run, which will be saved in a text file
    # in the experiment directory.

    print("Enter comments for this run (press Enter to confirm, leave empty to skip): ")
    comments = input(">> ")
    if comments:
        logger.write_comments(experiment_dir, comments)

    return comments


if __name__ == "__main__":
    # Config variables
    FLOW_CURVE_CSV_PATH = None
    SYRINGE_VOLUME_ML = 2.5
    TANK_PRESSURE_BAR = 1.5
    DROPLET_PUMP_RATE_ML_PER_MIN = 0.1

    # Initialise devices
    lift = SprayTecLift()
    # print("Current height:", lift.get_height(), " mm")
    pump = SyringePump(syringe_volume_ml=SYRINGE_VOLUME_ML)
    tcm = CoughMachine(debug=False)

    # Cough machine settings
    tcm.set_pressure(TANK_PRESSURE_BAR, timeout_s=10.0)
    tcm.load_flowcurve(csv_path="step")

    # Turn on syringe pump
    pump.infuse(pump_rate_ml_mn=DROPLET_PUMP_RATE_ML_PER_MIN)
    time.sleep(2)  # Wait a bit for the pump to start infusing

    # Go into droplet detection mode with a finite count
    detections = tcm.count_droplets(runs=5)
    print(f"Detected droplets: {detections}")

    # Ensure active modes are stopped
    tcm.quit()

    # Stop the pump after droplet detection is done
    pump.stop()
