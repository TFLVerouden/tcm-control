from __future__ import annotations

import csv
import math
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import linregress

from tcm_utils.file_dialogs import find_repo_root
from tcm_utils.time_utils import timestamp_str, timestamp_from_file
from tcm_utils.io_utils import (
    path_relative_to,
    load_two_column_numeric,
    save_metadata_json,
    beep,
    # move_to_raw_subfolder,
    create_timestamped_filename,
    prompt_input,
    wait_with_progress,
)


PRESSURE_COMMAND = "P"  # P: tank, M: nebuliser
DEVICE_NAME = "R_click"
SETTLING_TIME_S = 20
SETPOINTS_BAR = [
    0.0, 0.3, 0.6, 0.9, 1.0, 1.25, 1.5, 1.75, 2.0,
    2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 5.0, 6.0, 7.0,
]
# SETPOINTS_BAR = [0.1, 0.2, 0.3]
REPO_ROOT = find_repo_root(Path(__file__))
CALIBRATION_DIR = REPO_ROOT / "calibration"
RAW_DATA_DIR = CALIBRATION_DIR / "raw_data"
# Set a path to analyze existing readings instead.
INPUT_FILE: Path | None = None
TIMESTAMP_SOURCE = "file"  # "file" or "now"


def main() -> int:
    if PRESSURE_COMMAND not in {"P", "M"}:
        raise ValueError("PRESSURE_COMMAND must be 'P' or 'M'")
    if TIMESTAMP_SOURCE not in {"file", "now"}:
        raise ValueError("TIMESTAMP_SOURCE must be 'file' or 'now'")

    pressure_name = "tank" if PRESSURE_COMMAND == "P" else "nebuliser"
    expected_response = "SET_PRESSURE " if PRESSURE_COMMAND == "P" else "SET_NEB_PRESSURE "
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)

    if INPUT_FILE is not None:
        data_file = INPUT_FILE.expanduser().resolve()
        if not data_file.exists():
            raise FileNotFoundError(f"Input file not found: {data_file}")
    else:
        from tcm_control.devices import CoughMachine

        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        data_file = RAW_DATA_DIR / create_timestamped_filename(
            f"{pressure_name}_{DEVICE_NAME}", timestamp_str(
                include_us=True), "raw", "csv"
        )

        print(
            f"The pressure reported by {PRESSURE_COMMAND}? is not yet calibrated.")
        print("Enter the pressure shown by the external gauge.")
        try:
            tcm = CoughMachine(debug=True)
        finally:
            if sys.stdout.isatty():
                print("\033[0m", end="", flush=True)

        with data_file.open("x", newline="", encoding="utf-8") as raw_file:
            writer = csv.writer(raw_file)
            writer.writerow(["pressure (bar)", "current (mA)"])
            raw_file.flush()
            print(f"Saving readings to {data_file}")

            for setpoint in SETPOINTS_BAR:
                print(f"\nSetting pressure to {setpoint:g} bar.")
                _, lines = tcm._query_and_drain(
                    f"{PRESSURE_COMMAND} {setpoint}", echo=True)
                errors = [line.strip()
                          for line in lines if line.strip().startswith("ERROR")]
                if errors:
                    raise RuntimeError(
                        f"Failed to set pressure: {'; '.join(errors)}")
                if not any(line.strip().startswith(expected_response) for line in lines):
                    raise RuntimeError(
                        f"Missing {expected_response.strip()} response: {lines!r}")

                wait_with_progress(
                    SETTLING_TIME_S, label="Waiting for pressure to settle")
                beep()
                while True:
                    pressure = prompt_input(
                        "Enter the external gauge pressure (bar): ", value_type="float"
                    )
                    if math.isfinite(pressure):
                        break
                    print("Please enter a finite pressure value.")

                _, lines = tcm._query_and_drain(
                    f"{PRESSURE_COMMAND}?", echo=True)
                errors = [line.strip()
                          for line in lines if line.strip().startswith("ERROR")]
                if errors:
                    raise RuntimeError(
                        f"Failed to read pressure: {'; '.join(errors)}")
                current_lines = [
                    line.strip().removeprefix("R Click mA:").strip()
                    for line in lines
                    if line.strip().startswith("R Click mA:")
                ]
                if len(current_lines) != 1:
                    raise RuntimeError(
                        f"Expected one R Click mA reading: {lines!r}")
                try:
                    sensor_current = float(current_lines[0])
                except ValueError as exc:
                    raise RuntimeError(
                        f"Invalid R Click mA reading: {current_lines[0]!r}") from exc
                if not math.isfinite(sensor_current):
                    raise RuntimeError(
                        f"Invalid R Click mA reading: {current_lines[0]!r}")

                writer.writerow([pressure, sensor_current])
                raw_file.flush()

            print("\nReturning the pressure setting to 0 bar.")
            _, lines = tcm._query_and_drain(f"{PRESSURE_COMMAND} 0", echo=True)
            errors = [line.strip()
                      for line in lines if line.strip().startswith("ERROR")]
            if errors:
                raise RuntimeError(
                    f"Failed to set pressure to 0: {'; '.join(errors)}")
            if not any(line.strip().startswith(expected_response) for line in lines):
                raise RuntimeError(
                    f"Missing {expected_response.strip()} response: {lines!r}")

    output_folder = CALIBRATION_DIR
    output_folder.mkdir(parents=True, exist_ok=True)

    pressure_values, sensor_readings = load_two_column_numeric(
        data_file, delimiter=",")

    base_filename = Path(data_file).stem
    if not base_filename.startswith(f"{pressure_name}_"):
        base_filename = f"{pressure_name}_{base_filename}"
    if TIMESTAMP_SOURCE == "file":
        timestamp = timestamp_from_file(data_file, prefer_creation=True)
        timestamp_source_description = "file_creation_time"
    else:
        timestamp = timestamp_str()
        timestamp_source_description = "current_time"

    slope, intercept, r_value, p_value, std_err = linregress(
        sensor_readings, pressure_values
    )

    conversion_factor = slope
    print(
        f"Conversion: p = {conversion_factor:.4f} bar/mA * I - {-intercept:.4f} bar"
    )

    fit_pressure = slope * sensor_readings + intercept
    residuals = pressure_values - fit_pressure

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(
        sensor_readings, pressure_values, label="Data", color="blue", edgecolor="k"
    )
    ax.plot(
        sensor_readings,
        fit_pressure,
        label="Fit: p = {:.4f}I + {:.4f}".format(slope, intercept),
        color="red",
    )

    ax.set_xlabel("Sensor reading (mA)")
    ax.set_xlim(3.5, 20.5)
    ax.set_ylabel("Pressure (bar)")
    ax.set_title(f"Pressure sensor calibration - {base_filename}")
    ax.legend()
    ax.grid()
    fig.tight_layout()

    output_plot = output_folder / create_timestamped_filename(
        base_filename, timestamp, "plot", "pdf"
    )
    fig.savefig(output_plot)

    output_csv = output_folder / create_timestamped_filename(
        base_filename, timestamp, "calibration", "csv"
    )
    csv_header = "sensor_reading_mA,pressure_bar,fit_pressure_bar,residual_bar"
    csv_data = np.column_stack(
        (sensor_readings, pressure_values, fit_pressure, residuals))
    np.savetxt(output_csv, csv_data, delimiter=",",
               header=csv_header, comments="")

    # # Move the original raw file into a raw_data subfolder
    # moved_raw = move_to_raw_subfolder(data_file, output_folder)

    metadata = {
        "timestamp": timestamp,
        "timestamp_source": timestamp_source_description,
        "analysis_run_time": timestamp_str(),
        "input_file_original": path_relative_to(Path(data_file), REPO_ROOT),
        # "raw_data_path": path_relative_to(moved_raw, repo_root),
        "output_files": {
            "plot_pdf": path_relative_to(output_plot, REPO_ROOT),
            "calibration_csv": path_relative_to(output_csv, REPO_ROOT),
        },
        "fit": {
            "slope_bar_per_mA": slope,
            "intercept_bar": intercept,
            "r_value": r_value,
            "p_value": p_value,
            "std_err": std_err,
            "r_squared": r_value ** 2,
        },
    }

    metadata_path = output_folder / create_timestamped_filename(
        base_filename, timestamp, "metadata", "json"
    )
    save_metadata_json(metadata, metadata_path)

    print(f"CSV written to {output_csv}")
    print(f"Metadata written to {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
