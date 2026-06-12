from __future__ import annotations

from pathlib import Path

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.processing.common import get_processed_dir
from tcm_control.processing.spraytec_processing import (
    load_spraytec_csvs,
)
from tcm_control.processing.spraytec_plotting import time_average_distribution
from tcm_utils.file_dialogs import ask_directory

# ------------------------------
# Simple settings (edit these)
# ------------------------------
# Set to a parent folder containing experiment subfolders,
# or leave as None to select via folder dialog.
PARENT_DIR: str | None = None

CSV_PATTERN = "spraytec*.csv"

# One required averaging interval in milliseconds, relative to trigger (t = 0).
INTERVAL_MS = (0, 350)


def process_experiment(experiment_dir: Path) -> tuple[int, Path, Path]:
    candidate = experiment_dir / "spraytec"
    spraytec_dir = candidate if candidate.exists(
    ) and candidate.is_dir() else experiment_dir

    dir_name = f"spraytec_averages_{INTERVAL_MS[0]}-{INTERVAL_MS[1]}ms"
    output_dir = get_processed_dir(experiment_dir) / dir_name
    output_dir.mkdir(parents=True, exist_ok=True)

    spraytec_data_list = load_spraytec_csvs(spraytec_dir, pattern=CSV_PATTERN)

    for spraytec_data in spraytec_data_list:
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

    return len(spraytec_data_list), spraytec_dir, output_dir


def main() -> int:
    if INTERVAL_MS[1] <= INTERVAL_MS[0]:
        raise ValueError(f"INTERVAL_MS invalid: {INTERVAL_MS}")

    if PARENT_DIR is None:
        selected = ask_directory(
            key="average_spraytec_parent_dir",
            title="Select parent directory containing experiment folders",
            start=Path(__file__).resolve().parent,
        )
        if not selected:
            print("No parent directory selected.")
            return 1
        parent_dir = Path(selected).expanduser().resolve()
    else:
        parent_dir = Path(PARENT_DIR).expanduser().resolve()

    if not parent_dir.exists() or not parent_dir.is_dir():
        raise FileNotFoundError(f"Parent directory not found: {parent_dir}")

    experiment_dirs = sorted(
        path for path in parent_dir.iterdir() if path.is_dir())
    if not experiment_dirs:
        print(f"No subfolders found in: {parent_dir}")
        return 1

    print(f"Found {len(experiment_dirs)} experiment folders in: {parent_dir}")

    succeeded = 0
    failed: list[tuple[Path, str]] = []
    total_files_processed = 0

    for experiment_dir in experiment_dirs:
        print(f"\nProcessing experiment: {experiment_dir.name}")
        try:
            files_processed, spraytec_dir, output_dir = process_experiment(
                experiment_dir)
            total_files_processed += files_processed
            succeeded += 1
            print(f"Processed SprayTec directory: {spraytec_dir}")
            print(f"Output directory: {output_dir}")
            print(f"Files processed: {files_processed}")
        except Exception as exc:
            failed.append((experiment_dir, str(exc)))
            print(f"Failed: {experiment_dir} -> {exc}")

    print("\nSummary")
    print(f"Experiment folders found: {len(experiment_dirs)}")
    print(f"Succeeded: {succeeded}")
    print(f"Failed: {len(failed)}")
    print(f"Total SprayTec files processed: {total_files_processed}")
    print(
        "Generated time-average CSV and PDF outputs for trigger-relative interval: "
        f"[{INTERVAL_MS[0]}, {INTERVAL_MS[1]}] ms."
    )

    if failed:
        print("\nFailed experiments:")
        for folder, error in failed:
            print(f"- {folder.name}: {error}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
