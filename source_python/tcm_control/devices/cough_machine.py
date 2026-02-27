import csv
import time
from pathlib import Path
from typing import Callable, Optional

from tcm_utils.file_dialogs import ask_open_file, find_repo_root

from .base import PoFSerialDevice
from ..logger import copy_flow_curve

DEFAULT_FLOWCURVE_DIR = Path("source_python/tcm_control/flow_curves")
DEFAULT_RUN_LOG_DIR = Path(".logs")
# TODO: double check this value
MAX_PRESSURE_BAR = 5.0


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
    ):
        super().__init__(
            name=name,
            long_name=long_name,
            expected_id=expected_id,
            baudrate=baudrate,
            timeout=timeout,
            debug=debug,
            echo=echo,
        )

        self._wait_us: Optional[int] = None
        self._dataset_loaded = False
        self._flowcurve_csv_path: Optional[Path] = None

        # Set debug mode on device if requested
        self._set_debug(debug)

    # ------------------------------------------------------------------
    # Manual mode
    # ------------------------------------------------------------------

    # Allow user to type commands directly to the device
    def manual_mode(self) -> None:
        print("Entering manual mode. Type commands to send to the device. Ctrl+C to exit.")
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
        reply, _lines = self._query_and_drain("id?", echo=echo)
        return reply or ""

    def _set_debug(self, enabled: bool) -> None:
        cmd = "B 1" if enabled else "B 0"
        expected = "DEBUG_ON" if enabled else "DEBUG_OFF"
        self._query_and_drain(cmd, expected=expected, echo=enabled)
        if enabled:
            print("Debug mode enabled on device.")

    def read_status(
        self, *, echo: Optional[bool] = None, timeout: float = 1.0
    ) -> list[str]:
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
        reply, _lines = self._query_and_drain("?", echo=echo)
        return reply or ""

    # CONTROL HARDWARE
    def set_valve_current(self, current_ma: float, *, echo: Optional[bool] = None) -> str:
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
        echo: Optional[bool] = None,
    ) -> str:
        reply, _lines = self._query_and_drain(
            f"P {pressure_bar}", expected_prefix="SET_PRESSURE", echo=echo
        )

        # Check parameters
        if pressure_bar < 0 or pressure_bar > MAX_PRESSURE_BAR:
            raise ValueError(
                f"Pressure must be between 0 and {MAX_PRESSURE_BAR} bar")
        if timeout_s <= 0:
            return reply or ""
        if avg_window_s <= 0:
            raise ValueError("avg_window_s must be > 0")
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        if timeout_s <= avg_window_s:
            avg_window_s = timeout_s / 2

        # Loop until we reach the setpoint within tolerance,
        # using a rolling average to smooth out noise
        start = time.time()
        samples: list[tuple[float, float]] = []
        first_sample_time = time.time()
        while (time.time() - start) < timeout_s:
            reading = self.read_pressure(echo=False)
            if reading is not None:
                now = time.time()
                samples.append((now, reading))
                cutoff = now - avg_window_s
                samples = [(t, p) for t, p in samples if t >= cutoff]

                deviation = reading - pressure_bar
                print(
                    f"\r{self.name} tank pressure settling: {reading:.2f} bar (dev {deviation:+.2f})",
                    end="",
                    flush=True,
                )

                if (now - first_sample_time) >= avg_window_s and samples:
                    avg = sum(p for _, p in samples) / len(samples)
                    if abs(avg - pressure_bar) <= tolerance_bar:
                        print()
                        return reply or ""
            else:
                print(f"\r{self.name} pressure settling: -.-- bar (dev ---)",
                      end="", flush=True)

            time.sleep(poll_interval_s)

        print()
        raise RuntimeError(
            "Could not reach setpoint value or pressure too unstable.")

    def open_solenoid(self, *, echo: Optional[bool] = None) -> str:
        reply, _lines = self._query_and_drain(
            "O", expected="SOLENOID_OPENED", echo=echo
        )
        return reply or ""

    def close_solenoid(self, *, echo: Optional[bool] = None) -> str:
        reply, _lines = self._query_and_drain(
            "C", expected="SOLENOID_CLOSED", echo=echo
        )
        return reply or ""

    def quit(self, *, echo: Optional[bool] = None) -> str:
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

    # READ OUT SENSORS
    def read_pressure(self, *, echo: Optional[bool] = None) -> Optional[float]:
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
        reply, _lines = self._query_and_drain(
            f"W {wait_us}", expected_prefix="SET_WAIT", echo=echo
        )
        self._wait_us = wait_us
        return reply or ""

    def get_wait_us(self, *, echo: Optional[bool] = None) -> Optional[int]:
        reply, _lines = self._query_and_drain(
            "W?", expected_prefix="W", echo=echo)
        if reply is None:
            return None
        try:
            return int(reply[1:])
        except ValueError:
            return None

    def clear_memory(self, *, echo: Optional[bool] = None) -> str:
        reply, _lines = self._query_and_drain(
            "X!", expected="MEMORY_CLEARED", echo=echo)
        return reply or ""

    def clear_logs(self, *, echo: Optional[bool] = None) -> str:
        reply, _lines = self._query_and_drain(
            "X", expected="LOGS_CLEARED", echo=echo)
        return reply or ""

    # DATASET HANDLING
    def set_flowcurve_csv_path(self, csv_path: str | Path | None) -> None:
        # Store a default path for later; load_flowcurve() will use this if no path is passed.
        self._flowcurve_csv_path = Path(
            csv_path) if csv_path is not None else None

    def load_flowcurve(
        self,
        csv_path: str | Path | None = None,
        *,
        delimiter: str = ",",
        echo: Optional[bool] = None,
        timeout: float = 1.0,
        experiment_dir: Optional[Path] | None = None,
    ) -> str:
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

        time_arr, mA_arr, enable_arr = self._extract_csv(
            self._flowcurve_csv_path, delimiter=delimiter
        )
        serial_command = self._format_dataset(time_arr, mA_arr, enable_arr)

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
    ) -> list[str]:

        print("Starting cough")
        if not self.write("R"):
            raise RuntimeError("Failed to send R command")
        rows = self._receive_run_log(
            timeout_s=timeout_s,
            echo=echo,
        )
        print("Cough completed")
        self._save_run_logs(rows, output_dir=output_dir,
                            run_nr_start=run_nr_start)
        return rows

    def _await_droplet_events(
        self,
        *,
        nr_droplets: Optional[int],
        on_detected: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> int:
        remaining: Optional[int]
        if nr_droplets is None:
            remaining = None
        else:
            remaining = max(0, int(nr_droplets))

        detections = 0
        while True:
            if remaining is not None and remaining <= 0:
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
                    if remaining is not None:
                        remaining -= 1
                    if on_detected is not None:
                        on_detected(detections, remaining)
                    continue

        return detections

    def count_droplets(
        self,
        nr_droplets: Optional[int] = None,
        *,
        echo: Optional[bool] = None,
    ) -> int:
        if nr_droplets is not None and int(nr_droplets) <= 0:
            raise ValueError("nr_droplets must be >= 1 when provided")

        cmd = "D" if nr_droplets is None else f"D {nr_droplets}"
        reply, _lines = self._query_and_drain(
            cmd, expected="DROPLET_ARMED", echo=echo)

        if reply != "DROPLET_ARMED":
            raise RuntimeError(f"Unexpected reply to {cmd}: {reply!r}")

        def handle_detection(detections: int, remaining: Optional[int]) -> None:
            remaining_text = "∞" if remaining is None else str(remaining)
            print(
                f"\rCounted droplets: {detections} ({remaining_text} remaining)",
                end="",
                flush=True,
            )

        detections = self._await_droplet_events(
            nr_droplets=nr_droplets,
            on_detected=handle_detection,
        )
        print()
        return detections

    def detect_droplets_and_run(
        self,
        nr_runs: Optional[int] = None,
        run_nr_start: Optional[int] = None,
        *,
        echo: Optional[bool] = None,
        output_dir: Optional[str | Path] = None,
        log_timeout_s: float = 10.0,
    ) -> list[list[str]]:
        if nr_runs is not None and int(nr_runs) <= 0:
            raise ValueError("nr_runs must be >= 1 when provided")

        cmd = "D!" if nr_runs is None else f"D! {nr_runs}"
        reply, _lines = self._query_and_drain(
            cmd, expected="DROPLET_ARMED", echo=echo)

        if reply != "DROPLET_ARMED":
            raise RuntimeError(f"Unexpected reply to {cmd}: {reply!r}")

        results: list[list[str]] = []

        def handle_detection(_detections: int, _remaining: Optional[int]) -> None:
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
        self._save_run_logs(results, output_dir=output_dir,
                            run_nr_start=run_nr_start)
        return results

    # -------------------------------------------------------------------
    # Flowcurve read and upload
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_csv(
        filename: str | Path, delimiter: str = ","
    ) -> tuple[list[str], list[str], list[str]]:
        # Parse a CSV file into time, current, enable arrays for the L command.
        time_arr: list[str] = []
        mA_arr: list[str] = []
        enable_arr: list[str] = []
        row_idx = 0

        with open(filename, "r") as csvfile:
            csvreader = csv.reader(csvfile, delimiter=delimiter)
            for rows in csvreader:
                if len(rows) < 3 or not rows[0] or not rows[1] or rows[2] == "":
                    raise ValueError(
                        f"Encountered empty cell at row index {row_idx}!"
                    )
                # replace ',' with '.' depending on csv format (';' delim vs ',' delim)
                time_arr.append(rows[0].replace(",", "."))
                mA_arr.append(rows[1].replace(",", "."))
                enable_arr.append(rows[2].strip())
                row_idx += 1

        if not time_arr or not mA_arr or not enable_arr:
            raise ValueError("CSV contains no data.")
        return time_arr, mA_arr, enable_arr

    @staticmethod
    def _format_dataset(
        time_array: list[str],
        mA_array: list[str],
        enable_array: list[str],
        *,
        prefix: str = "L",
        handshake_delim: str = " ",
        data_delim: str = ",",
    ) -> str:
        # Format the arrays into the serial protocol for dataset upload.
        if (
            not time_array
            or len(time_array) != len(mA_array)
            or len(time_array) != len(enable_array)
        ):
            raise ValueError(
                f"Arrays are not compatible! Time length: {len(time_array)}, "
                f"mA length: {len(mA_array)}, enable length: {len(enable_array)}"
            )

        duration = time_array[-1]
        header = (
            f"{prefix}{handshake_delim}{len(time_array)}"
            f"{handshake_delim}{duration}{handshake_delim}"
        )
        data = [
            str(val)
            for t, mA, e in zip(time_array, mA_array, enable_array)
            for val in (t, mA, e)
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
            filename = f"run{label}_{timestamp}.csv"

            filepath = target_dir / filename
            with open(filepath, "w", encoding="utf-8", newline="") as handle:
                for row in rows:
                    if run_nr_start is not None and row.startswith("run_nr"):
                        row = f"run_nr,{label}\n"
                    handle.write(row if row.endswith("\n") else f"{row}\n")
            saved_paths.append(filepath)

        print(f"Saved {len(saved_paths)} run log(s) to {target_dir}")

        return saved_paths
