from pathlib import Path

from importlib import resources
import time
from typing import Optional

from tcm_control.devices import CoughMachine, SprayTecLift, SyringePump
from tcm_control.devices.spraytec_output import save_spraytec_data
from tcm_control import logger
from tcm_utils.io_utils import prompt_input, prompt_yes_no
from tcm_utils.time_utils import timestamp_str


def ask_start_confirmation(experiment_name: str):
    result = prompt_yes_no(
        f"Press Enter to start experiment \"{experiment_name}\"...", default=True)

    if not result:
        print("Aborted.")
        exit(1)

    return


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
    # [EXPERIMENT] Config variables
    EXPERIMENT_MODE = "droplet"  # "droplet", "film", "piv", "manual"
    FLOW_CURVE_CSV_PATH = "step"  # name of default flow curve or full
    TANK_PRESSURE_BAR = 1.0
    EXPERIMENT_NAME = "firmware_test_droplet"
    SERIES_DIR = Path("C:\\CoughMachineData\\260226_tests")
    # time between sending the run command or detecting a droplet and starting the flow profile, in milliseconds
    WAIT_BEFORE_RUN_MS = 67.5
    RECORD_DROPLET_SIZE = False

    # [PUMP] Only have to be set when in droplet or PIV mode
    SYRINGE_VOLUME_ML = 2.5
    DROPLET_PUMP_RATE_ML_PER_MIN = 0.1
    # skip the first n detections to allow the pump to start infusing properly
    NR_DROPLETS_TO_SKIP = 5

    # [SPRAYTEC] Following values only have to be set when recording droplet size using SprayTec
    SPRAYTEC_APPEND_FILE_PATH = None  # set to Path(...) to avoid file dialog
    DEBUG_MODE = False

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

    # [MULTI-RUN] Only have to be set when running multiple runs in a row
    NR_RUNS = 3
    # Time to wait between runs when running multiple runs in a row, in seconds.
    MULTI_RUN_INTERVAL_S = 5.0

    # Some processing/checking of config variables should happen below
    # ...
    if NR_RUNS == None:
        NR_RUNS = 1
    wait_before_run_us = int(WAIT_BEFORE_RUN_MS * 1000)

    # ==========================================================================

    # Generate experiment directory based on current timestamp and experiment name
    time_start = timestamp_str()
    output_dir = logger.create_experiment_dir(
        SERIES_DIR, EXPERIMENT_NAME, start_time=time_start)

    # Initialise cough machine
    tcm = CoughMachine(debug=DEBUG_MODE)
    tcm.set_pressure(TANK_PRESSURE_BAR, timeout_s=60.0)
    tcm.set_wait_us(wait_us=wait_before_run_us)
    tcm.load_flowcurve(csv_path=FLOW_CURVE_CSV_PATH, experiment_dir=output_dir)

    # Initialise SprayTec lift and get height
    if RECORD_DROPLET_SIZE:
        lift = SprayTecLift()
        spraytec_z = lift.get_spraytec_height(
            tcm_trachea_bottom_z_mm=TCM_TRACHEA_BOTTOM_Z_MM,
            tcm_trachea_height_mm=TCM_TRACHEA_HEIGHT_MM,
            lift_zero_z_mm=LIFT_ZERO_Z_MM,
            spraytec_to_lift_z_mm=SPRAYTEC_TO_LIFT_Z_MM)
        spraytec_x, spraytec_y = set_spraytec_xy(
            TCM_TRACHEA_EXIT_TO_REF_X_MM,
            TCM_TRACHEA_EXIT_TO_REF_Y_MM,
            SPRAYTEC_TO_REF_X_MM,
            SPRAYTEC_TO_REF_Y_MM,
            stage_position_x_mm=STAGE_POSITION_X_MM,
            stage_position_y_mm=STAGE_POSITION_Y_MM)

        print("SprayTec measurement volume position (x, y, z) in mm: ",
              spraytec_x, spraytec_y, spraytec_z)

        # TODO: Check here for the existence of the SprayTec append file

        # TODO: Check name of this "ready" mode on the SprayTec and update the prompt accordingly
        prompt_yes_no(
            "Press Enter to confirm that SprayTec is in ready mode...", default=True)

    match EXPERIMENT_MODE:
        # Manual mode
        case "manual":
            print(
                f"Running in manual mode, for direct serial communication with {tcm.name}")
            tcm.manual_mode()

        # Droplet mode
        case "droplet":
            pump = SyringePump(syringe_volume_ml=SYRINGE_VOLUME_ML)

            # Wait for user to start the experiment
            ask_start_confirmation(experiment_name=EXPERIMENT_NAME)

            # Record temperature and humidity
            temperature_start, humidity_start = tcm.read_temperature_humidity()

            for run_idx in range(NR_RUNS):
                # Wait between coughs if needed
                if run_idx > 0 and MULTI_RUN_INTERVAL_S > 0:
                    start_loop_time = time.time()
                    last_printed_seconds = None
                    while True:
                        elapsed = time.time() - start_loop_time
                        seconds_remaining = max(
                            0, int(MULTI_RUN_INTERVAL_S - elapsed))
                        if seconds_remaining != last_printed_seconds:
                            print(
                                f"Waiting for {seconds_remaining} seconds before starting next run\r", end="", flush=True)
                            last_printed_seconds = seconds_remaining
                        if elapsed >= MULTI_RUN_INTERVAL_S:
                            break
                        time.sleep(0.05)

                    # Ask confirmation to continue (CAN BE COMMENTED OUT)
                    prompt_yes_no(
                        f"\rPress Enter to continue...                                        ", default=True)

                # Turn on syringe pump
                pump.infuse(pump_rate_ml_mn=DROPLET_PUMP_RATE_ML_PER_MIN)

                # Let the pump run for a bit to ensure proper infusion before starting the next cough
                tcm.count_droplets(nr_droplets=5, let_drip=True)
                # TODO: test this let_drip mode

                # Then go into droplet detection mode
                tcm.detect_droplets_and_run(nr_runs=1, output_dir=output_dir,
                                            run_nr_start=(run_idx + 1))

                # Turn off pump
                pump.stop()

        # Film mode
        case "film":

            if NR_RUNS > 1:
                raise NotImplementedError(
                    "Multi-run is not implemented for film mode yet.")

            # Ask user to start the experiment
            ask_start_confirmation(experiment_name=EXPERIMENT_NAME)

            # Record temperature and humidity
            temperature_start, humidity_start = tcm.read_temperature_humidity()

            tcm.run(output_dir=output_dir)

        # PIV mode
        case "piv":
            raise NotImplementedError("PIV mode not implemented yet.")

    # Finish off
    # Ask user for comments about the run
    ask_user_for_comments(output_dir=output_dir)

    # Record temperature and humidity
    temperature_finish, humidity_finish = tcm.read_temperature_humidity()
    time_finish = timestamp_str()

    print("Experiment completed, all data saved to ", output_dir)

    # TODO: Post-processing
    if RECORD_DROPLET_SIZE:
        prompt_yes_no(
            "Press Enter if the SprayTec has finished processing the measurement(s)...",
            default=True,
        )
        save_spraytec_data(
            append_file_path=SPRAYTEC_APPEND_FILE_PATH,
            experiment_dir=output_dir,
            start_time=time_start,
            debug=DEBUG_MODE,
        )
    

    print("Exiting.")
