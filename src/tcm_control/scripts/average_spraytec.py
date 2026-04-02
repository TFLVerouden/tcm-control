from __future__ import annotations

from pathlib import Path

from tcm_control.processing.spraytec_processing import (
    export_combined_spraytec_metadata_json,
    export_spraytec_metadata_json,
    load_spraytec_csvs,
    time_average_distribution,
)
from tcm_utils.file_dialogs import ask_directory

# ------------------------------
# Simple settings (edit these)
# ------------------------------
# Set to an experiment folder, or leave as None to select via folder dialog.
EXPERIMENT_DIR: str | None = None

# Optional override for the folder containing spraytec*.csv files.
# If None, script tries <experiment>/spraytec and then <experiment>.
SPRAYTEC_DIR: str | None = None

CSV_PATTERN = "spraytec*.csv"

# Two required averaging intervals in seconds.
INTERVAL_1 = (0.000, 1.000)
INTERVAL_2 = (1.000, 2.000)


def main() -> int:
    if INTERVAL_1[1] <= INTERVAL_1[0]:
        raise ValueError(f"INTERVAL_1 invalid: {INTERVAL_1}")
    if INTERVAL_2[1] <= INTERVAL_2[0]:
        raise ValueError(f"INTERVAL_2 invalid: {INTERVAL_2}")

    if EXPERIMENT_DIR is None:
        selected = ask_directory(
            key="average_spraytec_experiment_dir",
            title="Select experiment directory",
            start=Path(__file__).resolve().parent,
        )
        if not selected:
            print("No experiment directory selected.")
            return 1
        experiment_dir = Path(selected).expanduser().resolve()
    else:
        experiment_dir = Path(EXPERIMENT_DIR).expanduser().resolve()

    if not experiment_dir.exists() or not experiment_dir.is_dir():
        raise FileNotFoundError(f"Experiment directory not found: {experiment_dir}")

    if SPRAYTEC_DIR is not None:
        spraytec_dir = Path(SPRAYTEC_DIR).expanduser().resolve()
    else:
        candidate = experiment_dir / "spraytec"
        spraytec_dir = candidate if candidate.exists() and candidate.is_dir() else experiment_dir

    spraytec_data_list = load_spraytec_csvs(spraytec_dir, pattern=CSV_PATTERN)

    metadata_paths: list[Path] = []
    for spraytec_data in spraytec_data_list:
        metadata_paths.append(export_spraytec_metadata_json(spraytec_data))

        time_average_distribution(
            spraytec_data=spraytec_data,
            start_time_s=INTERVAL_1[0],
            end_time_s=INTERVAL_1[1],
            export_csv=True,
            export_pdf=True,
            plot=True,
        )
        time_average_distribution(
            spraytec_data=spraytec_data,
            start_time_s=INTERVAL_2[0],
            end_time_s=INTERVAL_2[1],
            export_csv=True,
            export_pdf=True,
            plot=True,
        )

    combined_metadata_path = export_combined_spraytec_metadata_json(spraytec_data_list)

    print(f"Processed SprayTec directory: {spraytec_dir}")
    print(f"Files processed: {len(spraytec_data_list)}")
    for path in metadata_paths:
        print(f"Saved metadata: {path}")
    print(f"Saved combined metadata: {combined_metadata_path}")
    print(
        "Generated time-average CSV and PDF outputs for intervals: "
        f"[{INTERVAL_1[0]:.3f}, {INTERVAL_1[1]:.3f}] s and "
        f"[{INTERVAL_2[0]:.3f}, {INTERVAL_2[1]:.3f}] s."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
