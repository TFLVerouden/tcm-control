from pathlib import Path
import time
from tcm_utils.io_utils import create_timestamped_filename, save_metadata_json
from tcm_utils.time_utils import timestamp_str, timestamp_from_file

# In the destination folder, put several files: metadata (json),
# cough machine event log (csv, multiple in case of droplet detection),
# a copy of the flow curve (csv), comments about the run (txt),
# and some plots (pdf) of the data.


def create_experiment_dir(
    experiment_dir: Path,
    experiment_name: str,
    start_time: str | None = None,
) -> Path:

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
    file_path = experiment_dir / "comments.txt"
    with open(file_path, "w") as f:
        f.write(comments)

    print(f"Comments saved to {file_path}")


def copy_flow_curve(
        experiment_dir: Path,
        flow_curve_path: Path):

    # Copy the flow curve file to the experiment directory for record-keeping
    dest_path = experiment_dir / f"flow_curve_{flow_curve_path.name}"
    with open(flow_curve_path, "r") as src, open(dest_path, "w") as dst:
        dst.write(src.read())

    print(f"Flow curve copied to {dest_path}")


def create_labeled_csv_filename(
        prefix: str,
        label: int | str | None,
        timestamp: str | None = None) -> str:
    if timestamp is None:
        timestamp = time.strftime("%y%m%d_%H%M%S")

    safe_label = "" if label is None else str(label)
    return f"{prefix}{safe_label}_{timestamp}.csv"
