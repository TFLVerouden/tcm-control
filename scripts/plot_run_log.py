from pathlib import Path

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_control.processing.run_log_processing import plot_run_log
from tcm_utils.file_dialogs import ask_directory, ask_open_file


def main() -> int:
    selected_experiment_dir = ask_directory(
        key="plot_run_log_experiment_dir",
        title="Select experiment directory",
        start=Path(__file__).resolve().parent,
    )
    if selected_experiment_dir is None:
        print("No experiment directory selected.")
        return 1

    experiment_dir = Path(selected_experiment_dir).expanduser().resolve()
    run_logs_dir = experiment_dir / "run_logs"
    default_dir = run_logs_dir if run_logs_dir.exists() else experiment_dir

    selected_run_log = ask_open_file(
        key="plot_run_log_csv",
        title="Select run log CSV file",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        default_dir=default_dir,
        start=default_dir,
    )
    if selected_run_log is None:
        print("No run log selected.")
        return 1

    plot_path = plot_run_log(
        run_log_path=Path(selected_run_log),
        experiment_dir=experiment_dir,
        show=True,
    )
    if plot_path is not None:
        print(f"Saved run-log plot: {plot_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
