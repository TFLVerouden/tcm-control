"""File and metadata logging utilities for experiment runs."""

from pathlib import Path
import time
from typing import Any

from tcm_utils.io_utils import create_timestamped_filename, save_metadata_json
from tcm_utils.time_utils import timestamp_str, timestamp_from_file

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
    file_path = experiment_dir / f"run_log_{run_nr}.txt"
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
        flow_curve_path: Path):
    """Copy the active flow-curve file for traceability of each run."""

    # Copy the flow curve file to the experiment directory for record-keeping
    dest_path = experiment_dir / f"flow_curve_{flow_curve_path.name}"
    with open(flow_curve_path, "r") as src, open(dest_path, "w") as dst:
        dst.write(src.read())

    print(f"Flow curve copied to {dest_path}")


def create_labeled_csv_filename(
        prefix: str,
        label: int | str | None,
        timestamp: str | None = None) -> str:
    """Build a timestamped CSV filename with an optional label."""
    if timestamp is None:
        timestamp = time.strftime("%y%m%d_%H%M%S")

    safe_label = "" if label is None else str(label)
    return f"{prefix}{safe_label}_{timestamp}.csv"


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
    time_start: str,
    time_finish: str,
    experiment_name: str,
    experiment_mode: str,
    output_dir: Path,
    wait_before_run_us: int,
    temperature_start: float | None,
    humidity_start: float | None,
    temperature_finish: float | None,
    humidity_finish: float | None,
    comments: str,
    core_inputs: dict[str, Any],
    tcm: Any,
    cough_machine_inputs: dict[str, Any],
    pump: Any,
    pump_inputs: dict[str, Any],
    record_droplet_size: bool,
    spraytec_inputs: dict[str, Any],
    spraytec_x: float | None,
    spraytec_y: float | None,
    spraytec_z: float | None,
    lift_height: float | None,
    spraytec_audit_path: str | Path | None,
    lift: Any,
) -> dict[str, Any]:
    """Construct the run metadata dictionary before JSON serialization."""
    return {
        "time": {
            "start": time_start,
            "finish": time_finish,
        },
        "experiment": {
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
            "core": core_inputs,
        },
        "devices": {
            "cough_machine": {
                "name": tcm.name,
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
                        pump_inputs.get("droplet_pump_rate_ml_per_min")
                        if experiment_mode in ["droplet", "piv"]
                        else None
                    ),
                },
            },
            "spraytec": {
                "mode": "enabled" if record_droplet_size else "disabled",
                "inputs": spraytec_inputs,
                "measurement_position_mm": {
                    "x": spraytec_x,
                    "y": spraytec_y,
                    "z": spraytec_z,
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
                    "lift_height_mm": (
                        None
                        if lift is None
                        else lift_height
                    ),
                },
            },
        },
    }
