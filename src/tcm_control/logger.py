"""File and metadata logging utilities for experiment runs."""

from contextlib import contextmanager
from datetime import datetime
import io
from pathlib import Path
import shutil
import sys
import time
from typing import Any, TextIO

from tcm_utils.io_utils import create_timestamped_filename, save_metadata_json
from tcm_utils.time_utils import timestamp_str, timestamp_from_file


RUN_LOGS_SUBDIR = "run_logs"
CONSOLE_LOGS_SUBDIR = "host_console_logs"

# In the destination folder, put several files: metadata (json),
# cough machine event log (csv, multiple in case of droplet detection),
# a copy of the flow curve (csv), comments about the run (txt),
# and some plots (pdf) of the data.

# -----------------------------------------------------------------------------
# Experiment folder and artifact file helpers
# -----------------------------------------------------------------------------


def create_experiment_dir(
    experiment_dir: Path,
    experiment_name: str,
    start_time: str | None = None,
) -> Path:
    """Create a timestamped output directory for one experiment."""

    # Create a timestamped directory for the experiment if not provided
    if start_time is None:
        start_time = timestamp_str()

    # Create the experiment directory
    dir_name = f"{start_time}_{experiment_name}"
    experiment_dir = experiment_dir / dir_name
    experiment_dir.mkdir(parents=True, exist_ok=False)

    # Return path
    return experiment_dir


def write_run_log(
        experiment_dir: Path,
        rows: list[str]):
    """Write a single run log text file into the experiment directory."""

    # Get the run number from the row starting with "run_nr,"
    for row in rows:
        if row.startswith("run_nr,"):
            run_nr = row.split(",")[1]
            break

    # Set the file path and write the log
    run_logs_dir = experiment_dir / RUN_LOGS_SUBDIR
    run_logs_dir.mkdir(parents=True, exist_ok=True)
    file_path = run_logs_dir / f"run_log_{run_nr}.txt"
    with open(file_path, "w") as f:
        for row in rows:
            f.write(f"{row}\n")

    print(f"Run log #{run_nr} saved to {file_path}")


def write_comments(
        experiment_dir: Path,
        comments: str):
    """Persist optional user comments for the run."""
    file_path = experiment_dir / "comments.txt"
    with open(file_path, "w") as f:
        f.write(comments)

    print(f"Comments saved to {file_path}")


def copy_flow_curve(
        experiment_dir: Path,
        flow_curve_path: Path) -> Path:
    """Copy the active flow-curve file for traceability of each run."""

    # Copy the flow curve file to the experiment directory for record-keeping
    dest_path = experiment_dir / f"flow_curve_{flow_curve_path.name}"
    shutil.copy2(flow_curve_path, dest_path)

    print(f"Flow curve copied to {dest_path}")
    return dest_path


def copy_experiment_config(
    experiment_dir: Path,
        config_path: Path) -> Path:
    """Copy the active experiment TOML into the experiment directory."""

    dest_path = experiment_dir / f"{config_path.name}"
    shutil.copy2(config_path, dest_path)

    print(f"Config file copied to {dest_path}")
    return dest_path


def create_labeled_csv_filename(
        prefix: str,
        label: int | str | None,
        timestamp: str | None = None) -> str:
    """Build a timestamped CSV filename with an optional label."""
    if timestamp is None:
        timestamp = time.strftime("%y%m%d_%H%M%S")

    safe_label = "" if label is None else str(label)
    return f"{prefix}{safe_label}_{timestamp}.csv"


def create_console_log_path(
        experiment_dir: Path) -> Path:
    """Return the fixed log path for captured terminal output per experiment."""
    return experiment_dir / "host_console_log.txt"


class _TimestampedTee(io.TextIOBase):
    """Mirror writes to terminal and a timestamped text log file."""

    def __init__(
        self,
        terminal_stream: TextIO,
        log_stream: TextIO,
        stream_label: str,
    ) -> None:
        self._terminal_stream = terminal_stream
        self._log_stream = log_stream
        self._stream_label = stream_label
        self._line_start = True
        self._log_stream_broken = False

    def _timestamp_prefix(self) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"[{timestamp}] [{self._stream_label}] "

    def write(self, text: str) -> int:
        if not text:
            return 0

        self._terminal_stream.write(text)

        if self._log_stream_broken:
            return len(text)

        if getattr(self._log_stream, "closed", False):
            self._log_stream_broken = True
            return len(text)

        try:
            for char in text:
                if self._line_start:
                    self._log_stream.write(self._timestamp_prefix())
                    self._line_start = False

                if char == "\r":
                    self._log_stream.write("\n")
                    self._line_start = True
                    continue

                self._log_stream.write(char)

                if char == "\n":
                    self._line_start = True
        except (ValueError, OSError):
            self._log_stream_broken = True

        return len(text)

    def flush(self) -> None:
        self._terminal_stream.flush()
        if self._log_stream_broken:
            return
        try:
            if not getattr(self._log_stream, "closed", False):
                self._log_stream.flush()
            else:
                self._log_stream_broken = True
        except (ValueError, OSError):
            self._log_stream_broken = True

    def isatty(self) -> bool:
        return self._terminal_stream.isatty()


@contextmanager
def capture_terminal_output(log_path: Path):
    """Capture all process stdout/stderr to a timestamped text file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "a", encoding="utf-8") as log_stream:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        captured_stdout = _TimestampedTee(
            original_stdout, log_stream, "STDOUT")
        captured_stderr = _TimestampedTee(
            original_stderr, log_stream, "STDERR")
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        try:
            yield log_path
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            for stream in (captured_stdout, captured_stderr, original_stdout, original_stderr):
                try:
                    stream.flush()
                except Exception:
                    pass


def _to_jsonable(value: Any) -> Any:
    """Recursively convert values to JSON-safe types (e.g., Path -> str)."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    return value


def write_run_metadata(
        experiment_dir: Path,
        metadata: dict[str, Any],
        filename: str = "metadata.json") -> Path:
    """Write the final experiment metadata payload to disk as JSON."""
    file_path = experiment_dir / filename
    save_metadata_json(_to_jsonable(metadata), file_path)
    print(f"Run metadata saved to {file_path}")
    return file_path


def build_run_metadata(
    *,
    run_context: dict[str, Any],
    cough_inputs: dict[str, Any],
    device_context: dict[str, Any],
) -> dict[str, Any]:
    """Construct the run metadata dictionary before JSON serialization.

    This API keeps call sites compact by accepting grouped context dictionaries
    instead of a long list of keyword arguments.
    """
    # Unpack run-level context values.
    config_file_path = run_context["config_file_path"]
    time_start = run_context["time_start"]
    time_finish = run_context["time_finish"]
    experiment_name = run_context["experiment_name"]
    experiment_mode = run_context["experiment_mode"]
    output_dir = run_context["output_dir"]
    wait_before_run_us = run_context["wait_before_run_us"]
    temperature_start = run_context["temperature_start"]
    humidity_start = run_context["humidity_start"]
    temperature_finish = run_context["temperature_finish"]
    humidity_finish = run_context["humidity_finish"]
    comments = run_context["comments"]

    # Unpack device-level context values.
    tcm = device_context["tcm"]
    cough_machine_inputs = device_context["cough_machine_inputs"]
    pump = device_context["pump"]
    pump_inputs = device_context["pump_inputs"]
    record_droplet_size = device_context["record_droplet_size"]
    spraytec_inputs = device_context["spraytec_inputs"]
    spraytec_x_mm = device_context["spraytec_x_mm"]
    spraytec_y_mm = device_context["spraytec_y_mm"]
    spraytec_z_mm = device_context["spraytec_z_mm"]
    lift_pos_z_mm = device_context["lift_pos_z_mm"]
    stage_pos_x_mm = device_context["stage_pos_x_mm"]
    stage_pos_y_mm = device_context["stage_pos_y_mm"]
    spraytec_target_z_mm = device_context["spraytec_target_z_mm"]
    spraytec_audit_path = device_context["spraytec_audit_path"]
    lift = device_context["lift"]

    return {
        "time": {
            "start": time_start,
            "finish": time_finish,
        },
        "experiment": {
            "config_file_path": config_file_path,
            "name": experiment_name,
            "mode": experiment_mode,
            "wait_before_run_us": wait_before_run_us,
            "temperature_start": temperature_start,
            "humidity_start": humidity_start,
            "temperature_finish": temperature_finish,
            "humidity_finish": humidity_finish,
            "comments": comments,
            "output_dir": output_dir,
        },
        "inputs": {
            "cough": cough_inputs,
        },
        "devices": {
            "cough_machine": {
                "name": tcm.name,
                "protocol_version": getattr(tcm, "protocol_version", None),
                "inputs": cough_machine_inputs,
                "connection": {
                    "port": getattr(getattr(tcm, "ser", None), "port", None),
                    "baudrate": tcm.serial_settings.get("baudrate"),
                    "timeout_s": tcm.serial_settings.get("timeout"),
                },
            },
            "pump": {
                "mode": (
                    "enabled"
                    if experiment_mode in ["droplet", "piv"]
                    else "disabled"
                ),
                "inputs": pump_inputs,
                "connection": {
                    "port": getattr(pump, "port", None),
                    "baudrate": getattr(pump, "baudrate", None),
                    "timeout_s": getattr(pump, "timeout_s", None),
                    "pump_address": getattr(pump, "pump_address", None),
                },
                "resolved": {
                    "syringe_volume_ml": getattr(pump, "syringe_volume_ml", None),
                    "rate_ml_per_min": (
                        pump_inputs.get("pump_rate_ml_per_min")
                        if experiment_mode in ["droplet", "piv"]
                        else None
                    ),
                },
            },
            "spraytec": {
                "mode": "enabled" if record_droplet_size else "disabled",
                "inputs": spraytec_inputs,
                "measurement_position_mm": {
                    "x": spraytec_x_mm,
                    "y": spraytec_y_mm,
                    "z": spraytec_z_mm,
                },
                "operator_visible_position_mm": {
                    "stage_x_read_off": stage_pos_x_mm,
                    "stage_y_read_off": stage_pos_y_mm,
                    "lift_pos_z_set": lift_pos_z_mm,
                },
                "audit_csv": spraytec_audit_path,
            },
            "spraytec_lift": {
                "name": getattr(lift, "name", None),
                "connection": {
                    "port": getattr(getattr(lift, "ser", None), "port", None),
                    "baudrate": (
                        None
                        if lift is None
                        else lift.serial_settings.get("baudrate")
                    ),
                    "timeout_s": (
                        None
                        if lift is None
                        else lift.serial_settings.get("timeout")
                    ),
                    "lift_pos_z_mm": (
                        None
                        if lift is None
                        else lift_pos_z_mm
                    ),
                },
            },
        },
    }
