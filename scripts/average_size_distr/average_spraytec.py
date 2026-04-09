from __future__ import annotations

from pathlib import Path

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.processing.spraytec_processing import (
    export_combined_spraytec_metadata_json,
    export_spraytec_metadata_json,
    load_spraytec_csvs,
)
from tcm_control.processing.spraytec_plotting import time_average_distribution
from tcm_control.processing.common import get_processed_dir
from tcm_utils.file_dialogs import ask_directory

# ------------------------------
# Simple settings (edit these)
# ------------------------------
# Set to an experiment folder, or leave as None to select via folder dialog.
EXPERIMENT_DIR: str | None = None

CSV_PATTERN = "spraytec*.csv"

# One required averaging interval in milliseconds, relative to trigger (t = 0).
INTERVAL_MS = (30, 130)


def main() -> int:
    if INTERVAL_MS[1] <= INTERVAL_MS[0]:
        raise ValueError(f"INTERVAL_MS invalid: {INTERVAL_MS}")

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
        raise FileNotFoundError(
            f"Experiment directory not found: {experiment_dir}")

    candidate = experiment_dir / "spraytec"
    spraytec_dir = candidate if candidate.exists(
    ) and candidate.is_dir() else experiment_dir
    dir_name = f"spraytec_averages_{INTERVAL_MS[0]}-{INTERVAL_MS[1]}ms"
    output_dir = get_processed_dir(experiment_dir) / dir_name
    output_dir.mkdir(parents=True, exist_ok=True)

    spraytec_data_list = load_spraytec_csvs(spraytec_dir, pattern=CSV_PATTERN)

    metadata_paths: list[Path] = []
    for spraytec_data in spraytec_data_list:
        metadata_paths.append(
            export_spraytec_metadata_json(
                spraytec_data,
                output_dir=output_dir,
            )
        )

        time_average_distribution(
            spraytec_data=spraytec_data,
            start_time_ms=INTERVAL_MS[0],
            end_time_ms=INTERVAL_MS[1],
            trigger_column="Trigger",
            export_csv=True,
            export_pdf=True,
            plot=True,
            output_dir=output_dir,
        )

    combined_metadata_path = export_combined_spraytec_metadata_json(
        spraytec_data_list,
        output_dir=output_dir,
    )

    print(f"Processed SprayTec directory: {spraytec_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Files processed: {len(spraytec_data_list)}")
    for path in metadata_paths:
        print(f"Saved metadata: {path}")
    print(f"Saved combined metadata: {combined_metadata_path}")
    print(
        "Generated time-average CSV and PDF outputs for trigger-relative interval: "
        f"[{INTERVAL_MS[0]}, {INTERVAL_MS[1]}] ms."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
