from __future__ import annotations

from pathlib import Path

from tcm_control.processing.common import get_processed_dir
from tcm_control.processing.spraytec_plotting import export_time_dependent_columns_csv
from tcm_control.processing.spraytec_processing import (
    export_combined_spraytec_metadata_json,
    export_spraytec_metadata_json,
    load_spraytec_csvs,
)
from tcm_utils.io_utils import ask_directory

# ------------------------------
# Simple settings (edit these)
# ------------------------------
# Set to a parent folder containing experiment subfolders,
# or leave as None to select via folder dialog.
PARENT_DIR: str | None = None

CSV_PATTERN = "spraytec*.csv"


def process_experiment(experiment_dir: Path) -> tuple[int, Path, Path]:
    candidate = experiment_dir / "spraytec"
    spraytec_dir = candidate if candidate.exists(
    ) and candidate.is_dir() else experiment_dir
    output_dir = get_processed_dir(experiment_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    spraytec_data_list = load_spraytec_csvs(spraytec_dir, pattern=CSV_PATTERN)

    exported_paths: list[Path] = []
    metadata_paths: list[Path] = []
    for spraytec_data in spraytec_data_list:
        metadata_paths.append(
            export_spraytec_metadata_json(
                spraytec_data,
                output_dir=output_dir,
            )
        )

        exported_path = export_time_dependent_columns_csv(
            spraytec_data,
            output_dir=output_dir,
        )
        exported_paths.append(exported_path)

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
    for path in exported_paths:
        print(f"Saved time-dependent columns CSV: {path}")

    return len(spraytec_data_list), spraytec_dir, output_dir


def main() -> int:
    if PARENT_DIR is None:
        selected = ask_directory(
            key="residuals_transmission_parent_dir",
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
        "Generated time-dependent CSV outputs and metadata in each experiment's processed folder."
    )

    if failed:
        print("\nFailed experiments:")
        for folder, error in failed:
            print(f"- {folder.name}: {error}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
