from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd

from tcm_utils.file_dialogs import ask_directory
from tcm_utils.io_utils import make_minimal_progress_bar

#code adapted from combine_timed.py, but now only reads the cv_ppm values within the time window and organizes them by height (or folder name if height not detected).

# ------------------------------
# Settings
# ------------------------------
PARENT_DIR: str | None = None
CSV_SUFFIX = "_time_dependent_columns.csv"
INTERVAL_MS = (0, 700)
TARGET_COLUMN = "cv_ppm"


def _first_existing(candidates: list[str], available_columns: list[str]) -> str | None:
    normalized_to_original = {
        str(col).strip().lower(): str(col) for col in available_columns
    }
    for candidate in candidates:
        resolved = normalized_to_original.get(candidate.strip().lower())
        if resolved is not None:
            return resolved
    return None


def main() -> int:
    if PARENT_DIR is None:
        selected = ask_directory(
            key="combine_timed_parent_dir",
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
        path
        for path in parent_dir.iterdir()
        if path.is_dir() and not path.name.lower().startswith("processed")
    )
    if not experiment_dirs:
        print(f"No subfolders found in: {parent_dir}")
        return 1
    print("Found experiment folders:", [p.name for p in experiment_dirs])
    # Detect height from folder name (e.g. "50mm" or "-80mm")
    height_pattern = re.compile(r"(-?\d+)\s*mm", re.IGNORECASE)
    experiment_info: list[tuple[Path, int | None]] = []
    for experiment_dir in experiment_dirs:
        match = height_pattern.search(experiment_dir.name)
        detected_height_mm = int(match.group(1)) if match else None
        experiment_info.append((experiment_dir, detected_height_mm))

    # Sort by height descending if all heights were detected
    if all(h is not None for _, h in experiment_info):
       experiment_info.sort(
    key=lambda item: item[1] if item[1] is not None else -1,
    reverse=True,
)
    # Collect CSVs per experiment folder
    subfolder_csvs: list[tuple[Path, list[Path]]] = []
    with make_minimal_progress_bar(
        total=len(experiment_info),
        label="Collecting timed data",
        unit_label="folders",
    ) as pbar:
        for experiment_dir, _ in experiment_info:
            csv_paths = sorted(
                path
                for path in experiment_dir.rglob("*.csv")
                if path.is_file() and path.name.endswith(CSV_SUFFIX)
            )
            subfolder_csvs.append((experiment_dir, csv_paths))
            pbar.update(1)
   
  
    # Load CSVs and extract cv_ppm within the time window
    # Result: dict mapping height_mm (or folder name) -> array of cv_ppm values
    cv_by_height: dict[str, list[np.ndarray]] = {}

    for (experiment_dir, detected_height_mm), (_, csv_paths) in zip(experiment_info, subfolder_csvs):
        key = f"{detected_height_mm}mm" if detected_height_mm is not None else experiment_dir.name
        runs: list[np.ndarray] = []

        for csv_path in csv_paths:
            try:
                df = pd.read_csv(csv_path)
            except Exception as exc:
                print(f"Skipping unreadable file {csv_path.name}: {exc}")
                continue

            if df.empty:
                continue

            time_col = _first_existing(
                ["time_s", "time", "time [s]", "time(s)"],
                [str(col) for col in df.columns],
            )
            if time_col is None:
                print(f"Skipping {csv_path.name}: no time column found.")
                continue

            cv_col = _first_existing([TARGET_COLUMN], [str(col) for col in df.columns])
            if cv_col is None:
                print(f"Skipping {csv_path.name}: '{TARGET_COLUMN}' column not found.")
                continue

            df[time_col] = pd.to_numeric(df[time_col], errors="coerce")
            df[cv_col] = pd.to_numeric(df[cv_col], errors="coerce")

            t_ms = df[time_col] * 1000.0
            mask = (t_ms >= INTERVAL_MS[0]) & (t_ms <= INTERVAL_MS[1])
            values = df.loc[mask, cv_col].dropna().to_numpy(dtype=float)
            values = values[np.isfinite(values)]

            if values.size > 0:
                runs.append(values)
                print(f"  {csv_path.name}: {len(values)} values")

        cv_by_height[key] = runs
        print(f"{key}: {len(runs)} run(s) found")
    
    
    #further processing
    print("\nAvailable heights:", list(cv_by_height.keys()))
    
    
    cv_average_by_height = {}
    std_by_height = {}
    peak_time_by_height = {}
    time_std ={}
    for key in list(cv_by_height.keys()):
        cv_max = []
        peak_time=[]
        for run in np.arange(10):
         if np.max(cv_by_height[key][run]) < 1000:
            cv_max.append(np.max(cv_by_height[key][run]))
         if t_ms[np.argmax(cv_by_height[key][run])] < 80:
            peak_time.append(t_ms[np.argmax(cv_by_height[key][run])])
            
        cv_average_by_height.update({key: np.mean(cv_max)})
        std_by_height.update({key: np.std(cv_max)})
        peak_time_by_height.update({key: np.mean(peak_time)})
        time_std.update({key: np.std(peak_time)})
    #print(cv_average_by_height)  
    #print(std_by_height)     
    print(peak_time_by_height) 
    print(time_std)


    return 0

if __name__ == "__main__":
    raise SystemExit(main())