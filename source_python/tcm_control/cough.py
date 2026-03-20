"""Main experiment runner for the Twente Cough Machine."""

import signal
import shutil
from pathlib import Path

from typing import Optional

from tcm_control.devices import CoughMachine, SprayTecLift, SyringePump
from tcm_control.devices.spraytec_output import (
    resolve_append_file_path,
    save_spraytec_data,
)
from tcm_control import logger
from tcm_control.init_config import load_experiment_config
from tcm_utils.file_dialogs import ask_directory
from tcm_utils.io_utils import prompt_input, prompt_yes_no, wait_with_progress
from tcm_utils.time_utils import timestamp_str


# References to currently active devices, used by the Ctrl+C cleanup path.
_ACTIVE_TCM: Optional[CoughMachine] = None
_ACTIVE_PUMP: Optional[SyringePump] = None
_ACTIVE_OUTPUT_DIR: Optional[Path] = None
_INTERRUPT_CLEANED_UP = False


def _cleanup_on_interrupt(*, ask_before_delete_output_dir: bool = False) -> None:
    """Stop active devices once after Ctrl+C.

    Args:
        ask_before_delete_output_dir: When True, prompt before deleting the output
            directory. Keep this False in signal handlers to avoid re-entrant input.
    """
    global _INTERRUPT_CLEANED_UP
    # Prevent duplicate cleanup attempts if SIGINT is received more than once.
    if _INTERRUPT_CLEANED_UP:
        return
    _INTERRUPT_CLEANED_UP = True

    if _ACTIVE_PUMP is not None:
        try:
            _ACTIVE_PUMP.stop()
            print("Syringe pump stopped")
        except Exception as exc:
            print(f"Warning: Failed to stop syringe pump: {exc}")

    if _ACTIVE_TCM is not None:
        try:
            _ACTIVE_TCM.quit()
            print("Cough machine returned to idle")
        except Exception as exc:
            print(f"Warning: Failed to quit cough machine: {exc}")

    if _ACTIVE_OUTPUT_DIR is not None and _ACTIVE_OUTPUT_DIR.exists():
        output_dir_full = _ACTIVE_OUTPUT_DIR.resolve()
        if ask_before_delete_output_dir:
            delete_output_dir = prompt_yes_no(
                "Remove created experiment directory? "
                f"{output_dir_full} "
                "(press ENTER to cancel, type 'y' to delete)",
                default=False,
            )
        else:
            delete_output_dir = False
            print(
                "Skipping output-directory deletion prompt during Ctrl+C cleanup "
                "to avoid re-entrant stdin access."
            )

        if delete_output_dir:
            try:
                shutil.rmtree(output_dir_full)
                print(f"Removed experiment directory: {output_dir_full}")
            except Exception as exc:
                print(
                    f"Warning: Failed to remove experiment directory {output_dir_full}: {exc}")
        print("Exiting")


def _handle_sigint(_signum, _frame) -> None:
    """Handle Ctrl+C by raising KeyboardInterrupt.

    Keep signal-handler work minimal and non-interactive; cleanup is performed
    in regular exception handling flow.
    """
    print("\nCtrl+C detected; stopping experiment...")
    raise KeyboardInterrupt


# -----------------------------------------------------------------------------
# User interaction helpers
# -----------------------------------------------------------------------------


def ask_start_confirmation(experiment_name: str):
    """Ask the user to confirm experiment start."""
    result = prompt_yes_no(
        f"Press Enter to start experiment \"{experiment_name}\"...", default=True)

    if not result:
        print("Aborted.")
        exit(1)

    return


def ask_user_for_comments(output_dir: Path) -> str:
    """Prompt user comments and store them in the experiment directory."""

    print(
        "Enter comments for this run "
        "(press Enter to confirm, leave empty to skip): "
    )
    comments = input(">> ")
    if comments:
        logger.write_comments(output_dir, comments)

    return comments


def set_spraytec_xy(tcm_trachea_exit_to_ref_x_mm: float,
                    tcm_trachea_exit_to_ref_y_mm: float,
                    spraytec_to_ref_x_mm: float,
                    spraytec_to_ref_y_mm: float,
                    stage_pos_x_zero_mm: float,
                    stage_pos_y_zero_mm: float,
                    stage_pos_x_mm: Optional[float] = None,
                    stage_pos_y_mm: Optional[float] = None
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
    else:
        stage_pos_x_mm = stage_pos_x_mm
        stage_pos_y_mm = stage_pos_y_mm

    spraytec_x = stage_pos_x_zero_mm - stage_pos_x_mm - \
        tcm_trachea_exit_to_ref_x_mm + spraytec_to_ref_x_mm
    spraytec_y = stage_pos_y_zero_mm - stage_pos_y_mm - \
        tcm_trachea_exit_to_ref_y_mm + spraytec_to_ref_y_mm
    return spraytec_x, spraytec_y, stage_pos_x_mm, stage_pos_y_mm


def cough(config_path: Path | str | None = None) -> Path:
    """Run a full experiment using a TOML configuration.

    Args:
        config_path: Optional TOML path. If omitted, a file picker opens.

    Returns:
        The experiment output directory path.
    """
    # Load and unpack normalized config dictionaries.
    config = load_experiment_config(config_path)

    experiment_config = config["experiment"]
    core_inputs = config["inputs"]["core"]
    cough_machine_inputs = config["devices"]["cough_machine"]["inputs"]
    pump_inputs = config["devices"]["pump"]["inputs"]
    spraytec_inputs = config["devices"]["spraytec"]["inputs"]

    experiment_name = experiment_config["name"]
    if experiment_name is None:
        while True:
            prompted_name = prompt_input(
                "Enter experiment name: ",
                allow_empty=True,
            )
            experiment_name = (
                "" if prompted_name is None else str(prompted_name).strip()
            )
            if experiment_name:
                break
            print("Experiment name cannot be empty.")

    experiment_mode = experiment_config["mode"]
    series_directory_value = experiment_config["series_directory"]
    if series_directory_value is None:
        selected_series_dir = ask_directory(
            key="tcm_series_directory",
            title="Select series directory",
            start=Path(__file__).resolve().parent,
        )
        if selected_series_dir is None:
            raise SystemExit("No series directory selected.")
        series_directory = selected_series_dir
    else:
        series_directory = Path(series_directory_value)

    record_droplet_size = config["devices"]["spraytec"]["enabled"]

    wait_before_run_us = core_inputs["wait_before_run_us"]

    pump = None
    lift = None
    spraytec_x = None
    spraytec_y = None
    spraytec_z = None
    spraytec_audit_path = None

    # ------------------------------------------------------------------
    # Prepare output folder and device state variables
    # ------------------------------------------------------------------

    # Create output directory for this experiment.
    time_start = timestamp_str()
    output_dir = logger.create_experiment_dir(
        series_directory, experiment_name, start_time=time_start)
    global _ACTIVE_OUTPUT_DIR
    _ACTIVE_OUTPUT_DIR = output_dir
    console_log_path = logger.create_console_log_path(output_dir)

    with logger.capture_terminal_output(console_log_path):
        print(f"Session console log file: {console_log_path}")
        print("Starting cough machine experiment, "
              "press Ctrl+C at any time to abort and safely exit")

        # Initialise cough machine and load flow curve.
        tcm = CoughMachine(debug=core_inputs["debug_mode"])
        global _ACTIVE_TCM, _ACTIVE_PUMP
        # Register device so interrupt cleanup can call quit() on it.
        _ACTIVE_TCM = tcm
        tcm.set_pressure(
            cough_machine_inputs["tank_pressure_bar"],
            timeout_s=cough_machine_inputs["tank_pressure_settling_time_s"],
            avg_window_s=cough_machine_inputs["tank_pressure_avg_window_s"],
            tolerance_bar=cough_machine_inputs["tank_pressure_tolerance_bar"],
            poll_interval_s=cough_machine_inputs["tank_pressure_poll_interval_s"],
            interm_press_diff_bar=cough_machine_inputs[
                "tank_pressure_intermediate_diff_bar"
            ],
            interm_press_time_s=cough_machine_inputs[
                "tank_pressure_intermediate_time_s"
            ],
        )
        tcm.set_wait_us(wait_us=wait_before_run_us)
        tcm.load_flowcurve(
            csv_path=cough_machine_inputs["flow_curve_csv_path"],
            experiment_dir=output_dir,
        )
        # Store the resolved flow curve path for metadata traceability.
        cough_machine_inputs["flow_curve_csv_path"] = tcm.get_flowcurve_csv_path(
        )

        # Optional SprayTec setup and geometry resolution.
        if record_droplet_size:
            lift = SprayTecLift()
            spraytec_z, lift_height = lift.get_spraytec_height(
                tcm_trachea_bottom_z_mm=spraytec_inputs["tcm_trachea_bottom_z_mm"],
                tcm_trachea_height_mm=spraytec_inputs["tcm_trachea_height_mm"],
                lift_zero_z_mm=spraytec_inputs["lift_zero_z_mm"],
                table_height_mm=spraytec_inputs["table_height_mm"],
                spraytec_to_lift_z_mm=spraytec_inputs["spraytec_to_lift_z_mm"],
            )
            spraytec_x, spraytec_y, stage_pos_x_mm, stage_pos_y_mm = set_spraytec_xy(
                spraytec_inputs["tcm_trachea_exit_to_ref_x_mm"],
                spraytec_inputs["tcm_trachea_exit_to_ref_y_mm"],
                spraytec_inputs["spraytec_to_ref_x_mm"],
                spraytec_inputs["spraytec_to_ref_y_mm"],
                spraytec_inputs["stage_pos_x_zero_mm"],
                spraytec_inputs["stage_pos_y_zero_mm"],
                stage_pos_x_mm=spraytec_inputs["stage_pos_x_mm"],
                stage_pos_y_mm=spraytec_inputs["stage_pos_y_mm"],
            )
            spraytec_inputs["stage_pos_x_mm"] = stage_pos_x_mm
            spraytec_inputs["stage_pos_y_mm"] = stage_pos_y_mm

            spraytec_inputs["append_file_path"] = resolve_append_file_path(
                spraytec_inputs["append_file_path"]
            )

            print("SprayTec measurement volume position (x, y, z) in mm: ",
                  spraytec_x, spraytec_y, spraytec_z)
            print(
                f"SprayTec append file: {spraytec_inputs['append_file_path']}")

            prompt_yes_no(
                "Press Enter to confirm that SprayTec SOP is waiting for a trigger...",
                default=True)
            # TODO: Merge this prompt with the start experiment prompt in certain cases. Probably involves making a separate pump if statement before

        # ------------------------------------------------------------------
        # Run mode-specific experiment behavior
        # ------------------------------------------------------------------
        match experiment_mode:
            # Manual mode
            case "manual":
                temperature_start, humidity_start = tcm.read_temperature_humidity()
                print(
                    f"Running in manual mode, for direct serial communication with {tcm.name}")
                tcm.manual_mode()

            # Droplet mode
            case "droplet":
                pump = SyringePump(
                    syringe_volume_ml=pump_inputs["syringe_volume_ml"])
                # Register pump so interrupt cleanup can call stop() on it.
                _ACTIVE_PUMP = pump

                # Wait for user to start the experiment
                ask_start_confirmation(experiment_name=experiment_name)

                # Record temperature and humidity
                temperature_start, humidity_start = tcm.read_temperature_humidity()

                for run_idx in range(core_inputs["nr_runs"]):
                    # Wait between coughs if needed
                    if run_idx > 0:
                        if core_inputs["multi_run_interval_s"] > 0:
                            wait_with_progress(
                                float(core_inputs["multi_run_interval_s"]),
                                label="Waiting before starting next run",
                            )

                        if core_inputs["confirm_before_starting_next_run"]:
                            prompt_yes_no(
                                "Press Enter to continue...",
                                default=True,
                            )

                    # Turn on syringe pump
                    pump.infuse(
                        pump_rate_ml_mn=pump_inputs["droplet_pump_rate_ml_per_min"])

                    # Optionally let pump run before recording
                    nr_droplets_to_skip = pump_inputs[
                        "nr_droplets_to_skip_before_recording"
                    ]
                    if nr_droplets_to_skip > 0:
                        print("Flushing before starting cough")
                        tcm.count_droplets(
                            nr_droplets=nr_droplets_to_skip, let_drip=True)

                    # Then go into droplet detection mode
                    tcm.detect_droplets_and_run(
                        nr_runs=1,
                        output_dir=output_dir,
                        run_nr_start=(run_idx + 1),
                    )

                    # Turn off pump
                    pump.stop()

            # Film mode
            case "film":

                if core_inputs["nr_runs"] > 1:
                    raise NotImplementedError(
                        "Multi-run is not implemented for film mode yet.")
                    # TODO: Implement multi-run for film mode

                # Ask user to start the experiment
                ask_start_confirmation(experiment_name=experiment_name)

                # Record temperature and humidity
                temperature_start, humidity_start = tcm.read_temperature_humidity()

                tcm.run(output_dir=output_dir)

            # PIV mode
            case "piv":
                raise NotImplementedError("PIV mode not implemented yet.")

        # Finish off
        if experiment_mode != "manual":
            # Collect comments
            comments = ask_user_for_comments(output_dir=output_dir)

            # Record temperature and humidity
            temperature_finish, humidity_finish = tcm.read_temperature_humidity()
            time_finish = timestamp_str()

            # Optional SprayTec post-processing.
            if record_droplet_size:
                prompt_yes_no(
                    "Press Enter if the SprayTec has finished processing and exporting the measurement(s)...",
                    default=True,
                )
                spraytec_audit_path = save_spraytec_data(
                    append_file_path=spraytec_inputs["append_file_path"],
                    experiment_dir=output_dir,
                    start_time=time_start,
                    debug=core_inputs["debug_mode"],
                    offer_archive_if_large=True,
                )

            metadata = logger.build_run_metadata(
                time_start=time_start,
                time_finish=time_finish,
                experiment_name=experiment_name,
                experiment_mode=experiment_mode,
                output_dir=output_dir,
                wait_before_run_us=wait_before_run_us,
                temperature_start=temperature_start,
                humidity_start=humidity_start,
                temperature_finish=temperature_finish,
                humidity_finish=humidity_finish,
                comments=comments,
                core_inputs=core_inputs,
                tcm=tcm,
                cough_machine_inputs=cough_machine_inputs,
                pump=pump,
                pump_inputs=pump_inputs,
                record_droplet_size=record_droplet_size,
                spraytec_inputs=spraytec_inputs,
                spraytec_x=spraytec_x,
                spraytec_y=spraytec_y,
                spraytec_z=spraytec_z,
                spraytec_audit_path=spraytec_audit_path,
                lift_height=lift_height,
                lift=lift,
            )
            # Persist full run metadata snapshot.
            logger.write_run_metadata(
                experiment_dir=output_dir, metadata=metadata)

            print("Experiment completed, all data saved to ", output_dir)
            print("Exiting.")

    # Return output directory
    return output_dir


if __name__ == "__main__":
    # Temporarily install a SIGINT handler so Ctrl+C triggers device cleanup.
    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        cough()
    except KeyboardInterrupt:
        _cleanup_on_interrupt(ask_before_delete_output_dir=True)
        raise SystemExit(130)
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)
