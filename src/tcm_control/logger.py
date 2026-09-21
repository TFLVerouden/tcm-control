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


def latest_experiment_display_name(series_directory: Path) -> str | None:
    """Return a display name for the newest experiment folder, if any."""
    try:
        candidates = [path for path in series_directory.iterdir()
                      if path.is_dir()]
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return None

    if not candidates:
        return None

    try:
        latest = max(candidates, key=lambda path: path.stat().st_mtime)
    except (FileNotFoundError, PermissionError, OSError):
        return None

    latest_name = latest.name

    # Strip known folder prefix: YYMMDD_HHMMSS_ -> experiment name.
    if len(latest_name) > 14 and latest_name[6:7] == "_" and latest_name[13:14] == "_":
        return latest_name[14:]

    return latest_name


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
        meta: dict[str, Any],
        filename: str = "metadata.json") -> Path:
    """Write the final experiment metadata payload to disk as JSON."""
    file_path = experiment_dir / filename
    save_metadata_json(_to_jsonable(meta), file_path)
    print(f"Run metadata saved to {file_path}")
    return file_path


def build_run_metadata(config, **meta) -> dict[str, Any]:
    """Construct the run metadata dictionary.
    """

    debug_mode = config["inputs"]["cough"]["debug_mode"]
    nr_runs = config["inputs"]["cough"]["nr_runs"]
    multi_run_interval_s = config["inputs"]["cough"]["multi_run_interval_s"]
    confirm_before_starting_next_run = config["inputs"]["cough"]["confirm_before_starting_next_run"]
    record_droplet_size = config["inputs"]["cough"]["record_droplet_size"]
    config_file_path = config["experiment"]["config_file_path"]

    # Prefer configured syringe geometry values because runtime objects may
    # not expose table-based conversions in all pump implementations.
    # configured_syringe_volume_ml = meta["pump_inputs"].get(
    #     "syringe_volume_ml")
    # configured_syringe_diameter_mm = meta["pump_inputs"].get(
    #     "syringe_diameter_mm")

    runtime_syringe_volume_ml = getattr(
        meta["pump"], "syringe_volume_ml", None)
    runtime_syringe_diameter_mm = getattr(
        meta["pump"], "syringe_diameter_mm", None)

    if runtime_syringe_diameter_mm is None and meta["pump"] is not None and hasattr(meta["pump"], "get_diameter"):
        try:
            runtime_syringe_diameter_mm = float(
                meta["pump"].get_diameter())
        except Exception:
            runtime_syringe_diameter_mm = None

    # resolved_syringe_volume_ml = (
    #     configured_syringe_volume_ml
    #     if configured_syringe_volume_ml is not None
    #     else runtime_syringe_volume_ml
    # )
    # resolved_syringe_diameter_mm = (
    #     configured_syringe_diameter_mm
    #     if configured_syringe_diameter_mm is not None
    #     else runtime_syringe_diameter_mm
    # )

    return {
        "experiment": {
            "name": meta["experiment_name"],
            "mode": meta["experiment_mode"],
            "time": {
                "start": meta["time_start"],
                "finish": meta["time_finish"],
            },
            "files": {
                "config_file_path": config_file_path,
                "output_dir": meta["output_dir"],
            },
            "settings": {
                "nr_runs": nr_runs,
                "multi_run_interval_s": multi_run_interval_s,
                "confirm_before_starting_next_run": confirm_before_starting_next_run,
                "wait_before_run_us": meta["wait_before_run_us"],
            },
            "measurements": {
                "temperature": {
                    "start": meta["temperature_start"],
                    "finish": meta["temperature_finish"],
                },
                "humidity": {
                    "start": meta["humidity_start"],
                    "finish": meta["humidity_finish"],
                },
                "film_height_mm": meta["film_height_mm"],
            },
            "comments": meta["comments"],
            "debug_mode": debug_mode,
        },
        "devices": {
            "cough_machine": {
                "name": meta["tcm"].name,
                "protocol_version": getattr(meta["tcm"], "protocol_version", None),
                "inputs": meta["cough_machine_inputs"],
                "connection": {
                    "port": getattr(getattr(meta["tcm"], "ser", None), "port", None),
                    "baudrate": meta["tcm"].serial_settings.get("baudrate"),
                    "timeout_s": meta["tcm"].serial_settings.get("timeout"),
                },
            },
            "pump": {
                "mode": (
                    "enabled"
                    if meta["experiment_mode"] in ["droplet", "piv"]
                    else "disabled"
                ),
                # "inputs": meta["pump_inputs"],
                "syringe": meta["syringe_inputs"],
                "layer": meta["layer_inputs"],
                "connection": {
                    "port": getattr(meta["pump"], "port", None),
                    "baudrate": getattr(meta["pump"], "baudrate", None),
                    "timeout_s": getattr(meta["pump"], "timeout_s", None),
                    "pump_address": getattr(meta["pump"], "pump_address", None),
                },
                # "resolved": {
                #     "syringe_volume_ml": resolved_syringe_volume_ml,
                #     "syringe_diameter_mm": resolved_syringe_diameter_mm,
                #     "rate_ml_per_min": (
                #         meta["pump_inputs"].get("pump_rate_ml_per_min")
                #         if meta["experiment_mode"] in ["droplet", "piv"]
                #         else None
                #     ),
                # },
            },
            "camera": {
                "inputs": meta["camera_inputs"],
            },
            "spraytec": {
                "mode": "enabled" if record_droplet_size else "disabled",
                "inputs": meta["spraytec_inputs"],
                "measurement_position_mm": {
                    "x": meta["spraytec_x_mm"],
                    "y": meta["spraytec_y_mm"],
                    "z": meta["spraytec_z_mm"],
                },
                "operator_readable_position_mm": {
                    "stage_x_read_off": meta["stage_pos_x_mm"],
                    "stage_y_read_off": meta["stage_pos_y_mm"],
                    "stage_pos_z_set": meta["stage_pos_z_mm"],
                },
                "audit_csv": meta["spraytec_audit_path"],
                "laser_intensity": meta["spraytec_laser_intensity"],
            },
            "vertical_stage": {
                "name": getattr(meta["vertical_stage"], "name", None),
                "connection": {
                    "port": getattr(getattr(meta["vertical_stage"], "ser", None), "port", None),
                    "baudrate": (
                        None
                        if meta["vertical_stage"] is None
                        else meta["vertical_stage"].serial_settings.get("baudrate")
                    ),
                    "timeout_s": (
                        None
                        if meta["vertical_stage"] is None
                        else meta["vertical_stage"].serial_settings.get("timeout")
                    ),
                    "lift_pos_z_mm": (
                        None
                        if meta["vertical_stage"] is None
                        else meta["vertical_stage"].serial_settings.get("lift_pos_z_mm")
                    ),
                },
            },
        },
    }
