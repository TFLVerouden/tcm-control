"""User prompt and input helpers for experiment runs."""

from pathlib import Path
from typing import Optional

from tcm_control import logger
from tcm_utils.io_utils import prompt_input, prompt_yes_no, wait_with_progress


def ask_start_confirmation(experiment_name: str) -> None:
    """Ask the user to confirm experiment start."""
    result = prompt_yes_no(
        f"Press ENTER to start experiment \"{experiment_name}\"...", default=True
    )

    if not result:
        print("Aborted.")
        raise SystemExit(1)


def ask_user_for_comments(output_dir: Path) -> str:
    """Prompt user comments and store them in the experiment directory."""

    print(
        "Enter comments for this run "
        "(press ENTER to confirm, leave empty to skip): "
    )
    comments = input(">> ")
    if comments:
        logger.write_comments(output_dir, comments)

    return comments


def set_spraytec_xy(
    tcm_trachea_exit_to_ref_x_mm: float,
    tcm_trachea_exit_to_ref_y_mm: float,
    spraytec_to_ref_x_mm: float,
    spraytec_to_ref_y_mm: float,
    stage_pos_x_zero_mm: float,
    stage_pos_y_zero_mm: float,
    stage_pos_x_mm: Optional[float] = None,
    stage_pos_y_mm: Optional[float] = None,
) -> tuple[float, float, float, float]:
    """Return SprayTec x/y from stage position and known geometry offsets.

    If stage positions are not provided, they are prompted from the user.
    """
    if stage_pos_x_mm is None or stage_pos_y_mm is None:
        # Ask user to read off x and y position of the cough machine
        print("Read off the x and y scale on the cough machine stage.")
        stage_pos_x_mm = prompt_input(
            "x (cross-airflow) position in mm: ",
            value_type="float",
            min_value=2,
            max_value=200,
        )
        stage_pos_y_mm = prompt_input(
            "y (along-airflow) position in mm: ",
            value_type="float",
            min_value=0,
            max_value=784,
        )

    spraytec_x = (
        stage_pos_x_zero_mm
        - stage_pos_x_mm
        - tcm_trachea_exit_to_ref_x_mm
        + spraytec_to_ref_x_mm
    )
    spraytec_y = (
        stage_pos_y_zero_mm
        - stage_pos_y_mm
        - tcm_trachea_exit_to_ref_y_mm
        + spraytec_to_ref_y_mm
    )
    return spraytec_x, spraytec_y, stage_pos_x_mm, stage_pos_y_mm


def wait_or_confirm_next_run(
    *,
    next_run_number: int,
    nr_runs: int,
    multi_run_interval_s: float,
    confirm_before_starting_next_run: bool,
) -> None:
    """Handle optional inter-run waiting and user confirmation prompts."""
    if multi_run_interval_s > 0:
        wait_with_progress(
            float(multi_run_interval_s),
            label=f"Waiting before starting run {next_run_number}/{nr_runs}",
        )

    if confirm_before_starting_next_run:
        prompt_yes_no(
            f"Press ENTER to continue with run {next_run_number}/{nr_runs}...",
            default=True,
        )
