from pathlib import Path

from importlib import resources

from tcm_control.devices import CoughMachine, SprayTecLift
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

    lift = SprayTecLift()
    print("Current height:", lift.get_height(), " mm")
    # lift.read_status(echo=True)
    # cough_machine = CoughMachine(debug=False)
    # cough_machine.clear_memory()
    # cough_machine.set_pressure(1.5, timeout_s=10.0)

    # cough_machine.load_flowcurve(csv_path="step")
    # cough_machine.detect_droplet(runs=2, output_dir=output_dir)
    # cough_machine.manual_mode()
