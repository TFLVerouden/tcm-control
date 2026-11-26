"""File and metadata logging utilities for experiment runs."""

from contextlib import contextmanager
import csv
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
    experiment_name: str | None,
    start_time: str | None = None,
) -> Path:
    """Create a timestamped output directory for one experiment."""

    # Create a timestamped directory for the experiment if not provided
    if start_time is None:
        start_time = timestamp_str()

    # Create the experiment directory
    dir_name = f"{start_time}_{experiment_name}" if experiment_name else start_time
    experiment_dir = experiment_dir / dir_name
    experiment_dir.mkdir(parents=True, exist_ok=False)

    # Return path
    return experiment_dir


def create_run_dir(
    experiment_dir: Path | None, run_number: int, nr_runs: int
) -> Path | None:
    """Create the run directory, or return None when saving is disabled."""
    if experiment_dir is None:
        return None

    # Use a simple name for a single run and numbered names for multiple runs
    run_name = "run" if nr_runs == 1 else f"run{run_number}"
    run_dir = experiment_dir / run_name
    run_dir.mkdir()
    return run_dir


def write_film_measurement(
    run_dir: Path, measurement: dict[str, int | float | str | None]
) -> None:
    """Save a single film measurement in its run directory."""
    # Keep column names and values together in the run's CSV
    with (run_dir / "film_measurement.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=measurement.keys())
        writer.writeheader()
        writer.writerow(measurement)


def write_ambient_measurement(
    run_dir: Path, temperature_degC: float | None, relative_humidity_percent: float | None
) -> None:
    """Save the ambient conditions in the run directory, empty if unavailable."""
    with (run_dir / "temperature_humidity.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["time", "temperature_degC", "relative_humidity_percent"])
        writer.writerow(
            [timestamp_str(), temperature_degC, relative_humidity_percent])


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

    def set_log_stream(self, log_stream: TextIO) -> None:
        """Redirect subsequent writes to a new log file after relocation."""
        self._log_stream = log_stream
        self._log_stream_broken = False
        self._line_start = True


PENDING_CONSOLE_LOGS_DIRNAME = ".logs"


def create_pending_console_log_path() -> Path:
    """Return a temp path (repo root/.logs) to log to before the experiment dir exists."""
    from tcm_utils.file_dialogs import find_repo_root

    logs_dir = find_repo_root() / PENDING_CONSOLE_LOGS_DIRNAME
    return logs_dir / f"pending_{timestamp_str()}.txt"


class ConsoleLogCapture:
    """Mirrors stdout/stderr to a log file, relocatable while the process runs."""

    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = log_path
        self._log_stream = open(log_path, "a", encoding="utf-8")
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._stdout_tee = _TimestampedTee(
            self._original_stdout, self._log_stream, "STDOUT")
        self._stderr_tee = _TimestampedTee(
            self._original_stderr, self._log_stream, "STDERR")
        sys.stdout = self._stdout_tee
        sys.stderr = self._stderr_tee

    def relocate(self, new_path: Path) -> Path:
        """Move the log file to new_path and keep mirroring output there."""
        self._log_stream.flush()
        self._log_stream.close()
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.log_path), str(new_path))
        self._log_stream = open(new_path, "a", encoding="utf-8")
        self._stdout_tee.set_log_stream(self._log_stream)
        self._stderr_tee.set_log_stream(self._log_stream)
        self.log_path = new_path
        return new_path

    def close(self) -> None:
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        for stream in (self._stdout_tee, self._stderr_tee, self._original_stdout, self._original_stderr):
            try:
                stream.flush()
            except Exception:
                pass
        try:
            self._log_stream.close()
        except Exception:
            pass

    def remove(self) -> None:
        """Delete the log file and stop mirroring output."""
        self.close()
        try:
            self.log_path.unlink(missing_ok=True)
        except Exception:
            pass


@contextmanager
def capture_terminal_output(log_path: Path):
    """Capture all process stdout/stderr to a timestamped text file."""
    capture = ConsoleLogCapture(log_path)
    try:
        yield capture.log_path
    finally:
        capture.close()


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
        filename: str = "metadata.json",
        title: str = "Run metadata"
) -> Path:
    """Write the final experiment metadata payload to disk as JSON."""
    file_path = experiment_dir / filename
    # Replace the previous snapshot only after the new JSON is complete
    temp_path = experiment_dir / f".{filename}.tmp"
    try:
        save_metadata_json(_to_jsonable(meta), temp_path)
        temp_path.replace(file_path)
    finally:
        temp_path.unlink(missing_ok=True)
    print(f"{title} saved to {file_path}")
    return file_path


def build_run_metadata(
    config: dict[str, Any], *, time_start: str, output_dir: Path, tcm: Any,
    time_finish: str | None = None, temperature_start: float | None = None,
    humidity_start: float | None = None, temperature_finish: float | None = None,
    humidity_finish: float | None = None, comments: str | None = None,
    pump: Any = None, camera: Any = None, ops: Any = None,
    spraytec: Any = None, vertical_stage: Any = None,
    spraytec_x_mm: float | None = None, spraytec_y_mm: float | None = None,
    spraytec_z_mm: float | None = None, spraytec_audit_path: Path | None = None,
    spraytec_laser_intensity: float | None = None, stage_pos_z_mm: float | None = None,
) -> dict[str, Any]:
    """Combine the complete resolved configuration with runtime-only facts."""
    # Device modules import logger, so defer this device-dependent module.
    from tcm_control import liquid_film

    return {
        "schema_version": 1,
        "configuration": config,
        "runtime": {
            "status": "completed" if time_finish is not None else "in_progress",
            "time": {"start": time_start, "finish": time_finish},
            "output_dir": output_dir,
            "measurements": {
                "temperature": {"start": temperature_start, "finish": temperature_finish},
                "humidity": {"start": humidity_start, "finish": humidity_finish},
            },
            "comments": comments,
            "processing": {
                "film_height": {
                    "image_crop_left": liquid_film.IMAGE_CROP_LEFT,
                    "canny_thr1": liquid_film.CANNY_THR1,
                    "canny_thr2": liquid_film.CANNY_THR2,
                    "plate_height_crossing_tolerance_px":
                        liquid_film.PLATE_HEIGHT_CROSSING_TOLERANCE_PX,
                    "film_height_average_width_px":
                        liquid_film.FILM_HEIGHT_AVERAGE_WIDTH_PX,
                    "contact_angle_fit_width_px":
                        liquid_film.CONTACT_ANGLE_FIT_WIDTH_PX,
                    "contact_point_roi": liquid_film.CONTACT_POINT_ROI,
                    "plate_background_extension_px":
                        liquid_film.PLATE_BACKGROUND_EXTENSION_PX,
                    "threshold_method": "skimage.filters.threshold_minimum",
                    "edge_detection": "OpenCV Canny on vertically flipped binary images",
                    "film_subtraction": "eroded binary background minus binary film image",
                    "rim_selection": "highest edge pixel per image column",
                    "plate_height_selection": "mean rim height excluding left crop",
                    "film_height_selection":
                        "mean around rightmost highest rim point, with window clipped to image",
                    "contact_point_selection":
                        "rightmost near mean plate level, then near plate rim, otherwise extrapolation",
                    "contact_angle": "acute angle of linear rim fit",
                    "film_height_error":
                        "root-sum-square of plate and film rim standard deviations, scaled to mm",
                },
            },
            "devices": {
                "cough_machine": tcm.metadata(),
                "pump": pump.metadata() if pump is not None else None,
                "camera": camera.metadata() if camera is not None else None,
                "ops": ops.metadata() if ops is not None else None,
                "spraytec": {
                    **(spraytec.metadata() if spraytec is not None else {}),
                    "measurement_position_mm": {
                        "x": spraytec_x_mm, "y": spraytec_y_mm, "z": spraytec_z_mm,
                    },
                    "stage_pos_z_mm": stage_pos_z_mm,
                    "audit_csv": spraytec_audit_path,
                    "laser_intensity": spraytec_laser_intensity,
                },
                "vertical_stage": vertical_stage.metadata() if vertical_stage is not None else None,
            },
        },
    }
