"""User prompt and input helpers for experiment runs."""

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from tcm_control import logger
from tcm_utils.io_utils import prompt_input, prompt_yes_no, wait_with_progress

if TYPE_CHECKING:
    from tcm_control.devices.vertical_stage import VerticalStage


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


def set_spraytec_pos(
    lift: "VerticalStage",
    tcm_trachea_exit_to_ref_x_mm: float,
    tcm_trachea_exit_to_ref_y_mm: float,
    spraytec_to_ref_x_mm: float,
    spraytec_to_ref_y_mm: float,
    tcm_trachea_bottom_z_mm: float,
    tcm_trachea_height_mm: float,
    lift_zero_z_mm: float,
    table_height_mm: float,
    spraytec_to_lift_z_mm: float,
    stage_pos_x_zero_mm: float,
    stage_pos_y_zero_mm: float,
    spraytec_target_z_mm: Optional[float] = None,
    stage_pos_x_mm: Optional[float] = None,
    stage_pos_y_mm: Optional[float] = None,
) -> tuple[float, float, float, float, float, float, float]:
    """Return SprayTec x/y/z from known geometry and requested stage position.

    If stage x/y positions are not provided, the user is asked to read them from
    the cough machine stage scales. If SprayTec z is not provided, the user is
    asked for the target height in mm and the lift is moved automatically.
    """
    if stage_pos_x_mm is None or stage_pos_y_mm is None:
        # Ask user to read x/y directly from the physical cough-machine stages.
        print("Set the cough machine stage to the desired position and read off the x/y values")
        stage_pos_x_mm = prompt_input(
            "  x: from cough machine stage ruler (cross-airflow) [mm]: ",
            value_type="float",
            min_value=2,
            max_value=200,
        )
        stage_pos_y_mm = prompt_input(
            "  y: from cough machine stage ruler (along-airflow) [mm]: ",
            value_type="float",
            min_value=0,
            max_value=784,
        )

    if spraytec_target_z_mm is None:
        print("Enter the desired measurement height z in mm; the lift will be moved automatically")
        spraytec_target_z_mm = prompt_input(
            "  z: target SprayTec height [mm]: ",
            value_type="float",
        )

    spraytec_z_mm, lift_pos_z_mm = lift.set_spraytec_height(
        spraytec_target_z_mm,
        tcm_trachea_bottom_z_mm=tcm_trachea_bottom_z_mm,
        tcm_trachea_height_mm=tcm_trachea_height_mm,
        lift_zero_z_mm=lift_zero_z_mm,
        table_height_mm=table_height_mm,
        spraytec_to_lift_z_mm=spraytec_to_lift_z_mm,
    )
    if spraytec_z_mm is None or lift_pos_z_mm is None:
        raise RuntimeError("Failed to set SprayTec z position.")

    spraytec_x_mm = (
        stage_pos_x_zero_mm
        - stage_pos_x_mm
        - tcm_trachea_exit_to_ref_x_mm
        + spraytec_to_ref_x_mm
    )
    spraytec_y_mm = (
        stage_pos_y_zero_mm
        - stage_pos_y_mm
        - tcm_trachea_exit_to_ref_y_mm
        + spraytec_to_ref_y_mm
    )
    return (
        spraytec_x_mm,
        spraytec_y_mm,
        spraytec_z_mm,
        stage_pos_x_mm,
        stage_pos_y_mm,
        spraytec_target_z_mm,
        lift_pos_z_mm,
    )


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
