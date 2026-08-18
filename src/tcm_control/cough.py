"""Main experiment runner for the Twente Cough Machine."""

from contextlib import nullcontext
import time
from pathlib import Path

from typing import Optional

from tcm_control.devices import CoughMachine, VerticalStage, SyringePump, SprayTec
from tcm_control import logger
from tcm_control.initialise_config import load_experiment_config
from tcm_control.interrupt_handling import (
    reset_interrupt_cleanup_state,
    set_active_output_dir,
    set_active_pump,
    set_active_tcm,
)
from tcm_control.processing.run_log_processing import plot_run_log
from tcm_control.user_input import (
    ask_start_confirmation,
    ask_user_for_comments,
    set_spraytec_pos,
    wait_or_confirm_next_run,
)
from tcm_utils.file_dialogs import ensure_directory_path
from tcm_utils.io_utils import (
    ensure_non_empty_text,
    prompt_input,
    prompt_yes_no,
)
from tcm_utils.time_utils import timestamp_str

from tcm_control.devices.ops3330.ops3330 import OPSClient, OPS
import logging
import sys
import time
from pathlib import Path
import datetime


def cough(config_path: Path | str | None = None) -> Optional[Path]:
    """Run a full experiment using a TOML configuration.

    Args:
        config_path: Optional TOML path. If omitted, a file picker opens.

    Returns:
        The experiment output directory path, or None when saving is disabled.
    """
    # Reset interrupt state for a fresh run and clear stale references.
    reset_interrupt_cleanup_state()
    set_active_tcm(None)
    set_active_pump(None)
    set_active_output_dir(None)

    # ------------------------------------------------------------------
    # 1) Load and validate configuration
    # ------------------------------------------------------------------

    # Load and unpack normalized config dictionaries.
    config = load_experiment_config(config_path)

    # Split the normalized config into local sections used throughout this run
    exp_conf = config["experiment"]
    cough_inputs = config["inputs"]["cough"]
    cough_machine_inputs = config["devices"]["cough_machine"]["inputs"]
    tank_inputs = cough_machine_inputs["tank"]
    pump_inputs = config["devices"]["pump"]["inputs"]
    vertical_stage_inputs = config["devices"]["vertical_stage"]["inputs"]
    spraytec_inputs = config["devices"]["spraytec"]["inputs"]
    # Cache the selected mode for the central match/case branch below
    experiment_mode = exp_conf["mode"]
    # Default to saving unless config explicitly disables it
    save_data = bool(exp_conf.get("save_data", True))

    # Ensure the experiment name is never empty because it is used in folder naming
    experiment_name = ensure_non_empty_text(
        exp_conf["name"],
        prompt="Enter experiment name: ",
        empty_error="Experiment name cannot be empty.",
    )
    if save_data:
        # Resolve and validate the root folder where this experiment run will be stored
        series_directory = ensure_directory_path(
            exp_conf["series_directory"],
            key="tcm_series_directory",
            title="Select series directory",
            start=Path(__file__).resolve().parent,
        )
        if series_directory is None:
            raise SystemExit("No series directory selected.")
    else:
        series_directory = None
        # Keep a clear runtime message when the run is intentionally non-persistent
        print("Data saving disabled via config setting series_directory='None'.")

    # Toggle for optional SprayTec setup and post-processing branches
    record_droplet_size = bool(cough_inputs["record_droplet_size"])

    # Host-level pre-trigger delay that is sent to the cough machine
    wait_before_run_us = cough_machine_inputs["wait_before_run_us"]

    pump = None
    lift = None
    lift_pos_z_mm = None
    stage_pos_x_mm = None
    stage_pos_y_mm = None
    spraytec_target_z_mm = None
    spraytec = None
    spraytec_x_mm = None
    spraytec_y_mm = None
    spraytec_z_mm = None
    spraytec_audit_path = None
    spraytec_laser_intensity = None
    first_run_log_path = None

    # ------------------------------------------------------------------
    # 2) Prepare output folder and host logging
    # ------------------------------------------------------------------

    # Capture run start timestamp once and reuse it across artifacts and metadata
    time_start = timestamp_str()
    output_dir: Optional[Path] = None
    console_log_path: Optional[Path] = None
    if save_data:
        assert series_directory is not None
        # Create output directory for this experiment.
        output_dir = logger.create_experiment_dir(
            series_directory, experiment_name, start_time=time_start)
        logger.copy_experiment_config(
            experiment_dir=output_dir,
            config_path=exp_conf["config_file_path"],
        )
        # Register folder globally so Ctrl+C cleanup can optionally remove it
        set_active_output_dir(output_dir)
        # Derive fixed path for host console logging in this experiment folder
        console_log_path = logger.create_console_log_path(output_dir)
        # Mirror stdout/stderr to the file for reproducibility and debugging
        logging_context = logger.capture_terminal_output(console_log_path)
    else:
        # No output directory exists in non-saving mode
        set_active_output_dir(None)
        # Use a no-op context manager so code below stays linear
        logging_context = nullcontext()

    # Set up logger to write all prints to a file when saving is enabled.
    with logging_context:
        # --------------------------------------------------------------
        # 3) Initialize devices and resolve run geometry
        # --------------------------------------------------------------

        if console_log_path is not None:
            print(f"Session console log file: {console_log_path}")
        print("Starting cough machine experiment, "
              "press Ctrl+C at any time to abort and safely exit")

        # Initialise cough machine
        tcm = CoughMachine(debug=cough_inputs["debug_mode"])

        # Register device so interrupt cleanup can call quit() on it
        set_active_tcm(tcm)

        tcm.set_pressure(
            # Drive tank to target pressure and hold until tolerance is satisfied
            tank_inputs["pressure_bar"],
            timeout_s=tank_inputs["settling_time_s"],
            avg_window_s=tank_inputs["avg_window_s"],
            tolerance_bar=tank_inputs["tolerance_bar"],
            poll_interval_s=tank_inputs["poll_interval_s"],
            interm_press_diff_bar=tank_inputs["intermediate_diff_bar"],
            interm_press_time_s=tank_inputs["intermediate_time_s"],
        )
        # Program the fixed pre-run wait into the cough machine controller
        tcm.set_wait_us(wait_us=wait_before_run_us)
        tcm.load_flowcurve(
            # Load the configured flow curve and optionally copy it into output_dir
            csv_path=cough_machine_inputs["flow_curve_csv_path"],
            experiment_dir=output_dir if save_data else None,
        )
        # Store the resolved flow curve path for metadata traceability.
        cough_machine_inputs["flow_curve_csv_path"] = tcm.get_flowcurve_csv_path(
        )

        # In droplet and PIV modes, set up the pump
        if experiment_mode in ["droplet", "piv"]:
            pump = SyringePump(
                syringe_volume_ml=pump_inputs["syringe_volume_ml"])

            # Register pump so interrupt cleanup can call stop() on it
            set_active_pump(pump)

        # Optional SprayTec setup and geometry resolution
        if record_droplet_size:
            # Vertical stage is only needed when SprayTec measurements are enabled.
            lift = VerticalStage()
            spraytec_x_mm, spraytec_y_mm, spraytec_z_mm, stage_pos_x_mm, stage_pos_y_mm, spraytec_target_z_mm, lift_pos_z_mm = set_spraytec_pos(
                lift,
                spraytec_inputs["tcm_trachea_exit_to_ref_x_mm"],
                spraytec_inputs["tcm_trachea_exit_to_ref_y_mm"],
                spraytec_inputs["spraytec_to_ref_x_mm"],
                spraytec_inputs["spraytec_to_ref_y_mm"],
                spraytec_inputs["tcm_trachea_bottom_z_mm"],
                spraytec_inputs["tcm_trachea_height_mm"],
                spraytec_inputs["lift_zero_z_mm"],
                spraytec_inputs["table_height_mm"],
                spraytec_inputs["spraytec_to_lift_z_mm"],
                spraytec_inputs["stage_pos_x_zero_mm"],
                spraytec_inputs["stage_pos_y_zero_mm"],
                spraytec_target_z_mm=spraytec_inputs["position"]["spraytec_target_z_mm"],
                stage_pos_x_mm=spraytec_inputs["position"]["stage_pos_x_mm"],
                stage_pos_y_mm=spraytec_inputs["position"]["stage_pos_y_mm"],
                tolerance_mm=vertical_stage_inputs["tolerance_mm"],
                timeout_s=vertical_stage_inputs["timeout_s"],
                poll_interval_s=vertical_stage_inputs["poll_interval_s"],
            )
            # Persist resolved/manual stage inputs for traceability in metadata.
            spraytec_inputs["position"]["stage_pos_x_mm"] = stage_pos_x_mm
            spraytec_inputs["position"]["stage_pos_y_mm"] = stage_pos_y_mm
            spraytec_inputs["position"]["spraytec_target_z_mm"] = spraytec_target_z_mm

            spraytec = SprayTec(
                append_file_path=spraytec_inputs["append_file_path"],
                experiment_dir=output_dir,
            )

            spraytec_inputs["append_file_path"] = spraytec.resolve_append_file_path(
                spraytec_inputs["append_file_path"]
            )

            print("SprayTec measurement volume position (x, y, z) in mm: ",
                  spraytec_x_mm, spraytec_y_mm, spraytec_z_mm)
            print(
                f"SprayTec append file: {spraytec_inputs['append_file_path']}")

            spraytec_laser_intensity = prompt_input("Enter SprayTec laser intensity (%) and press ENTER: ",
                                                    value_type="float", min_value=0, max_value=100)

            prompt_yes_no(
                "Press ENTER to confirm that SprayTec SOP is waiting for a trigger...",
                default=True)

        # ------------------------------------------------------------------
        # 4) Run mode-specific experiment behavior
        # ------------------------------------------------------------------
        match experiment_mode:
            # Droplet mode
            case "droplet":
                # ------------------------------------------------------
                # Mode: Droplet
                # ------------------------------------------------------

                assert pump is not None

                # Wait for user to start the experiment
                ask_start_confirmation(experiment_name=experiment_name)

                # Record temperature and humidity
                temperature_start, humidity_start = tcm.read_temperature_humidity()

                # Execute configured number of single-cough runs
                for run_idx in range(cough_inputs["nr_runs"]):
                    # Turn on syringe pump
                    pump.infuse(
                        pump_rate_ml_mn=pump_inputs["pump_rate_ml_per_min"])

                    # Optionally let pump run before recording
                    nr_droplets_to_skip = pump_inputs[
                        "nr_droplets_to_skip_before_recording"
                    ]
                    if nr_droplets_to_skip > 0:
                        print("Flushing before starting cough")
                        tcm.count_droplets(
                            nr_droplets=nr_droplets_to_skip, let_drip=True)

                    # Then go into droplet detection mode
                    saved_run_log_paths = tcm.detect_droplets_and_run(
                        nr_runs=1,
                        output_dir=output_dir,
                        run_nr_start=(run_idx + 1),
                        save_logs=save_data,
                    )
                    # Cache first run log for the summary plot in finalization
                    if run_idx == 0 and saved_run_log_paths:
                        first_run_log_path = saved_run_log_paths[0]

                    # Turn off pump
                    pump.stop()

                    # Skip inter-run wait/confirm prompts after the final run
                    is_last_run = run_idx == (cough_inputs["nr_runs"] - 1)
                    if not is_last_run:
                        wait_or_confirm_next_run(
                            next_run_number=(run_idx + 2),
                            nr_runs=cough_inputs["nr_runs"],
                            multi_run_interval_s=float(
                                cough_inputs["multi_run_interval_s"]),
                            confirm_before_starting_next_run=cough_inputs[
                                "confirm_before_starting_next_run"
                            ],
                        )

            # Film mode
            case "film":
                # ------------------------------------------------------
                # Mode: Film
                # ------------------------------------------------------

                # Ask user to start the experiment
                ask_start_confirmation(experiment_name=experiment_name)

                # Record temperature and humidity
                temperature_start, humidity_start = tcm.read_temperature_humidity()

                # Execute repeated runs
                for run_idx in range(cough_inputs["nr_runs"]):
                    # Wait between coughs if needed
                    if run_idx > 0:
                        wait_or_confirm_next_run(
                            next_run_number=(run_idx + 1),
                            nr_runs=cough_inputs["nr_runs"],
                            multi_run_interval_s=float(
                                cough_inputs["multi_run_interval_s"]),
                            confirm_before_starting_next_run=cough_inputs[
                                "confirm_before_starting_next_run"
                            ],
                        )

                    CONNECTION_IP_OPS = "192.168.1.50"
                    PROFILE_PATH_OPS = Path(__file__).resolve(
                    ).parent / "profiles" / "default_minimal.toml"
                    if output_dir is None:
                        raise ValueError(
                            "Output directory is None, cannot save OPS data.")
                    OUT_CSV_OPS = output_dir / \
                        f"OPS_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
                    OUT_CSV_OPS.parent.mkdir(parents=True, exist_ok=True)

                    with OPSClient(ip=CONNECTION_IP_OPS) as client:
                        ops = OPS(client)

                        print("Model:", client.read_model_number())
                        print("Status:", ops.read_status())

                        ops.start_standard_recording(
                            profile_toml_path=PROFILE_PATH_OPS,
                            out_csv_path=OUT_CSV_OPS,
                        )

                        # Wait for the OPS to start recording before triggering the cough machine
                        time.sleep(10)

                        run_log_path = tcm.run(
                            output_dir=output_dir,
                            run_nr_start=(run_idx + 1),
                            save_logs=save_data,
                        )
                        # Cache first run log for the summary plot in finalization
                        if run_idx == 0:
                            first_run_log_path = run_log_path

                        recorded_csv = ops.collect_recording()
                        print(f"Saved data to {recorded_csv}")

            # PIV mode
            case "piv":
                # ------------------------------------------------------
                # Mode: PIV
                # ------------------------------------------------------

                assert pump is not None

                piv_nebuliser_pressure_bar = pump_inputs["piv_nebuliser_pressure_bar"]
                pump_rate_ml_per_min = pump_inputs["pump_rate_ml_per_min"]
                assert piv_nebuliser_pressure_bar is not None
                assert pump_rate_ml_per_min is not None

                # Explicitly require operator confirmation of nebuliser pressure
                confirm_piv_ready = prompt_yes_no(
                    "Press ENTER to confirm the nebuliser is pressurised to "
                    f"{piv_nebuliser_pressure_bar} bar...",
                    default=True,
                )
                if not confirm_piv_ready:
                    print("Aborted.")
                    exit(1)

                # Ask user to start the experiment
                ask_start_confirmation(experiment_name=experiment_name)

                # Record temperature and humidity
                temperature_start, humidity_start = tcm.read_temperature_humidity()

                # Execute configured number of PIV runs with pump start/stop timing
                for run_idx in range(cough_inputs["nr_runs"]):
                    # Start liquid feed before each run
                    pump.infuse(pump_rate_ml_mn=pump_rate_ml_per_min)
                    try:
                        if pump_inputs["piv_pump_start_before_run_s"] > 0:
                            # Optional pre-run pump lead-in time for stable nebulisation
                            print(
                                f"Waiting {pump_inputs['piv_pump_start_before_run_s']} s before run {run_idx + 1}/{cough_inputs['nr_runs']}"
                            )
                            time.sleep(
                                float(pump_inputs["piv_pump_start_before_run_s"]))

                        run_log_path = tcm.run(
                            output_dir=output_dir,
                            run_nr_start=(run_idx + 1),
                            save_logs=save_data,
                        )
                        # Cache first run log for the summary plot in finalization
                        if run_idx == 0:
                            first_run_log_path = run_log_path

                        if pump_inputs["piv_pump_stop_after_run_s"] > 0:
                            # Optional post-run pump tail time
                            print(
                                f"Waiting {pump_inputs['piv_pump_stop_after_run_s']} s after run {run_idx + 1}/{cough_inputs['nr_runs']}"
                            )
                            time.sleep(
                                float(pump_inputs["piv_pump_stop_after_run_s"]))
                    finally:
                        # Always stop pump, even if the run or waits raise an error
                        pump.stop()

                        # Run cleaning routine every cycle
                        tcm.clean()

                    # Skip inter-run wait/confirm prompts after the final run
                    is_last_run = run_idx == (cough_inputs["nr_runs"] - 1)
                    if not is_last_run:
                        wait_or_confirm_next_run(
                            next_run_number=(run_idx + 2),
                            nr_runs=cough_inputs["nr_runs"],
                            multi_run_interval_s=float(
                                cough_inputs["multi_run_interval_s"]),
                            confirm_before_starting_next_run=cough_inputs[
                                "confirm_before_starting_next_run"
                            ],
                        )

        # ------------------------------------------------------------------
        # 5) Finalize run and write artifacts
        # ------------------------------------------------------------------
        if save_data:
            assert output_dir is not None
            if first_run_log_path is not None:
                # Generate a quick diagnostic plot from the first run log
                # TODO: Optionally, plot all run logs
                plot_run_log(
                    run_log_path=first_run_log_path,
                    experiment_dir=output_dir,
                    show=False,
                )

            # Collect comments
            comments = ask_user_for_comments(output_dir=output_dir)

            # Record temperature and humidity
            temperature_finish, humidity_finish = tcm.read_temperature_humidity()
            time_finish = timestamp_str()

            # Optional SprayTec post-processing.
            if record_droplet_size:
                assert spraytec is not None
                prompt_yes_no(
                    "Press ENTER if the SprayTec has finished processing and exporting the measurement(s)...",
                    default=True,
                )
                # TODO: Add some print statements in save_data so user is not wondering what is going on.
                spraytec_audit_path = spraytec.save_data(append_file_path=spraytec_inputs["append_file_path"],
                                                         start_time=time_start,
                                                         debug=cough_inputs["debug_mode"],
                                                         offer_archive_if_large=True,
                                                         )

            # Group run-level values in one dictionary to keep metadata wiring compact
            # Add new run-wide metadata values here
            run_context = {
                "config_file_path": exp_conf["config_file_path"],
                "time_start": time_start,
                "time_finish": time_finish,
                "experiment_name": experiment_name,
                "experiment_mode": experiment_mode,
                "output_dir": output_dir,
                "wait_before_run_us": wait_before_run_us,
                "temperature_start": temperature_start,
                "humidity_start": humidity_start,
                "temperature_finish": temperature_finish,
                "humidity_finish": humidity_finish,
                "comments": comments,
            }

            # Group device/config values separately for easier extension per device
            # Add device-specific metadata values here
            device_context = {
                "tcm": tcm,
                "cough_machine_inputs": cough_machine_inputs,
                "pump": pump,
                "pump_inputs": pump_inputs,
                "record_droplet_size": record_droplet_size,
                "spraytec_inputs": spraytec_inputs,
                "spraytec_x_mm": spraytec_x_mm,
                "spraytec_y_mm": spraytec_y_mm,
                "spraytec_z_mm": spraytec_z_mm,
                "spraytec_audit_path": spraytec_audit_path,
                "spraytec_laser_intensity": spraytec_laser_intensity,
                "lift_pos_z_mm": lift_pos_z_mm,
                "stage_pos_x_mm": stage_pos_x_mm,
                "stage_pos_y_mm": stage_pos_y_mm,
                "spraytec_target_z_mm": spraytec_target_z_mm,
                "lift": lift,
            }

            metadata = logger.build_run_metadata(
                run_context=run_context,
                cough_inputs=cough_inputs,
                device_context=device_context,
            )
            # Persist full run metadata snapshot.
            logger.write_run_metadata(
                experiment_dir=output_dir, metadata=metadata)

            print("Experiment completed, all data saved to ", output_dir)
            print("Exiting.")
        else:
            print("Experiment completed.")
            if not save_data:
                print("No data was saved (series_directory='None').")
            print("Exiting.")

    # ------------------------------------------------------------------
    # 6) Clear interrupt-handling references and return
    # ------------------------------------------------------------------

    # Clear registered devices after a normal, successful run.
    set_active_tcm(None)
    set_active_pump(None)
    set_active_output_dir(None)

    # Return output directory
    return output_dir
