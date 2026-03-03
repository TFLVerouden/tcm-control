from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import linregress

from tcm_utils.file_dialogs import ask_open_file, find_repo_root
from tcm_utils.time_utils import timestamp_str, timestamp_from_file
from tcm_utils.io_utils import (
    path_relative_to,
    load_two_column_numeric,
    save_metadata_json,
    # move_to_raw_subfolder,
    create_timestamped_filename,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pressure sensor calibration")
    parser.add_argument(
        "--input",
        type=Path,
        help="Path to CSV/TXT data file (skip dialog if provided)",
    )
    parser.add_argument(
        "--timestamp-source",
        choices=["file", "now"],
        default="file",
        help="Use 'file' creation/mod time or current time for outputs.",
    )
    args = parser.parse_args(argv)

    repo_root = find_repo_root(Path(__file__))
    docs_calibration_dir = repo_root / "docs" / "calibration"
    docs_calibration_dir.mkdir(parents=True, exist_ok=True)

    data_file: Path | None
    if args.input is not None:
        data_file = args.input.expanduser().resolve()
        if not data_file.exists():
            raise FileNotFoundError(f"Input file not found: {data_file}")
    else:
        data_file = ask_open_file(
            key="pressure_calibration",
            title="Select calibration data file",
            filetypes=[("Text or CSV files", "*.txt *.csv"),
                       ("All files", "*.*")],
            default_dir=docs_calibration_dir,
            start=Path(__file__),
        )
        if not data_file:
            print("No file selected. Exiting.")
            return 1

    output_folder = docs_calibration_dir
    output_folder.mkdir(parents=True, exist_ok=True)

    pressure_values, sensor_readings = load_two_column_numeric(
        data_file, delimiter=",")

    base_filename = Path(data_file).stem
    if args.timestamp_source == "file":
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

    plt.figure(figsize=(8, 6))
    plt.scatter(
        sensor_readings, pressure_values, label="Data", color="blue", edgecolor="k"
    )
    plt.plot(
        sensor_readings,
        fit_pressure,
        label="Fit: p = {:.4f}I + {:.4f}".format(slope, intercept),
        color="red",
    )
    plt.xlabel("Sensor reading (mA)")
    plt.ylabel("Pressure (bar)")
    plt.title(f"Pressure sensor calibration - {base_filename}")
    plt.legend()
    plt.grid()
    plt.tight_layout()

    output_plot = output_folder / create_timestamped_filename(
        base_filename, timestamp, "plot", "pdf"
    )
    plt.savefig(output_plot)

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
        "input_file_original": path_relative_to(Path(data_file), repo_root),
        # "raw_data_path": path_relative_to(moved_raw, repo_root),
        "output_files": {
            "plot_pdf": path_relative_to(output_plot, repo_root),
            "calibration_csv": path_relative_to(output_csv, repo_root),
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
