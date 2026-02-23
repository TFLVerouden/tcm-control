from pathlib import Path

from importlib import resources

from tcm_control.devices import CoughMachine
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


def main() -> None:
    cough_machine = CoughMachine(debug=False)
    # cough_machine.clear_memory()
    cough_machine.set_pressure(1.5, timeout_s=10.0)

    flow_curve = resources.files(
        "tcm_control").joinpath("flow_curves/step.csv")
    output_dir = Path.cwd() / "CoughMachineData" / "Tests"

    cough_machine.load_flowcurve(csv_path=flow_curve)
    # cough_machine.detect_droplet(runs=2, output_dir=output_dir)
    cough_machine.manual_mode()


if __name__ == "__main__":
    main()
