import csv
import time
from pathlib import Path
from typing import Callable, Optional

from tcm_utils.file_dialogs import ask_open_file, find_repo_root
from tcm_utils.io_utils import make_minimal_progress_bar

from .base import PoFSerialDevice
from ..logger import copy_flow_curve, create_labeled_csv_filename

DEFAULT_FLOWCURVE_DIR = Path("source_python/tcm_control/flow_curves")
DEFAULT_RUN_LOG_DIR = Path(".logs")
EXPERIMENT_RUN_LOG_SUBDIR = "run_logs"
MAX_PRESSURE_BAR = 4.3
# Keep protocol version as a single integer. Bump only for breaking serial changes.
DEFAULT_SUPPORTED_PROTOCOL_VERSION = 4


class CoughMachine(PoFSerialDevice):
    def __init__(
        self,
        name: str = "CoughMachine_MCU",
        long_name: str = "Adafruit ItsyBitsy M4 Express",
        expected_id: str = "TCM_control",
        baudrate: int = 115200,
        timeout: float = 1,
        debug: bool = False,
        echo: bool = False,
        supported_protocol_version: int = DEFAULT_SUPPORTED_PROTOCOL_VERSION,
    ):
        """Initialize the cough machine serial device wrapper.

        Parameters map to the underlying serial connection and expected MCU identity
        (`id?` -> `TCM_control`). If `debug` is True, device debug mode is enabled
        immediately via command `B 1`.
        """
        super().__init__(
            name=name,
            long_name=long_name,
            expected_id=expected_id,
            baudrate=baudrate,
            timeout=timeout,
            debug=debug,
            echo=echo,
        )

        self._supported_protocol_version = int(supported_protocol_version)
        self._protocol_version: Optional[int] = None

        if self._supported_protocol_version < 0:
            raise ValueError("supported_protocol_version must be >= 0")

        # Fail fast when host and firmware protocol contracts do not match.
        self._assert_protocol_compatibility(echo=echo)

        self._wait_us: Optional[int] = None
        self._target_pressure_bar: Optional[float] = None
        self._dataset_loaded = False
        self._flowcurve_csv_path: Optional[Path] = None

        # Set debug mode on device if requested
        self._set_debug(debug)

    # ------------------------------------------------------------------
    # Manual mode
    # ------------------------------------------------------------------

    # Allow user to type commands directly to the device
    def manual_mode(self) -> None:
        """Start an interactive terminal pass-through to the MCU.

        User-entered lines are sent directly over serial and responses are drained
        and printed. Exit with `exit`, `quit`, or Ctrl+C.
        """
        print("Entering manual mode; type commands to send to the device. Ctrl+C to exit")
        try:
            while True:
                cmd = input(">> ")
                if cmd.strip().lower() in {"exit", "quit"}:
                    print("Exiting manual mode.")
                    break
                self._query_and_drain(cmd, echo=True, raise_on_error=False)
        except KeyboardInterrupt:
            print("\nExiting manual mode.")
            quit(1)

    # ------------------------------------------------------------------
    # Serial command wrappers
    # ------------------------------------------------------------------

    # CONNECTION & DEBUGGING
    def _identify(self, *, echo: Optional[bool] = None) -> str:
        """Query device identity using `id?` and return the reply string."""
        reply, _lines = self._query_and_drain("id?", echo=echo)
        return reply or ""

    def get_protocol_version(self, *, echo: Optional[bool] = None) -> int:
        """Query protocol info using `ver?`.

        Expects `PROTO <integer>` and returns that integer.
        """
        reply, _lines = self._query_and_drain(
            "ver?", expected_prefix="PROTO", echo=echo)
        if reply is None:
            raise RuntimeError("No reply to protocol version query 'ver?'")

        clean = reply.strip()
        parts = clean.split()
        if len(parts) != 2 or parts[0] != "PROTO":
            raise RuntimeError(f"Unexpected protocol version reply: {reply!r}")

        try:
            return int(parts[1])
        except ValueError as exc:
            raise RuntimeError(
                f"Unexpected protocol version reply: {reply!r}") from exc

    @property
    def protocol_version(self) -> Optional[int]:
        """Negotiated MCU protocol version for this connection."""
        return self._protocol_version

    def _assert_protocol_compatibility(self, *, echo: Optional[bool] = None) -> None:
        try:
            protocol_version = self.get_protocol_version(echo=echo)
        except Exception as exc:
            raise RuntimeError(
                "Failed to negotiate protocol version with the MCU. "
                "Expected a `ver?` command reply in the form 'PROTO <integer>'."
            ) from exc

        if protocol_version != self._supported_protocol_version:
            raise RuntimeError(
                "Incompatible MCU protocol version "
                f"{protocol_version}. This host expects protocol version "
                f"{self._supported_protocol_version}."
            )

        self._protocol_version = protocol_version

    def _set_debug(self, enabled: bool) -> None:
        """Enable or disable MCU debug output using `B <0|1>`.

        Expects `DEBUG_ON` when enabled and `DEBUG_OFF` when disabled.
        """
        cmd = "B 1" if enabled else "B 0"
        expected = "DEBUG_ON" if enabled else "DEBUG_OFF"
        self._query_and_drain(cmd, expected=expected, echo=enabled)
        if enabled:
            print("Debug mode enabled on device.")

    def read_status(
        self, *, echo: Optional[bool] = None, timeout: float = 1.0
    ) -> list[str]:
        """Read debug status block using `S?`.

        This command is only available when debug mode is active on the host and MCU.
        Returns all lines read from the status response.
        """
        if not self._debug:
            raise RuntimeError("read_status is only available in debug mode.")
        if not self.write("S?"):
            raise RuntimeError("Failed to send S? command")

        lines = self._read_lines(timeout=timeout)
        if self._resolve_echo(echo):
            for line in lines:
                print(f"[{self.name}] {line}")
        self._check_errors(lines, raise_on_error=True)
        return lines

    def help(self, *, echo: Optional[bool] = None) -> str:
        """Request the on-device help menu using `?`."""
        reply, _lines = self._query_and_drain("?", echo=echo)
        return reply or ""

    # CONTROL HARDWARE
    def set_valve_current(self, current_ma: float, *, echo: Optional[bool] = None) -> str:
        """Set proportional valve current in mA using `V <mA>`.

        Expects a reply beginning with `SET_VALVE`.
        """
        reply, _lines = self._query_and_drain(
            f"V {current_ma}", expected_prefix="SET_VALVE", echo=echo
        )
        return reply or ""

    def set_pressure(
        self,
        pressure_bar: float,
        *,
        timeout_s: float = 120.0,
        avg_window_s: float = 5.0,
        tolerance_bar: float = 0.05,
        poll_interval_s: float = 0.2,
        interm_press_diff_bar: Optional[float] = None,
        interm_press_time_s: Optional[float] = None,
        status_prefix: Optional[str] = None,
        status_suffix: str = "",
        show_status: bool = True,
        print_newline_on_exit: bool = True,
        echo: Optional[bool] = None,
    ) -> str:
        """Set target pressure with `P <bar>` and wait for stable measured pressure.

        After issuing the set command, pressure is polled via `P?` until the rolling
        average over `avg_window_s` is within `tolerance_bar` or `timeout_s` elapses.
        """

        # Check parameters
        if pressure_bar < 0 or pressure_bar > MAX_PRESSURE_BAR:
            raise ValueError(
                f"Pressure must be between 0 and {MAX_PRESSURE_BAR} bar")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        if avg_window_s <= 0:
            raise ValueError("avg_window_s must be > 0")
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        if timeout_s <= avg_window_s:
            avg_window_s = timeout_s / 2
        if (interm_press_diff_bar is not None) != (interm_press_time_s is not None):
            raise ValueError(
                "Both interm_press_diff_bar and interm_press_time_s must be provided together")
        if status_prefix is None:
            status_prefix = f"{self.name} tank pressure settling:"

        # Track previous status-line length so shorter updates can clear tail chars.
        last_status_len = 0

        def _print_settling_status(message: str) -> None:
            nonlocal last_status_len
            clear_tail = max(0, last_status_len - len(message))
            print(f"\r{message}{' ' * clear_tail}", end="", flush=True)
            last_status_len = len(message)

        # Shared pressure-monitoring loop used for both intermediate and final
        # pressure phases. It always prints live pressure/deviation feedback.
        def _monitor_pressure(
            target_bar: float,
            phase_timeout_s: float,
            *,
            require_settle: bool,
            status_suffix: str = "",
        ) -> bool:
            # Keep a rolling window of readings to evaluate pressure stability.
            start = time.time()
            samples: list[tuple[float, float]] = []
            first_sample_time = time.time()

            while (time.time() - start) < phase_timeout_s:
                reading = self.read_pressure(echo=False)
                if reading is not None:
                    now = time.time()
                    samples.append((now, reading))
                    cutoff = now - avg_window_s
                    samples = [(t, p) for t, p in samples if t >= cutoff]

                    if show_status:
                        _print_settling_status(
                            f"{status_prefix} "
                            f"{reading:.2f}/{target_bar:.2f} bar{status_suffix}"
                        )

                    # For final setpoint settling, require the rolling average to
                    # stay within tolerance before reporting success.
                    if require_settle and (now - first_sample_time) >= avg_window_s and samples:
                        avg = sum(p for _, p in samples) / len(samples)
                        if abs(avg - target_bar) <= tolerance_bar:
                            return True
                else:
                    if show_status:
                        _print_settling_status(
                            f"{status_prefix} "
                            f"-.--/{target_bar:.2f} bar{status_suffix}"
                        )

                time.sleep(poll_interval_s)

            # Timeout reached. Intermediate phase treats this as expected end-of-
            # hold period; final phase treats it as failure to settle.
            return False

        # If a (relative) intermediate value is given, first set that value
        if interm_press_diff_bar is not None and interm_press_time_s is not None:
            interm_press_bar = pressure_bar + interm_press_diff_bar
            if interm_press_bar < 0 or interm_press_bar > MAX_PRESSURE_BAR:
                raise ValueError(
                    f"Intermediate pressure must be between 0 and {MAX_PRESSURE_BAR} bar")

            # Intermediate phase: go to an offset pressure first and monitor for
            # the requested hold duration (no strict settle criterion).
            self._query_and_drain(
                f"P {interm_press_bar}", expected_prefix="SET_PRESSURE", echo=echo)
            _monitor_pressure(
                interm_press_bar,
                interm_press_time_s,
                require_settle=False,
                status_suffix=" (intermediate setting)",
            )

        # Final phase: command requested pressure and wait until rolling-average
        # settling criterion is met, or timeout occurs.
        reply, _lines = self._query_and_drain(
            f"P {pressure_bar}", expected_prefix="SET_PRESSURE", echo=echo)

        settled = _monitor_pressure(
            pressure_bar,
            timeout_s,
            require_settle=True,
            status_suffix=status_suffix,
        )
        if show_status and print_newline_on_exit:
            print()
        if settled:
            # Remember the active pressure setpoint so routines (e.g. cleaning)
            # can restore it later without requiring caller-managed state.
            self._target_pressure_bar = pressure_bar
            return reply or ""

        raise RuntimeError(
            "Could not reach setpoint value or pressure too unstable.")

    def open_solenoid(self, *, echo: Optional[bool] = None) -> str:
        """Open the solenoid valve using `O`.

        Expects `SOLENOID_OPENED`.
        """
        reply, _lines = self._query_and_drain(
            "O", expected="SOLENOID_OPENED", echo=echo
        )
        return reply or ""

    def close_solenoid(self, *, echo: Optional[bool] = None) -> str:
        """Close the solenoid valve using `C`.

        Expects `SOLENOID_CLOSED`.
        """
        reply, _lines = self._query_and_drain(
            "C", expected="SOLENOID_CLOSED", echo=echo
        )
        return reply or ""

    def clean(
        self,
        *,
        pressure_bar: float = 4.0,
        open_duration_s: float = 2.5,
        repeats: int = 3,
        settle_timeout_s: float = 120.0,
        settle_avg_window_s: float = 5.0,
        settle_tolerance_bar: float = 0.05,
        settle_poll_interval_s: float = 0.2,
        echo: Optional[bool] = None,
    ) -> None:
        """Run a tank/valve cleaning routine and restore prior pressure setpoint.

        The routine repeats:
        1) set tank pressure to `pressure_bar`
          2) set proportional valve current to `prop_valve_open_current_ma`
          3) open solenoid for `open_duration_s`
          4) close solenoid and set proportional valve current to
              `prop_valve_close_current_ma`

        After all cycles (or on failure), the previous pressure setpoint is
        restored automatically using `set_pressure`.
        """
        if pressure_bar < 0 or pressure_bar > MAX_PRESSURE_BAR:
            raise ValueError(
                f"pressure_bar must be between 0 and {MAX_PRESSURE_BAR} bar")
        if open_duration_s <= 0:
            raise ValueError("open_duration_s must be > 0")
        if repeats <= 0:
            raise ValueError("repeats must be >= 1")

        original_setpoint_bar = self._target_pressure_bar
        if original_setpoint_bar is None:
            raise RuntimeError(
                "Cannot run clean() before a pressure setpoint is established. "
                "Call set_pressure() at least once first."
            )

        try:
            for cycle_idx in range(1, repeats + 1):
                self.set_pressure(
                    pressure_bar,
                    timeout_s=settle_timeout_s,
                    avg_window_s=settle_avg_window_s,
                    tolerance_bar=settle_tolerance_bar,
                    poll_interval_s=settle_poll_interval_s,
                    status_prefix=(
                        f"{self.name} cleaning cycle {cycle_idx}/{repeats} "
                        "(pressure"
                    ),
                    status_suffix=")",
                    print_newline_on_exit=False,
                    echo=echo,
                )

                opening_msg = f"{self.name} cleaning cycle (opening valves)"
                pressure_msg_len = len(
                    f"{self.name} cleaning cycle {cycle_idx}/{repeats} "
                    f"(pressure -.--/{pressure_bar:.2f} bar)"
                )
                clear_tail = max(0, pressure_msg_len - len(opening_msg))
                print(f"\r{opening_msg}{' ' * clear_tail}", end="", flush=True)

                self.set_valve_current(20, echo=echo)
                try:
                    self.open_solenoid(echo=echo)
                    time.sleep(open_duration_s)
                    self.close_solenoid(echo=echo)
                finally:
                    self.set_valve_current(12, echo=echo)
        finally:
            self.set_pressure(
                original_setpoint_bar,
                timeout_s=settle_timeout_s,
                avg_window_s=settle_avg_window_s,
                tolerance_bar=settle_tolerance_bar,
                poll_interval_s=settle_poll_interval_s,
                status_prefix=f"{self.name} restoring pressure (pressure",
                status_suffix=")",
                show_status=False,
                print_newline_on_exit=False,
                echo=echo,
            )
            print()

    def quit(self, *, echo: Optional[bool] = None) -> str:
        """Abort active MCU modes and return to idle using `Q`.

        Expects `RETURNED_TO_IDLE`.
        """
        reply, _lines = self._query_and_drain(
            "Q", expected="RETURNED_TO_IDLE", echo=echo
        )
        return reply or ""

    def laser_test(
        self,
        enabled: bool = True,
        *,
        duration_s: Optional[float] = None,
        echo: Optional[bool] = None,
    ) -> str:
        """Toggle laser test mode with `A <0|1>`.

        When `duration_s` is provided and `enabled` is True, test mode is enabled,
        held for the duration, and then automatically disabled.
        """
        if duration_s is not None and enabled:
            reply_on, _lines_on = self._query_and_drain(
                "A 1", expected="LASER_TEST_ON", echo=echo
            )
            time.sleep(duration_s)
            reply_off, _lines_off = self._query_and_drain(
                "A 0", expected="LASER_TEST_OFF", echo=echo
            )
            return reply_off or reply_on or ""

        cmd = "A 1" if enabled else "A 0"
        expected = "LASER_TEST_ON" if enabled else "LASER_TEST_OFF"
        reply, _lines = self._query_and_drain(
            cmd, expected=expected, echo=echo)
        return reply or ""

    def trigger_once(self, *, echo: Optional[bool] = None) -> str:
        """Send one immediate trigger pulse using `G`."""
        reply, _lines = self._query_and_drain(
            "G", expected="TRIGGER_PULSE_SENT", echo=echo
        )
        return reply or ""

    def trigger_test(self, *, echo: Optional[bool] = None):
        """Load the "just_trigger.csv" flow curve and run it to test the trigger output."""
        test_csv = DEFAULT_FLOWCURVE_DIR / "just_trigger.csv"
        if not test_csv.exists():
            raise RuntimeError(f"Test CSV not found at {test_csv}")
        self.load_flowcurve(csv_path=test_csv, echo=echo)
        self.run(echo=echo)

    # READ OUT SENSORS
    def read_pressure(self, *, echo: Optional[bool] = None) -> Optional[float]:
        """Read instantaneous pressure using `P?` and parse `P<bar>` reply."""
        reply, _lines = self._query_and_drain(
            "P?", expected_prefix="P", echo=echo)
        if reply is None:
            return None
        try:
            return float(reply[1:])
        except ValueError:
            return None

    def read_temperature_humidity(
        self, *, echo: Optional[bool] = None
    ) -> tuple[Optional[float], Optional[float]]:
        """Read temperature and humidity using `T?`.

        Parses replies formatted like `T<degC> H<%RH>` and returns `(temp, hum)`.
        """
        reply, _lines = self._query_and_drain(
            "T?", expected_prefix="T", echo=echo)
        if reply is None:
            return None, None
        try:
            parts = reply.split()
            temp = float(parts[0][1:])
            hum = float(parts[1][1:])
            return temp, hum
        except (IndexError, ValueError):
            return None, None

    # CONFIGURATION
    def set_wait_us(self, wait_us: int, *, echo: Optional[bool] = None) -> str:
        """Set pre-run wait in microseconds using `W <us>`.

        This wait applies before `R` runs and after droplet detection in `D!` mode.
        """
        reply, _lines = self._query_and_drain(
            f"W {wait_us}", expected_prefix="SET_WAIT", echo=echo
        )
        self._wait_us = wait_us
        return reply or ""

    def get_wait_us(self, *, echo: Optional[bool] = None) -> Optional[int]:
        """Read configured pre-run wait using `W?` and parse `W<us>` reply."""
        reply, _lines = self._query_and_drain(
            "W?", expected_prefix="W", echo=echo)
        if reply is None:
            return None
        try:
            return int(reply[1:])
        except ValueError:
            return None

    def clear_memory(self, *, echo: Optional[bool] = None) -> str:
        """Clear logs and persisted state using `X!`.

        Expects `MEMORY_CLEARED`.
        """
        reply, _lines = self._query_and_drain(
            "X!", expected="MEMORY_CLEARED", echo=echo)
        return reply or ""

    def clear_logs(self, *, echo: Optional[bool] = None) -> str:
        """Delete stored experiment log files using `X`.

        Expects `LOGS_CLEARED`.
        """
        reply, _lines = self._query_and_drain(
            "X", expected="LOGS_CLEARED", echo=echo)
        return reply or ""

    # DATASET HANDLING
    def set_flowcurve_csv_path(self, csv_path: str | Path | None) -> None:
        """Set or clear the default flow-curve CSV path used by `load_flowcurve`."""
        # Store a default path for later; load_flowcurve() will use this if no path is passed.
        self._flowcurve_csv_path = Path(
            csv_path) if csv_path is not None else None

    def get_flowcurve_csv_path(self) -> Optional[Path]:
        """Return the resolved flow-curve CSV path used by `load_flowcurve`."""
        return self._flowcurve_csv_path

    def load_flowcurve(
        self,
        csv_path: str | Path | None = None,
        *,
        delimiter: str = ",",
        echo: Optional[bool] = None,
        timeout: float = 1.0,
        experiment_dir: Optional[Path] | None = None,
    ) -> str:
        """Load and upload a flow-curve dataset using serial command `L`.

        The selected CSV is converted to protocol payload format
        `<N> <duration_ms> <ms0>,<mA0>,<e0>,<t0>,...` and sent as one `L` command,
        where `e` is solenoid enable and `t` is trigger event (both 0/1).
        Waits for upload confirmation ending with `DATASET_SAVED`.
        """
        # If a path is passed here, it overrides any previously stored default
        if csv_path is not None:
            candidate = Path(csv_path)
            if candidate.exists():
                self._flowcurve_csv_path = candidate
            elif isinstance(csv_path, str):

                # Add ".csv" if the string does not already end with it
                if not csv_path.lower().endswith(".csv"):
                    csv_path += ".csv"

                # Check for the file in the default flow_curves directory
                filename_candidate = DEFAULT_FLOWCURVE_DIR / \
                    Path(csv_path).name
                self._flowcurve_csv_path = (
                    filename_candidate if filename_candidate.exists() else None
                )
            else:
                self._flowcurve_csv_path = None

        # If no path was provided or stored, fall back to the file picker dialog.
        if self._flowcurve_csv_path is None:
            self._flowcurve_csv_path = ask_open_file(
                key="flow_curve_csv",
                title="Select flow curve CSV",
                filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
                default_dir=DEFAULT_FLOWCURVE_DIR,
                start=DEFAULT_FLOWCURVE_DIR,
            )

        if self._flowcurve_csv_path is None:
            raise SystemExit("No flow curve CSV selected")

        time_arr, mA_arr, sol_enable_arr, trig_enable_arr = self._extract_csv(
            self._flowcurve_csv_path, delimiter=delimiter
        )
        serial_command = self._format_dataset(
            time_arr,
            mA_arr,
            sol_enable_arr,
            trig_enable_arr,
        )

        if self._debug:
            print(f"Formatted serial command:\n{serial_command}")

        if not self.write(serial_command):
            raise RuntimeError("Failed to write dataset to device.")

        # Wait for dataset upload confirmation without issuing extra commands.
        reply, _lines = self._query_and_drain(
            None,
            expected="DATASET_SAVED",
            echo=echo,
            extra_timeout=timeout,
        )

        self._dataset_loaded = True
        print(f"Dataset loaded from {self._flowcurve_csv_path}")
        if experiment_dir is not None:
            copy_flow_curve(experiment_dir=experiment_dir,
                            flow_curve_path=self._flowcurve_csv_path)
        return reply or ""

    def get_flowcurve_status(self, *, echo: Optional[bool] = None) -> str:
        """Query loaded dataset state with `L?` and return first reply line."""
        reply, _lines = self._query_and_drain("L?", echo=echo)
        return reply or ""

    # COUGH
    def run(
        self,
        *,
        timeout_s: float = 10.0,
        echo: Optional[bool] = None,
        output_dir: Optional[str | Path] = None,
        run_nr_start: Optional[int] = None,
        save_logs: bool = True,
    ) -> Optional[Path]:
        """Run the loaded dataset immediately using `R` and save streamed log CSV.

        Expects a log stream wrapped by `START_OF_FILE ...` and `END_OF_FILE`.
        Returns the saved run-log CSV path, or `None` when `save_logs` is False.
        """

        print("Starting cough")
        if not self.write("R"):
            raise RuntimeError("Failed to send R command")
        rows = self._receive_run_log(
            timeout_s=timeout_s,
            echo=echo,
        )
        print("Cough completed")
        if not save_logs:
            return None
        saved_paths = self._save_run_logs(
            rows,
            output_dir=output_dir,
            run_nr_start=run_nr_start,
        )
        if not saved_paths:
            raise RuntimeError("Failed to save run log for cough run")
        return saved_paths[0]

    def _await_droplet_events(
        self,
        *,
        nr_droplets: Optional[int],
        on_detected: Optional[Callable[[int], None]] = None,
    ) -> int:
        """Wait for `DROPLET_DETECTED` events and invoke callback per detection.

        Stops after `nr_droplets` detections when provided, otherwise runs
        indefinitely until external interruption.
        """
        target_droplets: Optional[int] = (
            None if nr_droplets is None else max(0, int(nr_droplets))
        )

        detections = 0
        while True:
            if target_droplets is not None and detections >= target_droplets:
                break

            if self.ser is not None and self.ser.in_waiting > 0:
                success, line = self.readline()
                if not success or not isinstance(line, str):
                    continue
                clean_line = line.strip()

                if clean_line.startswith("ERROR"):
                    raise RuntimeError(clean_line)

                if clean_line == "DROPLET_DETECTED":
                    detections += 1
                    if on_detected is not None:
                        on_detected(detections)
                    continue

        return detections

    def count_droplets(
        self,
        nr_droplets: Optional[int] = None,
        let_drip: bool = False,
        *,
        echo: Optional[bool] = None,
    ) -> int:
        """Arm droplet detection mode (`D` or `D <n>`) and count detections.

        Returns the number of `DROPLET_DETECTED` events observed before completion.
        """
        target_droplets = None if nr_droplets is None else int(nr_droplets)
        if target_droplets is not None and target_droplets <= 0:
            raise ValueError("nr_droplets must be >= 1 when provided")

        cmd = "D" if (
            target_droplets is None or let_drip) else f"D {target_droplets}"
        reply, _lines = self._query_and_drain(
            cmd, expected="DROPLET_ARMED", echo=echo)

        if reply != "DROPLET_ARMED":
            raise RuntimeError(f"Unexpected reply to {cmd}: {reply!r}")

        if target_droplets is None:
            def handle_detection(detections: int) -> None:
                message = f"\rCounted droplets: {detections}"
                print(message, end="", flush=True)

            detections = self._await_droplet_events(
                nr_droplets=target_droplets,
                on_detected=handle_detection,
            )
            print()  # Newline after final count
        else:
            with make_minimal_progress_bar(
                total=target_droplets,
                label="Counting droplets",
                unit_label="drops",
            ) as pbar:
                def handle_detection(detections: int) -> None:
                    if detections > pbar.n:
                        pbar.update(detections - pbar.n)

                detections = self._await_droplet_events(
                    nr_droplets=target_droplets,
                    on_detected=handle_detection,
                )

        return detections

    def detect_droplets_and_run(
        self,
        nr_runs: Optional[int] = None,
        run_nr_start: Optional[int] = None,
        *,
        echo: Optional[bool] = None,
        output_dir: Optional[str | Path] = None,
        log_timeout_s: float = 10.0,
        save_logs: bool = True,
    ) -> list[Path]:
        """Arm droplet-triggered run mode (`D!` or `D! <n>`) and collect run logs.

        For each detected droplet, waits for and captures one streamed run log,
        then saves all captured logs to disk and returns saved file paths.
        """
        if nr_runs is not None and int(nr_runs) <= 0:
            raise ValueError("nr_runs must be >= 1 when provided")

        cmd = "D!" if nr_runs is None else f"D! {nr_runs}"
        reply, _lines = self._query_and_drain(
            cmd, expected="DROPLET_ARMED", echo=echo)

        if reply != "DROPLET_ARMED":
            raise RuntimeError(f"Unexpected reply to {cmd}: {reply!r}")

        print("Ready for cough; waiting for next droplet")
        results: list[list[str]] = []

        def handle_detection(_detections: int) -> None:
            result = self._receive_run_log(
                timeout_s=log_timeout_s,
                echo=echo,
            )
            results.append(result)

        self._await_droplet_events(
            nr_droplets=nr_runs,
            on_detected=handle_detection,
        )

        print("Cough completed")
        if not save_logs:
            return []
        saved_paths = self._save_run_logs(
            results,
            output_dir=output_dir,
            run_nr_start=run_nr_start,
        )
        return saved_paths

    # -------------------------------------------------------------------
    # Flowcurve read and upload
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_csv(
        filename: str | Path, delimiter: str = ","
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        """Read flow-curve CSV into arrays for time/current/solenoid/trigger.

        CSV rows must contain four non-empty values in the order
        `time_ms,prop_valve_ma,sol_valve,trig`.
        """
        # Parse a CSV file into time, current, solenoid and trigger arrays
        # for the L command.
        time_arr: list[str] = []
        mA_arr: list[str] = []
        sol_enable_arr: list[str] = []
        trig_enable_arr: list[str] = []
        has_header = False

        with open(filename, "r") as csvfile:
            csvreader = csv.reader(csvfile, delimiter=delimiter)
            for file_row_idx, rows in enumerate(csvreader, start=1):
                if not rows:
                    continue

                if len(rows) < 4:
                    raise ValueError(
                        f"Row {file_row_idx} must have 4 columns: "
                        "time_ms,prop_valve_ma,sol_valve,trig"
                    )

                time_str = rows[0].strip()
                current_str = rows[1].strip()
                sol_str = rows[2].strip()
                trig_str = rows[3].strip()

                if (
                    file_row_idx == 1
                    and time_str.lower() == "time_ms"
                    and current_str.lower() == "prop_valve_ma"
                    and sol_str.lower() == "sol_valve"
                    and trig_str.lower() == "trig"
                ):
                    # has_header = True
                    continue

                if not time_str or not current_str or sol_str == "" or trig_str == "":
                    raise ValueError(
                        f"Encountered empty cell at row {file_row_idx}!"
                    )

                # replace ',' with '.' depending on csv format (';' delim vs ',' delim)
                time_clean = time_str.replace(",", ".")
                current_clean = current_str.replace(",", ".")

                try:
                    float(time_clean)
                    float(current_clean)
                except ValueError as exc:
                    raise ValueError(
                        f"Non-numeric time/current at row {file_row_idx}: {rows[:2]}"
                    ) from exc

                if sol_str not in {"0", "1"}:
                    raise ValueError(
                        f"sol_valve must be 0 or 1 at row {file_row_idx}, got: {sol_str}"
                    )
                if trig_str not in {"0", "1"}:
                    raise ValueError(
                        f"trig must be 0 or 1 at row {file_row_idx}, got: {trig_str}"
                    )

                time_arr.append(time_clean)
                mA_arr.append(current_clean)
                sol_enable_arr.append(sol_str)
                trig_enable_arr.append(trig_str)

        if not time_arr or not mA_arr or not sol_enable_arr or not trig_enable_arr:
            raise ValueError("CSV contains no data.")
        # if has_header:
            # print(f"Detected and skipped CSV header in {filename}")
        return time_arr, mA_arr, sol_enable_arr, trig_enable_arr

    @staticmethod
    def _format_dataset(
        time_array: list[str],
        mA_array: list[str],
        sol_enable_array: list[str],
        trig_enable_array: list[str],
        *,
        prefix: str = "L",
        handshake_delim: str = " ",
        data_delim: str = ",",
    ) -> str:
        """Build the dataset upload string in MCU `L` command format.

        Output format is `L <N> <duration_ms> <ms0>,<mA0>,<e0>,<t0>,...`.
        """
        # Format the arrays into the serial protocol for dataset upload.
        if (
            not time_array
            or len(time_array) != len(mA_array)
            or len(time_array) != len(sol_enable_array)
            or len(time_array) != len(trig_enable_array)
        ):
            raise ValueError(
                f"Arrays are not compatible! Time length: {len(time_array)}, "
                f"mA length: {len(mA_array)}, solenoid length: {len(sol_enable_array)}, "
                f"trigger length: {len(trig_enable_array)}"
            )

        duration = time_array[-1]
        header = (
            f"{prefix}{handshake_delim}{len(time_array)}"
            f"{handshake_delim}{duration}{handshake_delim}"
        )
        data = [
            str(val)
            for t, mA, e, trig in zip(
                time_array,
                mA_array,
                sol_enable_array,
                trig_enable_array,
            )
            for val in (t, mA, e, trig)
        ]
        return header + data_delim.join(data)

    # -------------------------------------------------------------------
    # Run logging
    # -------------------------------------------------------------------

    def _receive_run_log(
        self,
        *,
        start_marker: str = "START_OF_FILE",
        end_marker: str = "END_OF_FILE",
        timeout_s: float = 10.0,
        echo: Optional[bool] = None,
    ) -> list[str]:
        """Receive one streamed log file delimited by file transfer markers.

        Reads serial lines after `START_OF_FILE` until `END_OF_FILE` and returns
        the CSV body lines.
        """
        # Read a single CSV log streamed between START_OF_FILE and END_OF_FILE.
        start_time = time.time()
        started = False
        filename: Optional[str] = None
        rows: list[str] = []
        while (time.time() - start_time) < timeout_s:
            if self.ser is not None and self.ser.in_waiting > 0:
                success, line = self.readline()
                if not success or not isinstance(line, str):
                    continue
                clean_line = line.strip()

                if self._resolve_echo(echo):
                    print(f"[{self.name}] {clean_line}")

                if not started:
                    if clean_line.startswith(start_marker):
                        started = True
                        parts = clean_line.split(maxsplit=1)
                        if len(parts) > 1:
                            filename = parts[1].strip()
                    continue

                if clean_line == end_marker:
                    break

                if not line.endswith("\n"):
                    line = f"{line}\n"
                rows.append(line)
            else:
                time.sleep(0.02)

        if not started:
            raise RuntimeError("Log stream did not start within timeout.")

        return rows

    def _save_run_logs(
        self,
        logs: list[str] | list[list[str]],
        *,
        run_nr_start: Optional[int] = None,
        output_dir: Optional[str | Path] = None,
    ) -> list[Path]:
        """Persist one or more captured run logs as timestamped CSV files.

        Accepts either a single run (`list[str]`) or multiple runs
        (`list[list[str]]`). Optionally rewrites `run_nr` rows when
        `run_nr_start` is provided.
        """
        # Save either one run log (list[str]) or multiple logs (list[list[str]]) as CSV files.
        repo_root = find_repo_root()
        if output_dir is None:
            target_dir = (repo_root / DEFAULT_RUN_LOG_DIR).resolve()
            print(
                "WARNING: output_dir was not found. "
                f"Run logs were saved to: {target_dir}. "
                "Retrieve your files from this repo path."
            )
        else:
            target_dir = Path(output_dir)
            if not target_dir.is_absolute():
                target_dir = repo_root / target_dir
            target_dir = target_dir.resolve()
            target_dir = target_dir / EXPERIMENT_RUN_LOG_SUBDIR

        normalized_logs: list[list[str]] = []
        if isinstance(logs, list) and logs:
            if all(isinstance(line, str) for line in logs):
                normalized_logs = [[str(line) for line in logs]]
            elif all(isinstance(run_rows, list) for run_rows in logs):
                normalized_logs = [
                    [str(line) for line in run_rows] for run_rows in logs
                ]
            else:
                raise TypeError(
                    "logs must be either list[str] or list[list[str]]"
                )
        elif isinstance(logs, list):
            normalized_logs = []
        else:
            raise TypeError("logs must be a list")

        if not normalized_logs:
            return []

        target_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%y%m%d_%H%M%S")
        saved_paths: list[Path] = []

        for idx, rows in enumerate(normalized_logs, start=1):
            if run_nr_start is None:
                if len(normalized_logs) == 1:
                    label = ""
                else:
                    label = idx
            else:
                label = run_nr_start + idx - 1
            filename = create_labeled_csv_filename(
                prefix="log",
                label=label,
                timestamp=timestamp,
            )

            filepath = target_dir / filename
            with open(filepath, "w", encoding="utf-8", newline="") as handle:
                for row in rows:
                    if run_nr_start is not None and row.startswith("run_nr"):
                        row = f"run_nr,{label}\n"
                    handle.write(row if row.endswith("\n") else f"{row}\n")
            saved_paths.append(filepath)

        print(f"Saved {len(saved_paths)} run log(s) to {target_dir}")

        return saved_paths
