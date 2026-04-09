from __future__ import annotations

from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from tcm_utils.file_dialogs import ask_directory
from tcm_utils.io_utils import make_minimal_progress_bar
from tcm_utils.plot_style import add_label, append_unit_to_last_ticklabel, use_tcm_poster_style
from tcm_utils.cvd_check import get_color, set_cvd_friendly_colors

# ------------------------------
# Simple settings (edit these)
# ------------------------------
# Set to a parent folder containing experiment subfolders,
# or leave as None to select via folder dialog.
PARENT_DIR: str | None = None

# Expected input files produced by export_time_dependent_columns_csv(...)
CSV_SUFFIX = "_time_dependent_columns.csv"

# Height labels associated with stacked subplots.
# Bottom subplot should be -80 mm; top subplot should be 50 mm.
HEIGHTS_MM = list(range(-80, 51, 10))

LINE_ALPHA = 0.35
MARKER_SIZE = 10

# Optional manual axis limits. Set to None for automatic limits from data.
X_LIMITS: tuple[float, float] | None = None
Y_LIMITS: tuple[float, float] | None = None

# Interval in milliseconds (like combine_averages).
INTERVAL_MS = (30, 130)

# Optional per-column y-limits using source column names.
# Example:
# Y_LIMITS_BY_COLUMN = {
#     "transmission_percent": (80, 100),
#     "residual": (0, 10),
#     "cv_ppm": (0, 200),
# }
Y_LIMITS_BY_COLUMN: dict[str, tuple[float, float] | None] = {
    "transmission_percent": (98, 100.5),
    "residual": (0, 100),
    "cv_ppm": (0, 40),
}

DISPLAY_LABELS_BY_COLUMN: dict[str, str] = {
    "transmission_percent": "Transmission (%)",
    "residual": "Residual (%)",
    "cv_ppm": "Volume concentration (ppm)",
}


def _first_existing(candidates: list[str], available_columns: list[str]) -> str | None:
    normalized_to_original = {
        str(column).strip().lower(): str(column) for column in available_columns
    }
    for candidate in candidates:
        resolved = normalized_to_original.get(candidate.strip().lower())
        if resolved is not None:
            return resolved
    return None


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")
    return cleaned.lower() or "column"


def main() -> int:
    if INTERVAL_MS[1] <= INTERVAL_MS[0]:
        raise ValueError(f"INTERVAL_MS invalid: {INTERVAL_MS}")

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

    height_pattern = re.compile(r"(-?\d+)\s*mm", re.IGNORECASE)
    experiment_info: list[tuple[Path, int | None]] = []
    for experiment_dir in experiment_dirs:
        match = height_pattern.search(experiment_dir.name)
        detected_height_mm = int(match.group(1)) if match else None
        experiment_info.append((experiment_dir, detected_height_mm))

    all_heights_detected = all(
        height is not None for _, height in experiment_info)
    if all_heights_detected:
        experiment_info = sorted(
            experiment_info,
            key=lambda item: item[1] if item[1] is not None else -10_000,
            reverse=True,
        )
    elif len(experiment_dirs) > len(HEIGHTS_MM):
        raise ValueError(
            f"Found {len(experiment_dirs)} subfolders but only {len(HEIGHTS_MM)} configured heights. "
            "Either add more HEIGHTS_MM values or include '<height>mm' in each folder name."
        )

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

    for experiment_dir, csv_paths in subfolder_csvs:
        if not csv_paths:
            print(
                f"No timed CSV files found in {experiment_dir.name} matching *{CSV_SUFFIX}.")

    loaded_by_experiment: list[list[pd.DataFrame]] = []
    all_value_columns: set[str] = set()
    for _, csv_paths in subfolder_csvs:
        row_frames: list[pd.DataFrame] = []
        for csv_path in csv_paths:
            try:
                df = pd.read_csv(csv_path)
            except Exception as exc:
                print(f"Skipping unreadable file {csv_path.name}: {exc}")
                continue

            if df.empty:
                continue

            resolved_time_col = _first_existing(
                ["time_s", "time", "time [s]", "time(s)"],
                [str(col) for col in df.columns],
            )
            if resolved_time_col is None:
                print(f"Skipping {csv_path.name}: no time column found.")
                continue

            df = df.copy()
            df[resolved_time_col] = pd.to_numeric(
                df[resolved_time_col], errors="coerce")

            candidate_value_cols = [
                str(col)
                for col in df.columns
                if str(col) != resolved_time_col
            ]
            for column_name in candidate_value_cols:
                df[column_name] = pd.to_numeric(
                    df[column_name], errors="coerce")

            finite_time_mask = np.isfinite(
                df[resolved_time_col].to_numpy(dtype=float))
            if not np.any(finite_time_mask):
                continue

            df = df.loc[finite_time_mask].reset_index(drop=True)
            row_frames.append(df)

            for column_name in candidate_value_cols:
                if np.isfinite(df[column_name].to_numpy(dtype=float)).any():
                    all_value_columns.add(column_name)

        loaded_by_experiment.append(row_frames)

    if not all_value_columns:
        print("No plottable timed data found.")
        return 1

    use_tcm_poster_style()
    set_cvd_friendly_colors(style="adjusted")

    heights_top_to_bottom = list(reversed(HEIGHTS_MM))[: len(experiment_info)]

    all_columns_sorted = sorted(
        all_value_columns, key=lambda value: value.lower())

    processed_dir = parent_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []

    for column_idx, value_column in enumerate(all_columns_sorted):
        global_x_values: list[float] = []
        global_y_values: list[float] = []
        for row_frames in loaded_by_experiment:
            for frame in row_frames:
                time_col = _first_existing(
                    ["time_s", "time", "time [s]", "time(s)"],
                    [str(col) for col in frame.columns],
                )
                if time_col is None or value_column not in frame.columns:
                    continue

                x = frame[time_col].to_numpy(dtype=float)
                y = frame[value_column].to_numpy(dtype=float)

                t_start_ms, t_end_ms = INTERVAL_MS
                t_ms = x * 1000.0
                time_window_mask = (t_ms >= float(t_start_ms)) & (
                    t_ms <= float(t_end_ms))
                x = x[time_window_mask]
                y = y[time_window_mask]

                valid = np.isfinite(x) & np.isfinite(y)
                if not np.any(valid):
                    continue

                global_x_values.extend(x[valid].tolist())
                global_y_values.extend(y[valid].tolist())

        if not global_x_values or not global_y_values:
            print(f"Skipping '{value_column}': no finite values found.")
            continue

        x_min = float(np.min(global_x_values))
        x_max = float(np.max(global_x_values))
        y_min = float(np.min(global_y_values))
        y_max = float(np.max(global_y_values))
        if y_min == y_max:
            y_max = y_min + 1.0

        if X_LIMITS is not None:
            x_min, x_max = X_LIMITS
        else:
            x_min, x_max = INTERVAL_MS[0] / 1000.0, INTERVAL_MS[1] / 1000.0
        if Y_LIMITS is not None:
            y_min, y_max = Y_LIMITS
        column_y_limits = Y_LIMITS_BY_COLUMN.get(value_column)
        if column_y_limits is not None:
            y_min, y_max = column_y_limits

        column_color = get_color(1 + column_idx)
        display_label = DISPLAY_LABELS_BY_COLUMN.get(
            value_column, value_column)

        fig, axes = plt.subplots(
            nrows=len(experiment_info),
            ncols=1,
            figsize=(10, max(2.2 * len(experiment_info), 4.0)),
            sharex=True,
        )

        if len(experiment_info) == 1:
            axes = [axes]

        for idx, (ax, (_, _), row_frames) in enumerate(
            zip(axes, subfolder_csvs, loaded_by_experiment, strict=True)
        ):
            for frame in row_frames:
                time_col = _first_existing(
                    ["time_s", "time", "time [s]", "time(s)"],
                    [str(col) for col in frame.columns],
                )
                if time_col is None or value_column not in frame.columns:
                    continue

                x = frame[time_col].to_numpy(dtype=float)
                y = frame[value_column].to_numpy(dtype=float)

                t_start_ms, t_end_ms = INTERVAL_MS
                t_ms = x * 1000.0
                time_window_mask = (t_ms >= float(t_start_ms)) & (
                    t_ms <= float(t_end_ms))
                x = x[time_window_mask]
                y = y[time_window_mask]

                valid = np.isfinite(x) & np.isfinite(y)
                if not np.any(valid):
                    continue

                ax.scatter(
                    x[valid],
                    y[valid],
                    color=column_color,
                    alpha=LINE_ALPHA,
                    s=MARKER_SIZE,
                    linewidths=0,
                )

            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)
            ax.grid(True, alpha=0.3)

            detected_height_mm = experiment_info[idx][1]
            height_label_mm = (
                int(detected_height_mm)
                if detected_height_mm is not None
                else int(heights_top_to_bottom[idx])
            )

            add_label(
                ax,
                f"{height_label_mm} mm",
                xy=(0.02, 0.95),
                coord_system="axes",
                ha="left",
                va="top",
                italic=False,
            )

            if idx < len(experiment_info) - 1:
                ax.tick_params(axis="x", labelbottom=False)

        axes[-1].set_xlabel("Time")
        append_unit_to_last_ticklabel(axes[-1], axis="x", unit="s")

        fig.supylabel(display_label)
        fig.suptitle(
            f"Timed SprayTec traces: {display_label} ({INTERVAL_MS[0]} to {INTERVAL_MS[1]} ms)",
            y=0.995,
        )
        fig.tight_layout()

        output_pdf = processed_dir / (
            f"combined_timed_{_slugify(value_column)}_t_{INTERVAL_MS[0]}_to_{INTERVAL_MS[1]}ms.pdf"
        )
        fig.savefig(output_pdf, bbox_inches="tight")
        plt.close(fig)

        print(f"Saved combined timed figure: {output_pdf}")
        saved_paths.append(output_pdf)

    if not saved_paths:
        print("No figures were saved.")
        return 1

    print(f"Saved {len(saved_paths)} timed figure(s) to: {processed_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
