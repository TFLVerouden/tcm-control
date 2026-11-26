"""Main experiment runner for the Twente Cough Machine."""

import time
from pathlib import Path
from typing import Optional

from tcm_control.devices import CoughMachine, VerticalStage, SprayTec, Camera, SyringePump, OpticalParticleSizer
from tcm_control.devices.spraytec import warn_if_experiment_dir_name_too_long
from tcm_control import logger
from tcm_control.initialise_config import load_experiment_config, resolve_tube_cleaning
from tcm_control.interrupt_handling import (
    reset_interrupt_cleanup_state,
    set_active_output_dir,
    set_active_pump,
    set_active_tcm,
)
from tcm_control.post_processing.run_log_processing import plot_run_log, plot_cough_machine_timing
from tcm_control.imaging import layer_preview, take_snapshot, wait_with_preview
from tcm_control.liquid_film import (
    make_liquid_film,
    measure_film_properties,
    measure_plate_height,
)
from tcm_control.user_input import (
    ask_start_confirmation,
    ask_user_for_comments,
    set_spraytec_pos,
    wait_or_confirm_next_run,
)
from tcm_utils.file_dialogs import ensure_directory_path
from tcm_utils.io_utils import (
    prompt_input,
    prompt_yes_no,
    wait_with_progress,
    beep,
    export_all_pdfs_to_pngs_in_directory,
)
from tcm_utils.time_utils import timestamp_str
from tcm_utils.io_utils import countdown_beep


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

    # Cache the selected mode for the central match/case branch below
    experiment_mode = config["experiment"]["mode"]
    save_data = config["experiment"]["save_data"]

    record_droplet_size_spraytec = config["devices"]["spraytec"]["enabled"]
    record_droplet_size_ops = config["devices"]["ops"]["enabled"]
    if record_droplet_size_ops and experiment_mode == "film" and not save_data:
        raise ValueError(
            "OPS recording requires an experiment output directory.")

    fan_off = config["run"]["fan_off_during_experiment"]

    # Cleaning settings
    cleaning_inputs = config["run"]["cleaning"]

    # --------------------------------------------------------------------------
    # 2) Make connection to cough machine
    # --------------------------------------------------------------------------

    # Initialise cough machine
    cough_inputs = config["run"]
    tcm = CoughMachine(debug=cough_inputs["debug_mode"])

    # If set up, turn off fan during experiment to prevent extra airflow
    if fan_off:
        print("Turning off electronics box fan during experiment")
        tcm.set_fan_speed(CoughMachine.FAN_SPEED_OFF)
    else:
        tcm.set_fan_speed(CoughMachine.FAN_SPEED_DEFAULT)

    # Register device so interrupt cleanup can stop it
    set_active_tcm(tcm)

    # --------------------------------------------------------------------------
    # 3) Set up experiment directory and logging
    # --------------------------------------------------------------------------

    if save_data:
        # Resolve and validate the root folder where this experiment run will be stored
        series_directory = ensure_directory_path(
            config["experiment"]["series_directory"],
            key="tcm_series_directory",
            title="Select series directory",
            start=Path(__file__).resolve().parent,
        )
        if series_directory is None:
            raise SystemExit("No series directory selected.")

        latest_experiment_name = logger.latest_experiment_display_name(
            series_directory)
        experiment_prompt = "Enter experiment name"
        if latest_experiment_name is not None:
            experiment_prompt = (
                "Enter experiment name "
                f"(latest in series: {latest_experiment_name})"
            )
    else:
        # If data is not being saved, we don't need a series directory or name
        series_directory = None
        experiment_prompt = ""
        print("Data saving disabled via config setting experiment.save_data=false.")

    if save_data:
        experiment_name = config["experiment"]["name"]
        if experiment_name is None:
            prompt = experiment_prompt or "Enter experiment name"
            experiment_name = prompt_input(
                f"{prompt} (optional; press ENTER to skip): ",
                value_type="string",
            ).strip() or None
    else:
        experiment_name = None
    config["experiment"]["name"] = experiment_name

    # Capture run start timestamp once and reuse it across artifacts and metadata
    time_start = timestamp_str()
    output_dir: Optional[Path] = None
    console_log_path: Optional[Path] = None
    if save_data:
        assert series_directory is not None
        assert console_log is not None
        if record_droplet_size_spraytec and experiment_name is not None:
            # Warn (but proceed) if SprayTec won't be able to display the full name
            warn_if_experiment_dir_name_too_long(time_start, experiment_name)
        # Create output directory for this experiment.
        output_dir = logger.create_experiment_dir(
            series_directory, experiment_name, start_time=time_start)
        logger.copy_experiment_config(
            experiment_dir=output_dir,
            config_path=config["experiment"]["config_file_path"],
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

    # Devices must be available to cleanup even if setup fails
    ops = None
    pump = None
    camera = None
    vertical_stage = None

    # Enter the main experiment try/finally block to ensure cleanup occurs even if an error occurs
    try:

        # Persist an initial metadata snapshot in case experiment is interrupted
        if output_dir is not None:
            logger.write_run_metadata(
                output_dir, logger.build_run_metadata(
                    config, time_start=time_start, output_dir=output_dir, tcm=tcm),
                title="Initial run metadata snapshot",)

        # ----------------------------------------------------------------------
        # 4) Set up external device connections
        # ----------------------------------------------------------------------

        # Connect to camera in film mode only
        if experiment_mode == "film":
            # The camera output directory is changed to the current run below
            camera_inputs = config["devices"]["camera"]
            camera_output_dir = output_dir
            camera = Camera(exposure_us=camera_inputs["camera_exposure_us"],
                            output_dir=camera_output_dir,
                            roi=camera_inputs["roi"],
                            flip=camera_inputs["flip"],
                            gain_db=camera_inputs["camera_gain_db"])
            camera.open()
            # Record any camera values clamped to device limits
            camera_inputs["camera_exposure_us"] = camera.exposure_us
            camera_inputs["camera_gain_db"] = camera.gain_db

        # Connect to syringe pump in film and droplet modes
        if experiment_mode in ["film", "droplet"]:
            syringe_inputs = config["devices"]["syringe_pump"]
            pump = SyringePump(syringe_inputs["syringe_vendor_code"],
                               syringe_inputs["syringe_volume_mL"],
                               syringe_inputs["syringe_diameter_mm"],
                               syringe_inputs["syringe_gang"],
                               syringe_inputs["syringe_force_percent"])

            set_active_pump(pump)

        # Connect to OPS when specified
        ops_inputs = config["devices"]["ops"]
        if record_droplet_size_ops:
            assert ops_inputs is not None
            ops = OpticalParticleSizer(
                bin_boundaries_um=ops_inputs["bin_boundaries_um"],
                alarm_threshold=ops_inputs["alarm_threshold"],
            )
            ops_position = config["geometry"]["ops"]["position"] or prompt_input(
                "Describe the OPS position and press ENTER: ", value_type="string"
            )
            config["geometry"]["ops"]["position"] = ops_position

        # Set up SprayTec and position if enabled
        vertical_stage = None
        spraytec = None
        spraytec_x_mm = spraytec_y_mm = spraytec_z_mm = None
        stage_pos_z_mm = spraytec_laser_intensity = None
        if record_droplet_size_spraytec:
            spraytec_inputs = config["devices"]["spraytec"]
            spraytec_geometry = config["geometry"]["spraytec"]
            # Vertical stage is only needed when SprayTec measurements are enabled.
            vertical_stage = VerticalStage()
            spraytec_x_mm, spraytec_y_mm, spraytec_z_mm, stage_pos_x_mm, stage_pos_y_mm, spraytec_target_z_mm, stage_pos_z_mm = set_spraytec_pos(
                vertical_stage,
                spraytec_geometry["tcm_trachea_exit_to_ref_x_mm"],
                spraytec_geometry["tcm_trachea_exit_to_ref_y_mm"],
                spraytec_geometry["spraytec_to_ref_x_mm"],
                spraytec_geometry["spraytec_to_ref_y_mm"],
                spraytec_geometry["tcm_trachea_bottom_z_mm"],
                spraytec_geometry["tcm_trachea_height_mm"],
                spraytec_geometry["lift_zero_z_mm"],
                spraytec_geometry["table_height_mm"],
                spraytec_geometry["spraytec_to_lift_z_mm"],
                spraytec_geometry["stage_pos_x_zero_mm"],
                spraytec_geometry["stage_pos_y_zero_mm"],
                spraytec_target_z_mm=spraytec_geometry["position"]["spraytec_target_z_mm"],
                stage_pos_x_mm=spraytec_geometry["position"]["stage_pos_x_mm"],
                stage_pos_y_mm=spraytec_geometry["position"]["stage_pos_y_mm"],
            )
            # Persist resolved/manual stage inputs for traceability in metadata.
            spraytec_geometry["position"]["stage_pos_x_mm"] = stage_pos_x_mm
            spraytec_geometry["position"]["stage_pos_y_mm"] = stage_pos_y_mm
            spraytec_geometry["position"]["spraytec_target_z_mm"] = spraytec_target_z_mm

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

        # ----------------------------------------------------------------------
        # 5) Configure cough machine
        # ----------------------------------------------------------------------

        # Clear memory before starting the experiment; turn off fan
        tcm.clear_memory()

        # Load flow curve
        cough_machine_inputs = config["run"]
        tcm.load_flowcurve(
            csv_path=cough_machine_inputs["flow_curve_csv_path"],
            experiment_dir=output_dir if save_data else None,
        )
        # Store the resolved flow curve path for metadata traceability.
        cough_machine_inputs["flow_curve_csv_path"] = tcm.get_flowcurve_csv_path(
        )

        # Program the fixed pre-run wait into the cough machine controller
        tcm.set_wait_us(wait_us=cough_machine_inputs["wait_before_run_us"])

        # Set tank pressure
        tank_inputs = cough_machine_inputs["tank"]
        tcm.set_pressure(
            tank_inputs["pressure_bar"],
            timeout_s=tank_inputs["settling_time_s"],
            avg_window_s=tank_inputs["avg_window_s"],
            tolerance_bar=tank_inputs["tolerance_bar"],
            poll_interval_s=tank_inputs["poll_interval_s"],
            interm_press_diff_bar=tank_inputs["intermediate_diff_bar"],
            interm_press_time_s=tank_inputs["intermediate_time_s"],
        )
        # Record the averaging window actually used by the controller helper
        if tank_inputs["settling_time_s"] <= tank_inputs["avg_window_s"]:
            tank_inputs["avg_window_s"] = tank_inputs["settling_time_s"] / 2

        # Save resolved setup values before starting the first run
        if output_dir is not None:
            logger.write_run_metadata(output_dir, logger.build_run_metadata(
                config, time_start=time_start, output_dir=output_dir, tcm=tcm,
                pump=pump, camera=camera, ops=ops, spraytec=spraytec,
                vertical_stage=vertical_stage,
                spraytec_x_mm=spraytec_x_mm, spraytec_y_mm=spraytec_y_mm,
                spraytec_z_mm=spraytec_z_mm, spraytec_laser_intensity=spraytec_laser_intensity,
                stage_pos_z_mm=stage_pos_z_mm,
            ))

        # Track run folders and cleaning settings shared by film and PIV modes
        run_dirs: list[Path] = []

        # Protocols for each mode
        match experiment_mode:
            case "droplet":
                # --------------------------------------------------------------
                # 6A) Droplet atomisation mode
                # --------------------------------------------------------------

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
                # --------------------------------------------------------------
                # 6B) Film atomisation mode
                # --------------------------------------------------------------

                # PREPARATIONS =================================================
                # Explicitly require operator confirmation of syringe being filled
                layer_inputs = config["film"]["layer"]
                if not prompt_yes_no(
                    "Press ENTER to confirm the syringe is filled with > "
                    f"{layer_inputs['infuse_volume_ml']} mL...",
                    default=True,
                ):
                    print("Aborted.")
                    exit(1)

                # Ask for cleaning protocol
                if config["film"]["clean_tube"]["repetitions"] > 0 and prompt_yes_no(
                    "Clean the tubes before starting the experiment? (press ENTER to confirm, type 'n' to skip)",
                        default=True) and pump is not None:
                    if pump is not None:

                        # Resolve tube-cleaning settings only when cleaning is selected
                        cleaning_tube_inputs = resolve_tube_cleaning(
                            config["film"]["clean_tube"])
                        config["film"]["clean_tube"] = cleaning_tube_inputs

                        # Clean the tubes
                        pump.clean_tubes(volume_ml_layer=cleaning_tube_inputs["volume_ml_layer"],
                                         rate_ml_min_layer=cleaning_tube_inputs["rate_ml_min_layer"],
                                         volume_ml_repetition=cleaning_tube_inputs["volume_ml_repetition"],
                                         rate_ml_min_repetition=cleaning_tube_inputs["rate_ml_min_repetition"],
                                         repetitions=cleaning_tube_inputs["repetitions"])

                        # Clean the channel afterwards
                        tcm.clean(
                            clean_pressure_bar=cleaning_inputs["clean_pressure_bar"],
                            clean_valve_open_duration_s=cleaning_inputs["valve_open_duration_s"],
                            clean_cycle_count=cleaning_inputs["cycle_count"],
                            dry_pressure_bar=cleaning_inputs["dry_pressure_bar"],
                            dry_duration_s=cleaning_inputs["dry_duration_s"],
                            dry_valve_current_ma=cleaning_inputs["dry_valve_current_ma"],
                        )

                # Assert the camera is assigned
                assert camera is not None, "Camera must be initialized in film mode"

                # RUNS =========================================================
                # Execute repeated runs
                for run_idx in range(cough_inputs["nr_runs"]):
                    # Create the folder for this run and direct its images there
                    run_dir = logger.create_run_dir(
                        output_dir, run_idx + 1, cough_inputs["nr_runs"])
                    if run_dir is not None:
                        run_dirs.append(run_dir)
                        camera_output_dir = run_dir / "camera"
                        camera.output_dir = camera_output_dir

                    # Empty channel "background" picture
                    empty_channel_image_path = take_snapshot(
                        camera, tcm, filename="empty_channel")
                    live_preview = camera_inputs["live_preview"]
                    if camera_output_dir is not None or live_preview:
                        plate_measurement = measure_plate_height(
                            empty_channel_image_path)

                    # Make a layer with live preview
                    if live_preview and pump is not None:
                        with layer_preview(camera, tcm, plate_measurement,
                                           camera_inputs["scale_mm_per_px"]) as preview:
                            try:
                                make_liquid_film(
                                    pump, camera, tcm,
                                    infuse_volume_ml=layer_inputs["infuse_volume_ml"],
                                    infuse_rate_ml_min=layer_inputs["infuse_rate_ml_min"],
                                    withdraw_volume_ml=layer_inputs["withdraw_volume_ml"],
                                    withdraw_rate_ml_min=layer_inputs["withdraw_rate_ml_min"],
                                    settling_time_s=layer_inputs["film_settling_time_s"],
                                    preview=preview,
                                )
                            except BaseException:
                                try:
                                    pump.stop()
                                except Exception as exc:
                                    print(
                                        f"Warning: Failed to stop syringe pump: {exc}")
                                raise

                    # Or just make a layer
                    else:
                        if pump is not None:
                            make_liquid_film(
                                pump, camera, tcm,
                                infuse_volume_ml=layer_inputs["infuse_volume_ml"],
                                infuse_rate_ml_min=layer_inputs["infuse_rate_ml_min"],
                                withdraw_volume_ml=layer_inputs["withdraw_volume_ml"],
                                withdraw_rate_ml_min=layer_inputs["withdraw_rate_ml_min"],
                                settling_time_s=layer_inputs["film_settling_time_s"],
                            )

                    # Take a picture of the layer
                    final_film_image_path = take_snapshot(
                        camera, tcm, filename=f"final_film")
                    if camera_output_dir is not None:
                        film_height_mm, film_error_mm, contact_angle_deg, film_level_px = measure_film_properties(
                            final_film_image_path, plate_measurement,
                            camera_inputs["scale_mm_per_px"], camera_output_dir)
                        plate_height_px, plate_std_px, _, _, _ = plate_measurement
                        film_measurement = {
                            "time": timestamp_str(),
                            "plate_height_px": plate_height_px,
                            "plate_height_std_px": plate_std_px,
                            "film_level_px": film_level_px,
                            "film_height_mm": film_height_mm,
                            "film_height_error_mm": film_error_mm,
                            "contact_angle_deg": contact_angle_deg,
                        }
                        # Save the individual measurement alongside the images
                        assert run_dir is not None
                        logger.write_film_measurement(
                            run_dir, film_measurement)
                        print(
                            f"Film height (mm): {film_height_mm:.3f} +/- {film_error_mm:.3f}")
                        print(f"Contact angle (deg): {contact_angle_deg:.2f}")

                    # Wait between coughs if needed
                    if run_idx == 0:
                        # Ask user to start the experiment
                        ask_start_confirmation(experiment_name=experiment_name)

                        # Record temperature and humidity at the start of the series of runs
                        temperature_start, humidity_start = tcm.read_temperature_humidity(
                            show_reading=True,
                        )
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
                    # Start OPS recording
                    if ops is not None:
                        assert run_dir is not None and ops_inputs is not None
                        ops.start_recording(run_dir)
                        wait_with_progress(
                            wait_s=ops_inputs["pre_run_s"],
                            label="Recording OPS before cough...",
                        )
                        ops.check_recording()

                    try:
                        countdown_beep()

                        # Record the ambient conditions immediately before the cough
                        temperature, humidity = tcm.read_temperature_humidity(
                            show_reading=True,
                        )
                        if run_dir is not None:
                            logger.write_ambient_measurement(
                                run_dir, temperature, humidity)

                        # Start run, wait to finish, collect OPS data and receive run log
                        if ops is not None:
                            assert ops_inputs is not None
                            ops.check_recording()
                            tcm.start_run()
                            tcm.wait_for_run_finished()
                            ops.finish_after(ops_inputs["post_run_s"])
                            run_log_path = tcm.receive_run_log(
                                output_dir=run_dir,
                                run_nr_start=(run_idx + 1),
                                save_logs=save_data,
                            )
                            ops.collect_recording()
                        else:
                            run_log_path = tcm.run(
                                output_dir=run_dir,
                                run_nr_start=(run_idx + 1),
                                save_logs=save_data,
                            )
                    finally:
                        if ops is not None:
                            ops.stop_if_recording()

                    # POST-RUN =================================================
                    # Plot run log
                    if save_data and run_log_path is not None:
                        plot_run_log(
                            run_log_path=run_log_path,
                            experiment_dir=run_dir,
                            show=False,
                        )
                        plot_cough_machine_timing(
                            run_log_path=run_log_path,
                            experiment_dir=run_dir,
                            show=False,
                        )

                    # Clean the channel
                    tcm.clean(
                        clean_pressure_bar=cleaning_inputs["clean_pressure_bar"],
                        clean_valve_open_duration_s=cleaning_inputs["valve_open_duration_s"],
                        clean_cycle_count=cleaning_inputs["cycle_count"],
                        dry_pressure_bar=cleaning_inputs["dry_pressure_bar"],
                        dry_duration_s=cleaning_inputs["dry_duration_s"],
                        dry_valve_current_ma=cleaning_inputs["dry_valve_current_ma"],
                    )

                    # Image the channel after cleaning only if cycle count > 0
                    if cleaning_inputs["cycle_count"] > 0:
                        take_snapshot(camera, tcm, filename="cleaned_channel")

            case "piv":
                # ------------------------------------------------------------------
                # 5C) PIV mode
                # ------------------------------------------------------------------

                # Initialise nebuliser parameters
                nebuliser_inputs = config["piv"]["nebuliser"]
                nebuliser_pressure_bar = nebuliser_inputs["pressure_bar"]
                nebuliser_fill_time_s = nebuliser_inputs["fill_time_s"]

                # FIRST RUN
                # Ask for confirmation that the laser is turned on
                prompt_yes_no(
                    "Press ENTER to confirm that the PIV laser is turned on...")

                # Fill the nebuliser tank
                tcm.set_nebuliser(True)
                wait_with_progress(
                    wait_s=nebuliser_fill_time_s,
                    label="Filling nebuliser tank...",
                )

                # Ask user to start the experiment
                # ask_start_confirmation(experiment_name=experiment_name)
                # countdown_beep()

                # Record temperature and humidity
                temperature_start, humidity_start = tcm.read_temperature_humidity(
                    show_reading=True,
                )

                # Execute configured number of PIV runs with pump start/stop timing
                for run_idx in range(cough_inputs["nr_runs"]):
                    # Create a separate folder for each run when saving is enabled
                    run_dir = logger.create_run_dir(
                        output_dir, run_idx + 1, cough_inputs["nr_runs"])
                    if run_dir is not None:
                        run_dirs.append(run_dir)

                    # FROM SECOND RUN ONWARDS
                    if run_idx > 0:
                        # Before each run, fill the nebuliser tank again
                        tcm.set_nebuliser(True)
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
                    tcm.set_nebuliser_pressure(nebuliser_pressure_bar)
                    pump_stopped = False

                    # If an error occurs, the nebuliser will always be turned off
                    # TODO: This should be part of the cough machine cleanup routine
                    try:

                        # Optional pre-run pump lead-in time for stable nebulisation
                        if nebuliser_inputs["pre_run_start_s"] > 0:
                            print(
                                f"Waiting {nebuliser_inputs['pre_run_start_s']} s before run {run_idx + 1}/{cough_inputs['nr_runs']}"
                            )
                            time.sleep(
                                float(nebuliser_inputs["pre_run_start_s"]))

                        # Record the ambient conditions immediately before the cough
                        temperature, humidity = tcm.read_temperature_humidity(
                            show_reading=True,
                        )
                        if run_dir is not None:
                            logger.write_ambient_measurement(
                                run_dir, temperature, humidity)

                        # Start the run
                        tcm.start_run()
                        tcm.wait_for_run_finished()

                        # Optional post-run pump tail time after actuation finishes
                        if nebuliser_inputs["post_run_finish_s"] > 0:
                            print(
                                f"Waiting {nebuliser_inputs['post_run_finish_s']} s after run {run_idx + 1}/{cough_inputs['nr_runs']}"
                            )
                            time.sleep(
                                float(nebuliser_inputs["post_run_finish_s"]))

                        # Turn off nebuliser
                        tcm.set_nebuliser(False)
                        print("Turning off nebuliser air flow")
                        tcm.set_nebuliser_pressure(0.0)
                        pump_stopped = True

                        run_log_path = tcm.receive_run_log(
                            output_dir=run_dir,
                            run_nr_start=(run_idx + 1),
                            save_logs=save_data,
                        )

                        # Plot run log
                        if save_data and run_log_path is not None:
                            plot_run_log(
                                run_log_path=run_log_path,
                                experiment_dir=run_dir,
                                show=False,
                            )

                    finally:
                        # Always stop pump, even if the run or waits raise an error
                        if not pump_stopped:
                            tcm.set_nebuliser_pressure(0.0)
                            tcm.set_nebuliser(False)

                        # Flush nebuliser chamber before cleaning channel
                        tcm.set_nebuliser_pressure(0.3)
                        wait_with_progress(
                            wait_s=5, label="Flushing nebuliser chamber...")
                        tcm.set_nebuliser_pressure(0.0)

                        # Run cleaning routine every cycle
                        tcm.clean(clean_pressure_bar=cleaning_inputs["clean_pressure_bar"],
                                  clean_valve_open_duration_s=cleaning_inputs["valve_open_duration_s"],
                                  clean_cycle_count=cleaning_inputs["cycle_count"],
                                  dry_pressure_bar=cleaning_inputs["dry_pressure_bar"],
                                  dry_duration_s=cleaning_inputs["dry_duration_s"],
                                  dry_valve_current_ma=cleaning_inputs["dry_valve_current_ma"])

        # ------------------------------------------------------------------
        # 6) Finalize run and write (meta)data
        # ------------------------------------------------------------------
        # During cleanup, just to be sure, get rid of excess heat
        tcm.set_fan_speed(CoughMachine.FAN_SPEED_MAX)

        if save_data:
            assert output_dir is not None

            # Record temperature and humidity
            temperature_finish, humidity_finish = tcm.read_temperature_humidity(
                show_reading=True,
            )
            time_finish = timestamp_str()

            # Collect comments
            comments = ask_user_for_comments(output_dir=output_dir)

            # Optional SprayTec post-processing.
            spraytec_audit_path = None
            if record_droplet_size_spraytec:
                assert spraytec is not None
                prompt_yes_no(
                    "Press ENTER if the SprayTec has finished processing and exporting the measurement(s)...",
                    default=True,
                )
                # TODO: Add some print statements in save_data so user is not wondering what is going on.
                spraytec_audit_path = spraytec.save_data(
                    append_file_path=config["devices"]["spraytec"]["append_file_path"],
                    start_time=time_start,
                    debug=cough_inputs["debug_mode"],
                    offer_archive_if_large=True,
                    run_dirs=run_dirs,
                )

            metadata = logger.build_run_metadata(
                config,
                time_start=time_start,
                time_finish=time_finish,
                output_dir=output_dir,
                temperature_start=temperature_start,
                humidity_start=humidity_start,
                temperature_finish=temperature_finish,
                humidity_finish=humidity_finish,
                comments=comments,
                tcm=tcm,
                pump=pump,
                camera=camera,
                ops=ops,
                spraytec=spraytec,
                spraytec_x_mm=spraytec_x_mm,
                spraytec_y_mm=spraytec_y_mm,
                spraytec_z_mm=spraytec_z_mm,
                spraytec_audit_path=spraytec_audit_path,
                spraytec_laser_intensity=spraytec_laser_intensity,
                stage_pos_z_mm=stage_pos_z_mm,
                vertical_stage=vertical_stage,
            )
            # Persist full run metadata snapshot.
            logger.write_run_metadata(
                experiment_dir=output_dir, meta=metadata)

            # Export all pdfs as pngs for convenience
            export_all_pdfs_to_pngs_in_directory(output_dir)

            print("Experiment completed, all data saved to ", output_dir)
            print("Exiting.")
        else:
            print("Experiment completed.")
            if not save_data:
                print("No data was saved (experiment.save_data=false).")
            print("Exiting.")

        # Reset the fan to original speed
        tcm.set_fan_speed(CoughMachine.FAN_SPEED_DEFAULT)

    finally:
        # Release every device and the console log even if one release fails.
        # The cough machine stays open: interrupt cleanup still needs it.
        try:
            if ops is not None:
                try:
                    ops.close()
                except Exception as exc:
                    print(f"Warning: Failed to release OPS: {exc}")

            if camera is not None:
                try:
                    camera.close()
                except Exception as exc:
                    print(f"Warning: Failed to release camera: {exc}")

            if vertical_stage is not None:
                try:
                    vertical_stage.close(ignore_exceptions=True)
                except Exception as exc:
                    print(f"Warning: Failed to release vertical stage: {exc}")

            if pump is not None:
                try:
                    # stop() halts the motor, then closes the serial port
                    pump.stop()
                except Exception as exc:
                    print(f"Warning: Failed to release syringe pump: {exc}")
        finally:
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
