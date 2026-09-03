"""Main experiment runner for the Twente Cough Machine."""

import time
from pathlib import Path

from typing import Optional

from tcm_control.devices import CoughMachine, VerticalStage, SyringePump, SprayTec, Camera, SyringePump2
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
    wait_with_progress,
    beep,
)
from tcm_utils.time_utils import timestamp_str
from tcm_control.thin_film import take_snapshot, tube_cleaning, make_layer
from tcm_control.film_height import determine_film_height, determine_plate_height


def cough(config_path: Path | str | None = None) -> Optional[Path]:
    """Run a full experiment using a TOML configuration.

    Args:
        config_path: Optional TOML path. If omitted, a file picker opens.

    Returns:
        The experiment output directory path, or None when saving is disabled.
    """
    # --------------------------------------------------------------------------
    # 0) Set up logging and interrupt handling
    # --------------------------------------------------------------------------

    # Set up logger to write all terminal prints to a file when saving is
    # enabled, start in temporary location until experiment folder is created
    console_log = logger.ConsoleLogCapture(
        logger.create_pending_console_log_path())

    # Reset interrupt state for a fresh run and clear stale references.
    reset_interrupt_cleanup_state()
    set_active_tcm(None)
    set_active_pump(None)
    set_active_output_dir(None)

    print("Starting cough machine experiment, "
          "press Ctrl+C at any time to abort and safely exit")

    # --------------------------------------------------------------------------
    # 1) Load and validate config file & variables
    # --------------------------------------------------------------------------

    # Load the experiment config from the TOML file and validate it
    config = load_experiment_config(config_path)

    # Split the normalized config into local sections used throughout this run
    exp_conf = config["experiment"]
    cough_inputs = config["inputs"]["cough"]
    cough_machine_inputs = config["devices"]["cough_machine"]["inputs"]
    tank_inputs = cough_machine_inputs["tank"]
    cleaning_inputs = cough_machine_inputs["cleaning"]
    nebuliser_inputs = cough_machine_inputs["nebuliser"]
    pump_inputs = config["devices"]["pump"]["inputs"]
    camera_inputs = config["devices"]["camera"]["inputs"]
    vertical_stage_inputs = config["devices"]["vertical_stage"]["inputs"]
    spraytec_inputs = config["devices"]["spraytec"]["inputs"]

    # Default to saving unless config explicitly disables it
    save_data = bool(exp_conf.get("save_data", True))

    # Cache the selected mode for the central match/case branch below
    experiment_mode = exp_conf["mode"]

    # Toggle for optional SprayTec setup and post-processing branches
    record_droplet_size = bool(cough_inputs["record_droplet_size"])

    # Host-level pre-trigger delay that is sent to the cough machine
    wait_before_run_us = cough_machine_inputs["wait_before_run_us"]

    # Initialise variables
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

    # --------------------------------------------------------------------------
    # 2) Make connections to external devices
    # --------------------------------------------------------------------------

    # Initialise cough machine
    tcm = CoughMachine(debug=cough_inputs["debug_mode"])

    # TODO: temporarily added nebuliser on separate MCU
    neb = CoughMachine(
        debug=cough_inputs["debug_mode"], expected_id="NEB_control",
        name="Nebuliser_MCU", supported_protocol_version=6)

    # Register device so interrupt cleanup can call quit() on it
    set_active_tcm(tcm)

    # Vertical stage is only needed when SprayTec measurements are enabled.
    if record_droplet_size:
        lift = VerticalStage()

    # --------------------------------------------------------------------------
    # 3) Set up experiment directory and logging
    # --------------------------------------------------------------------------

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

        latest_experiment_name = logger.latest_experiment_display_name(
            series_directory)
        experiment_prompt = "Enter experiment name: "
        if latest_experiment_name is not None:
            experiment_prompt = (
                "Enter experiment name "
                f"(latest in series: {latest_experiment_name}): "
            )
    else:
        # If data is not being saved, we don't need a series directory
        series_directory = None
        experiment_prompt = "Enter experiment name: "
        # Keep a clear runtime message when the run is intentionally non-persistent
        print("Data saving disabled via config setting series_directory='None'.")

    # Ensure the experiment name is never empty because it is used in
    # folder naming and prints
    experiment_name = ensure_non_empty_text(
        exp_conf["name"],
        prompt=experiment_prompt,
        empty_error="Experiment name cannot be empty.",
    )

    # Capture run start timestamp once and reuse it across artifacts and metadata
    time_start = timestamp_str()
    output_dir: Optional[Path] = None
    console_log_path: Optional[Path] = None
    if save_data:
        assert series_directory is not None
        assert console_log is not None
        # Create output directory for this experiment.
        output_dir = logger.create_experiment_dir(
            series_directory, experiment_name, start_time=time_start)
        logger.copy_experiment_config(
            experiment_dir=output_dir,
            config_path=exp_conf["config_file_path"],
        )
        # Register folder globally so Ctrl+C cleanup can optionally remove it
        set_active_output_dir(output_dir)

        # Move the temp console log into the experiment folder now that it exists
        console_log_path = console_log.relocate(
            logger.create_console_log_path(output_dir))
        print(f"Session console log file: {console_log_path}")
    else:
        # No output directory exists in non-saving mode
        set_active_output_dir(None)

    # TODO: Check whether this try-finally clause is still needed
    try:

        # --------------------------------------------------------------
        # 4) Set up devices and resolve run geometry
        # --------------------------------------------------------------

        # In droplet and PIV modes, set up the pump
        # if experiment_mode in ["droplet", "piv"]:
        #     pump = SyringePump(
        #         syringe_volume_ml=pump_inputs["syringe_volume_ml"],
        #         syringe_diameter_mm=pump_inputs["syringe_diameter_mm"],
        #     )

        #     # Register pump so interrupt cleanup can call stop() on it
        #     set_active_pump(pump)

        tcm.load_flowcurve(
            csv_path=cough_machine_inputs["flow_curve_csv_path"],
            experiment_dir=output_dir if save_data else None,
        )
        tcm.set_wait_us(wait_us=wait_before_run_us)
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
        # Store the resolved flow curve path for metadata traceability.
        cough_machine_inputs["flow_curve_csv_path"] = tcm.get_flowcurve_csv_path(
        )

        # In film mode, set up the camera and pump
        if experiment_mode == "film":
            # Make a subfolder in output dir for camera outputs
            camera_output_dir = output_dir / "camera" if output_dir is not None else None
            if camera_output_dir is not None:
                camera_output_dir.mkdir(exist_ok=True)
            camera = Camera(exposure_us=camera_inputs["camera_exposure_us"],
                            output_dir=camera_output_dir)
            pump = SyringePump2(pump_inputs)

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

        match experiment_mode:
            case "droplet":
                # ------------------------------------------------------------------
                # 5A) Droplet atomisation mode
                # ------------------------------------------------------------------
                raise NotImplementedError("W.I.P.")

                #     assert pump is not None

                #     # Wait for user to start the experiment
                #     ask_start_confirmation(experiment_name=experiment_name)

                #     # Record temperature and humidity
                #     temperature_start, humidity_start = tcm.read_temperature_humidity()

                #     # Execute configured number of single-cough runs
                #     for run_idx in range(cough_inputs["nr_runs"]):
                #         # Turn on syringe pump
                #         pump.infuse(
                #             pump_rate_ml_mn=pump_inputs["pump_rate_ml_per_min"])

                #         # Optionally let pump run before recording
                #         nr_droplets_to_skip = pump_inputs[
                #             "nr_droplets_to_skip_before_recording"
                #         ]
                #         if nr_droplets_to_skip > 0:
                #             print("Flushing before starting cough")
                #             tcm.count_droplets(
                #                 nr_droplets=nr_droplets_to_skip, let_drip=True)

                #         # Then go into droplet detection mode
                #         saved_run_log_paths = tcm.detect_droplets_and_run(
                #             nr_runs=1,
                #             output_dir=output_dir,
                #             run_nr_start=(run_idx + 1),
                #             save_logs=save_data,
                #         )

                #         # Turn off pump
                #         pump.stop()

                #         # Skip inter-run wait/confirm prompts after the final run
                #         is_last_run = run_idx == (cough_inputs["nr_runs"] - 1)
                #         if not is_last_run:
                #             wait_or_confirm_next_run(
                #                 next_run_number=(run_idx + 2),
                #                 nr_runs=cough_inputs["nr_runs"],
                #                 multi_run_interval_s=float(
                #                     cough_inputs["multi_run_interval_s"]),
                #                 confirm_before_starting_next_run=cough_inputs[
                #                     "confirm_before_starting_next_run"
                #                 ],
                #             )

            case "film":
                # ------------------------------------------------------------------
                # 5B) Film atomisation mode
                # ------------------------------------------------------------------

                # Ask user to start the experiment
                ask_start_confirmation(experiment_name=experiment_name)

                # Record temperature and humidity
                temperature_start, humidity_start = tcm.read_temperature_humidity(
                    show_reading=True,
                )

                # Execute repeated runs
                for run_idx in range(cough_inputs["nr_runs"]):
                    # Initial picture
                    background_path = take_snapshot(camera, tcm)
                    if camera_output_dir is not None:
                        plate_height_px = determine_plate_height(
                            background_path, camera_output_dir)

                    # Make a layer
                    make_layer(pump)  # type: ignore

                    # Take a picture of the layer
                    thin_film_path = take_snapshot(camera, tcm)
                    if camera_output_dir is not None:
                        film_height_px = determine_film_height(
                            thin_film_path, plate_height_px, camera_output_dir)
                        film_height_mm = film_height_px / \
                            camera_inputs["pixel_per_meter"] * 1000
                        print(f"Film height (mm): {film_height_mm:.3f}")

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

                    # Produce a cough
                    run_log_path = tcm.run(
                        output_dir=output_dir,
                        run_nr_start=(run_idx + 1),
                        save_logs=save_data,
                    )

                    # Plot run log
                    if save_data and run_log_path is not None:
                        plot_run_log(
                            run_log_path=run_log_path,
                            experiment_dir=output_dir,
                            show=False,
                        )

                    # Clean the channel
                    tcm.clean(
                        clean_pressure_bar=cleaning_inputs["clean_pressure_bar"],
                        valve_open_duration_s=cleaning_inputs["valve_open_duration_s"],
                        dry_pressure_bar=cleaning_inputs["dry_pressure_bar"],
                        dry_duration_s=cleaning_inputs["dry_duration_s"],
                        dry_valve_current_ma=cleaning_inputs["dry_valve_current_ma"],
                        cycle_count=cleaning_inputs["cycle_count"],
                    )

                    # Image the channel after cleaning
                    _ = take_snapshot(camera, tcm)

            case "piv":
                # ------------------------------------------------------------------
                # 5C) PIV mode
                # ------------------------------------------------------------------

                # Initialise nebuliser parameters
                nebuliser_pressure_bar = nebuliser_inputs["pressure_bar"]
                nebuliser_fill_time_s = nebuliser_inputs["fill_time_s"]

                # FIRST RUN
                # Ask for confirmation that the laser is turned on
                # prompt_yes_no(
                #     "Press ENTER to confirm that the PIV laser is turned on...")

                # Fill the nebuliser tank
                neb.set_nebuliser(True)
                wait_with_progress(
                    wait_s=nebuliser_fill_time_s,
                    label="Filling nebuliser tank...",
                )

                # Ask user to start the experiment
                ask_start_confirmation(experiment_name=experiment_name)
                # countdown_beep()

                # Record temperature and humidity
                temperature_start, humidity_start = tcm.read_temperature_humidity(
                    show_reading=True,
                )

                # Execute configured number of PIV runs with pump start/stop timing
                for run_idx in range(cough_inputs["nr_runs"]):

                    # FROM SECOND RUN ONWARDS
                    if run_idx > 0:
                        # Before each run, fill the nebuliser tank again
                        neb.set_nebuliser(True)
                        wait_with_progress(
                            wait_s=nebuliser_fill_time_s,
                            label="Filling nebuliser tank...",
                        )

                        # Confirm before starting next run
                        wait_or_confirm_next_run(
                            next_run_number=(run_idx + 1),
                            nr_runs=cough_inputs["nr_runs"],
                            multi_run_interval_s=float(
                                cough_inputs["multi_run_interval_s"]),
                            confirm_before_starting_next_run=cough_inputs[
                                "confirm_before_starting_next_run"
                            ],
                        )

                    # ALL RUNS
                    # Start seeding air flow
                    beep()
                    print("Turning on nebuliser air flow")
                    neb.set_nebuliser_pressure(nebuliser_pressure_bar)
                    pump_stopped = False

                    # If an error occurs, the nebuliser will always be turned off
                    # TODO: This should be part of the cough machine cleanup routine
                    try:

                        # Optional pre-run pump lead-in time for stable nebulisation
                        if pump_inputs["piv_pump_start_before_run_s"] > 0:
                            print(
                                f"Waiting {pump_inputs['piv_pump_start_before_run_s']} s before run {run_idx + 1}/{cough_inputs['nr_runs']}"
                            )
                            time.sleep(
                                float(pump_inputs["piv_pump_start_before_run_s"]))

                        # Start the run
                        tcm.start_run()
                        tcm.wait_for_run_finished()

                        # Optional post-run pump tail time after actuation finishes
                        if pump_inputs["piv_pump_stop_after_run_s"] > 0:
                            print(
                                f"Waiting {pump_inputs['piv_pump_stop_after_run_s']} s after run {run_idx + 1}/{cough_inputs['nr_runs']}"
                            )
                            time.sleep(
                                float(pump_inputs["piv_pump_stop_after_run_s"]))

                        # Turn off nebuliser
                        neb.set_nebuliser(False)
                        print("Turning off nebuliser air flow")
                        neb.set_nebuliser_pressure(0.0)
                        pump_stopped = True

                        run_log_path = tcm.receive_run_log(
                            output_dir=output_dir,
                            run_nr_start=(run_idx + 1),
                            save_logs=save_data,
                        )

                        # Plot run log
                        if save_data and run_log_path is not None:
                            plot_run_log(
                                run_log_path=run_log_path,
                                experiment_dir=output_dir,
                                show=False,
                            )

                    finally:
                        # Always stop pump, even if the run or waits raise an error
                        if not pump_stopped:
                            neb.set_nebuliser_pressure(0.0)
                            neb.set_nebuliser(False)

                        # Flush nebuliser chamber before cleaning channel
                        neb.set_nebuliser_pressure(0.3)
                        wait_with_progress(
                            wait_s=10, label="Flushing nebuliser chamber...")
                        neb.set_nebuliser_pressure(0.0)

                        # Run cleaning routine every cycle
                        tcm.clean(clean_pressure_bar=cleaning_inputs["clean_pressure_bar"],
                                  valve_open_duration_s=cleaning_inputs["valve_open_duration_s"],
                                  dry_pressure_bar=cleaning_inputs["dry_pressure_bar"],
                                  dry_duration_s=cleaning_inputs["dry_duration_s"],
                                  dry_valve_current_ma=cleaning_inputs["dry_valve_current_ma"],
                                  cycle_count=cleaning_inputs["cycle_count"])

        # ------------------------------------------------------------------
        # 6) Finalize run and write (meta)data
        # ------------------------------------------------------------------
        if save_data:
            assert output_dir is not None

            # Collect comments
            comments = ask_user_for_comments(output_dir=output_dir)

            # Record temperature and humidity
            temperature_finish, humidity_finish = tcm.read_temperature_humidity(
                show_reading=True,
            )
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
                "thin_film_height_mm": film_height_mm if experiment_mode == "film" else None,
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
    finally:
        # TODO: Check whether this try-finally clause is still needed
        if console_log is not None:
            console_log.close()

    # ------------------------------------------------------------------
    # 7) Clear interrupt-handling references and return
    # ------------------------------------------------------------------

    # When not saving data, remove the temporary console log file to avoid cluttering the working directory
    if not save_data and console_log is not None:
        console_log.remove()

    # Clear registered devices after a normal, successful run.
    set_active_tcm(None)
    set_active_pump(None)
    set_active_output_dir(None)

    # Return output directory
    return output_dir
