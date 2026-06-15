from __future__ import annotations

from pathlib import Path
import re
import traceback
from typing import Any
import numpy as np
import pandas as pd
import traceback

from tcm_utils.file_dialogs import ask_directory
from tcm_utils.io_utils import make_minimal_progress_bar
from tcm_control.processing.common import get_processed_dir
from tcm_control.processing.spraytec_processing import load_spraytec_csvs
from tcm_control.processing.spraytec_plotting import time_average_distribution

#a combination of cv_reader and average_spraytec_multiple, but now the cv values are masked to find the 
#times over which the number densities are averaged. 

# Simple settings (edit these)
# ------------------------------
# Set to a parent folder containing experiment subfolders,
# or leave as None to select via folder dialog.
PARENT_DIR: str | None = None

CSV_PATTERN = "spraytec*.csv"

# Suffix used to find cv_ppm CSVs inside each <experiment>/processed/ folder.
CV_CSV_SUFFIX = "_time_dependent_columns.csv"

INTERVAL_MS = (0,700)
OUTLIER_THRESHOLD = 3.0  # runs more than this many std above the median mean are considered outliers and will be removed from the final average.

CV_TARGET_COLUMN = "cv_ppm"
TIME_COLUMN_CANDIDATES = ["time_s", "time", "time [s]", "time(s)"]
# SprayTec time column name (as used inside measurement_df).
SPRAYTEC_TIME_COLUMN = "Date-Time" 
# SprayTec trigger column name.
SPRAYTEC_TRIGGER_COLUMN = "Trigger"


MASK_MODE = "cv"  # "cv" or "time"

#threshold for masking cv values. Only number density values corresponding to cv values above this threshold will be averaged.
CV_THRESHOLD = 5

#threshold for masking time values. Only number density values corresponding to time values within this threshold (in ms) will be averaged.
TIME_THRESHOLD_MS = (0, 80)  # e.g. (0, 700) to keep only the first 700 ms after trigger.
# ------------------------------

def _first_existing(candidates: list[str], available_columns: list[str]) -> str | None:
    normalized_to_original = {
        str(col).strip().lower(): str(col) for col in available_columns
    }
    for candidate in candidates:
        resolved = normalized_to_original.get(candidate.strip().lower())
        if resolved is not None:
            return resolved
    return None

def _extract_run_key(path: Path) -> str:
    """
    Extract a shared stem key from a filename so that SprayTec and cv CSVs
    can be matched. 
    """
    stem = path.stem
    # Remove known suffixes to get a bare run key
    stem = re.sub(r"_time_dependent_columns$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_spraytec.*$", "", stem, flags=re.IGNORECASE)
    return stem
 
def _parse_spraytec_datetime(series: pd.Series) -> pd.Series:
    """
    Parse the SprayTec absolute datetime column, e.g. "13 May 2026 14:51:55.4441",
    into pandas Timestamps.
    """
    return pd.to_datetime(series, format="%d %b %Y %H:%M:%S.%f", errors="coerce")


def _trigger_relative_ms(df: pd.DataFrame) -> np.ndarray:
    """
    Convert the SprayTec Date-Time column to milliseconds relative to the
    trigger (t=0 = first row where Trigger == 1).
    """
    datetimes = _parse_spraytec_datetime(df[SPRAYTEC_TIME_COLUMN])
    trigger_vals = pd.to_numeric(df["Trigger"], errors="coerce").fillna(0)

    trigger_rows = datetimes[trigger_vals == 1].dropna()
    if trigger_rows.empty:
        raise ValueError("No trigger (Trigger == 1) found in measurement_df.")

    t0 = trigger_rows.iloc[0]
    relative_ms = (datetimes - t0).dt.total_seconds() * 1000.0
    return relative_ms.to_numpy(float)

 
def _mean_cv_for_run(cv_csv: Path) -> float | None:
    """
    Return the mean cv_ppm value across the entire run CSV, or None if the
    file cannot be parsed / the column is missing.
    """
    try:
        df = pd.read_csv(cv_csv)
    except Exception as exc:
        print(f"    [cv] Cannot read {cv_csv.name}: {exc}")
        return None
 
    if df.empty:
        return None
 
    cv_col = _first_existing([CV_TARGET_COLUMN], list(df.columns))
    if cv_col is None:
        print(f"    [cv] '{CV_TARGET_COLUMN}' not found in {cv_csv.name}")
        return None
 
    values = pd.to_numeric(df[cv_col], errors="coerce").dropna().to_numpy(float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
 
    return float(np.mean(values))
def load_cv_data(cv_csv: Path) -> tuple[np.ndarray, np.ndarray] | None:
    try:
        df = pd.read_csv(cv_csv)
    except Exception as exc:
        print(f"    [cv] Cannot read {cv_csv.name}: {exc}")
        return None

    if df.empty:
        return None

    time_col = _first_existing(TIME_COLUMN_CANDIDATES, list(df.columns))
    cv_col = _first_existing([CV_TARGET_COLUMN], list(df.columns))

    if time_col is None or cv_col is None:
        print(f"    [cv] Required columns not found in {cv_csv.name}")
        return None

    t_ms = pd.to_numeric(df[time_col], errors="coerce") * 1000.0
    cv_values = pd.to_numeric(df[cv_col], errors="coerce")

    # Drop NaNs jointly so both arrays stay the same length
    combined = pd.DataFrame({"t_ms": t_ms, "cv": cv_values}).dropna()

    mask = (combined["t_ms"] >= INTERVAL_MS[0]) & (combined["t_ms"] <= INTERVAL_MS[1])
    t_ms_masked = combined.loc[mask, "t_ms"].to_numpy(float)
    cv_masked = combined.loc[mask, "cv"].to_numpy(float)

    valid = np.isfinite(t_ms_masked) & np.isfinite(cv_masked)
    if not valid.any():
        return None

    return t_ms_masked[valid], cv_masked[valid]

def mask_data(
    spraytec_data: dict[str, Any],
    cv_series: tuple[np.ndarray, np.ndarray],
) -> dict[str, Any]:
    cv_time_ms, cv_ppm = cv_series  # cv_time is already in ms from load_cv_data

    df: pd.DataFrame = spraytec_data["measurement_df"].copy()
    stec_time_ms = _trigger_relative_ms(df)

    # Nearest-neighbour lookup into cv time axis
    nn_indices = np.searchsorted(cv_time_ms, stec_time_ms, side="left")
    nn_indices = np.clip(nn_indices, 0, len(cv_time_ms) - 1)
    left_idx = np.clip(nn_indices - 1, 0, len(cv_time_ms) - 1)
    right_idx = nn_indices
    left_dist = np.abs(stec_time_ms - cv_time_ms[left_idx])
    right_dist = np.abs(stec_time_ms - cv_time_ms[right_idx])
    best_idx = np.where(left_dist <= right_dist, left_idx, right_idx)

    cv_at_stec = cv_ppm[best_idx]

    # Keep SprayTec frames where cv_ppm is below the threshold
    frame_mask = cv_at_stec < CV_THRESHOLD  # shape: (len(df),) — one per SprayTec row

    n_total = len(df)
    n_kept = int(frame_mask.sum())
    n_dropped = n_total - n_kept
    print(
        f"    cv mask: {n_kept}/{n_total} frames kept "
        f"({n_dropped} dropped, cv_ppm >= {CV_THRESHOLD})"
    )

    filtered_data = dict(spraytec_data)
    filtered_data["measurement_df"] = df.loc[frame_mask].reset_index(drop=True)
    return filtered_data
 
def mask_data_by_time(
    spraytec_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Return a copy of spraytec_data with measurement_df filtered to only rows
    whose trigger-relative timestamp falls within TIME_MASK_MS.
    """
    df: pd.DataFrame = spraytec_data["measurement_df"].copy()
    stec_time_ms = _trigger_relative_ms(df)

    frame_mask = (
        (stec_time_ms >= TIME_THRESHOLD_MS[0]) &
        (stec_time_ms <= TIME_THRESHOLD_MS[1])
    )

    n_total = len(df)
    n_kept = int(frame_mask.sum())
    n_dropped = n_total - n_kept
    print(
        f"    time mask: {n_kept}/{n_total} frames kept "
        f"({n_dropped} dropped, outside {TIME_THRESHOLD_MS[0]}–{TIME_THRESHOLD_MS[1]} ms)"
    )

    filtered_data = dict(spraytec_data)
    filtered_data["measurement_df"] = df.loc[frame_mask].reset_index(drop=True)
    return filtered_data

def process_experiment(experiment_dir: Path) -> dict[str, str | int]:
    candidate = experiment_dir / "spraytec"
    spraytec_dir = candidate if candidate.exists(
    ) and candidate.is_dir() else experiment_dir

    processed_dir = get_processed_dir(experiment_dir)

    if MASK_MODE == "cv":
        dir_name = (f"spraytec_averages_masked_{int(CV_THRESHOLD)}_{INTERVAL_MS[0]}-{INTERVAL_MS[1]}ms")
    else:
        dir_name = (f"spraytec_averages_masked_time_{INTERVAL_MS[0]}-{INTERVAL_MS[1]}ms")
    output_dir = get_processed_dir(experiment_dir) / dir_name
    output_dir.mkdir(parents=True, exist_ok=True)

    spraytec_data_list = load_spraytec_csvs(spraytec_dir, pattern=CSV_PATTERN)

    if not spraytec_data_list:
     return {"runs_with_cv": 0, "runs_without_cv": 0, "status": "no_data"}
    
# --- build a map: run_key -> cv CSV path ---
    cv_csvs: dict[str, Path] = {}
    for cv_path in sorted(processed_dir.rglob("*.csv")):
        if cv_path.name.endswith(CV_CSV_SUFFIX):
            key = _extract_run_key(cv_path)
            cv_csvs[key] = cv_path

    runs_with_cv=0
    runs_without_cv=0        

    for spraytec_data in spraytec_data_list:
        stec_path = Path(spraytec_data["file_path"])
        run_key = _extract_run_key(stec_path)
        print(f"\n  Run: {stec_path.name}")

        if MASK_MODE == "cv":
            cv_csv = cv_csvs.get(run_key)
            if cv_csv is None:
                print(f"    No matching cv CSV for key '{run_key}' — run skipped.")
                runs_without_cv += 1
                continue

            cv_series = load_cv_data(cv_csv)
            if cv_series is None:
                print(f"    Could not load cv data from {cv_csv.name} — run skipped.")
                runs_without_cv += 1
                continue

            runs_with_cv += 1
            filtered_data = mask_data(spraytec_data, cv_series)

        elif MASK_MODE == "time":
            filtered_data = mask_data_by_time(spraytec_data)

        else:
            raise ValueError(f"Unknown MASK_MODE: '{MASK_MODE}'. Use 'cv' or 'time'.")

        if filtered_data["measurement_df"].empty:
            print("    No frames survived the mask — run skipped.")
            continue

        mask_label = f"cv{int(CV_THRESHOLD)}" if MASK_MODE == "cv" else f"time{TIME_THRESHOLD_MS[0]}-{TIME_THRESHOLD_MS[1]}ms"
        stem = stec_path.stem

        time_average_distribution(
            spraytec_data=filtered_data,
            start_time_ms=INTERVAL_MS[0],
            end_time_ms=INTERVAL_MS[1],
            trigger_column="Trigger",
            export_csv=True,
            csv_filename=f"{stem}_time_average_{INTERVAL_MS[0]}-{INTERVAL_MS[1]}ms_{mask_label}.csv",
            export_pdf=True,
            pdf_filename=f"{stem}_time_average_{INTERVAL_MS[0]}-{INTERVAL_MS[1]}ms_{mask_label}.pdf",
            plot=True,
            output_dir=output_dir,
        )
    return {"runs_with_cv": runs_with_cv, "runs_without_cv": runs_without_cv, "status": "success"}
 


def main() -> int:
    if INTERVAL_MS[1] <= INTERVAL_MS[0]:
        raise ValueError(f"INTERVAL_MS invalid: {INTERVAL_MS}")
 
    if PARENT_DIR is None:
        selected = ask_directory(
            key="average_spraytec_cv_masked_parent_dir",
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
        p for p in parent_dir.iterdir()
        if p.is_dir() and not p.name.lower().startswith("processed")
    )
    if not experiment_dirs:
        print(f"No subfolders found in: {parent_dir}")
        return 1
 
    print(f"Found {len(experiment_dirs)} experiment folder(s) in: {parent_dir}")
    print(f"cv_ppm frame threshold : cv_ppm > {CV_THRESHOLD} ppm")
    print(f"Averaging interval     : {INTERVAL_MS[0]}–{INTERVAL_MS[1]} ms\n")
 
    all_results: list[dict[str, str | int] | tuple[int, Path, Path]] = []
    failed: list[tuple[Path, str]] = []

 
    for experiment_dir in experiment_dirs:
        print(f"\n{'='*60}")
        print(f"Experiment: {experiment_dir.name}")
        print(f"{'='*60}")
        try:
            result = process_experiment(experiment_dir)
            all_results.append(result)
        except Exception as exc:
            failed.append((experiment_dir, str(exc)))
            print(f"  ERROR: {exc}")
            traceback.print_exc()
 
 
    # Filter to only dict results
    dict_results = [r for r in all_results if isinstance(r, dict)]
    
    print(f"Runs with cv data      : {sum(int(r['runs_with_cv']) for r in dict_results)}")
    print(f"Runs skipped (no cv)   : {sum(int(r['runs_without_cv']) for r in dict_results)}")
    
    if failed:
        print("\nFailed experiments:")
        for folder, error in failed:
            print(f"  - {folder.name}: {error}")
        return 2
    
    return 0
 
 
if __name__ == "__main__":
    raise SystemExit(main())


