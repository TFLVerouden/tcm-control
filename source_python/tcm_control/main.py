from pathlib import Path

from importlib import resources
import time

from tcm_control.devices import CoughMachine, SprayTecLift, SyringePump
from tcm_control import logger
from tcm_utils.io_utils import prompt_input
from tcm_utils.time_utils import timestamp_str


def ask_user_for_comments(output_dir: Path) -> str:
    # Ask user for comments about the run, which will be saved in a text file
    # in the experiment directory.

    print("Enter comments for this run (press Enter to confirm, leave empty to skip): ")
    comments = input(">> ")
    if comments:
        logger.write_comments(output_dir, comments)

    return comments


def set_spraytec_xy(tcm_trachea_exit_to_ref_x_mm: float,
                    tcm_trachea_exit_to_ref_y_mm: float,
                    spraytec_to_ref_x_mm: float,
                    spraytec_to_ref_y_mm: float,
                    stage_position_x_mm: Optional[float] = None,
                    stage_position_y_mm: Optional[float] = None) -> tuple[float, float]:

    if stage_position_x_mm is None or stage_position_y_mm is None:
        # Ask user to read off x and y position of the cough machine
        print("Read off the x and y scale on the cough machine stage.")
        # TODO: Set min and max values
        x = prompt_input("x (cross-airflow) position in mm: ",
                         value_type="float", min_value=0, max_value=100)
        y = prompt_input("y (along-airflow) position in mm: ",
                         value_type="float", min_value=0, max_value=100)
    else:
        x = stage_position_x_mm
        y = stage_position_y_mm

    return (x - tcm_trachea_exit_to_ref_x_mm - spraytec_to_ref_x_mm,
            y - tcm_trachea_exit_to_ref_y_mm - spraytec_to_ref_y_mm)


if __name__ == "__main__":
    # Config variables
    FLOW_CURVE_CSV_PATH = None
    SYRINGE_VOLUME_ML = 2.5
    TANK_PRESSURE_BAR = 1.5
    DROPLET_PUMP_RATE_ML_PER_MIN = 0.1
    # [SPRAYTEC] Following values only have to be set when recording droplet size using SprayTec
    # TODO: Measure offsets and enter here
    # Vertical position of the bottom of the cough machine trachea relative to floor
    TCM_TRACHEA_BOTTOM_Z_MM = 100.0
    # Height of the cough machine trachea
    TCM_TRACHEA_HEIGHT_MM = 10.0
    # Vertical position of lift platform top when it reports 0 mm, relative to floor
    LIFT_ZERO_Z_MM = 0.0
    # Vertical distance between lift platform and the centre of the SprayTec measurement volume
    SPRAYTEC_TO_LIFT_Z_MM = 50.0

    TCM_TRACHEA_EXIT_TO_REF_X_MM = 50.0
    TCM_TRACHEA_EXIT_TO_REF_Y_MM = 50.0
    SPRAYTEC_TO_REF_X_MM = 10.0
    SPRAYTEC_TO_REF_Y_MM = 10.0
    STAGE_POSITION_X_MM = None  # can be None, is then prompted
    STAGE_POSITION_Y_MM = None  # can be None, is then prompted

    # Generate experiment directory based on current timestamp and experiment name
    start_time = timestamp_str()
    output_dir = logger.create_experiment_dir(
        EXPERIMENT_BASE_DIR, EXPERIMENT_NAME, start_time=start_time)

    # Initialise devices
    # lift = SprayTecLift()
    # print("Current height:", lift.get_height(), " mm")
    # pump = SyringePump(syringe_volume_ml=SYRINGE_VOLUME_ML)
    tcm = CoughMachine(debug=False)

    # Cough machine settings
    tcm.set_pressure(TANK_PRESSURE_BAR, timeout_s=10.0)
    tcm.load_flowcurve(csv_path="step", copy_path=output_dir)

    # Turn on syringe pump
    # pump.infuse(pump_rate_ml_mn=DROPLET_PUMP_RATE_ML_PER_MIN)
    # time.sleep(2)  # Wait a bit for the pump to start infusing

    # Go into droplet detection mode with a finite count
    # detections = tcm.count_droplets(runs=5)
    # print(f"Detected droplets: {detections}")

    tcm.run(output_dir=output_dir)
    ask_user_for_comments(output_dir=output_dir)

    # Ensure active modes are stopped
    tcm.quit()

    # Stop the pump after droplet detection is done
    # pump.stop()
