from __future__ import annotations

from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from tcm_utils.file_dialogs import ask_directory
from tcm_utils.io_utils import make_minimal_progress_bar
from tcm_utils.plot_style import (
    add_label,
    append_unit_to_last_ticklabel,
    plot_binned_area,
    use_tcm_poster_style,
)

# ------------------------------
# Simple settings (edit these)
# ------------------------------
# Set to a parent folder containing experiment subfolders,
# or leave as None to select via folder dialog.
PARENT_DIR: str | None = None

# The interval to combine; used to match files named ...t_xxx_to_yyyms.csv
INTERVAL_MS = (0, 700)

# Height labels associated with stacked subplots.
# Bottom subplot should be -80 mm; top subplot should be 50 mm.
HEIGHTS_MM = list(range(0, 2, 1))

PLOT_COLOR = "C0"
PLOT_ALPHA = 0.18

# Optional manual axis limits. Set to None for automatic limits from data.
X_LIMITS: tuple[float, float] | None = None
Y_LIMITS: tuple[float, float] | None = (0, 50)
Y_LIMITS_LOG: tuple[float, float] | None = (0.001, 100)


def main() -> int:
    if INTERVAL_MS[1] <= INTERVAL_MS[0]:
        raise ValueError(f"INTERVAL_MS invalid: {INTERVAL_MS}")

    if PARENT_DIR is None:
        selected = ask_directory(
            key="combine_spraytec_parent_dir",
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

    interval_suffix = f"t_{INTERVAL_MS[0]}_to_{INTERVAL_MS[1]}ms.csv"

    subfolder_csvs: list[tuple[Path, list[Path]]] = []
    with make_minimal_progress_bar(
        total=len(experiment_info),
        label="Collecting averages",
        unit_label="folders",
    ) as pbar:
        for experiment_dir, _ in experiment_info:
            csv_paths = sorted(
                path
                for path in experiment_dir.rglob("*.csv")
                if path.is_file() and path.name.endswith(interval_suffix)
            )
            subfolder_csvs.append((experiment_dir, csv_paths))
            pbar.update(1)

    for experiment_dir, csv_paths in subfolder_csvs:
        if not csv_paths:
            print(
                f"No average files found in {experiment_dir.name} for interval {INTERVAL_MS[0]}-{INTERVAL_MS[1]} ms."
            )

    all_y_values: list[float] = []
    all_x_values: list[float] = []
    loaded_series: list[list[tuple[np.ndarray, np.ndarray]]] = []
    for _, csv_paths in subfolder_csvs:
        row_series: list[tuple[np.ndarray, np.ndarray]] = []
        for csv_path in csv_paths:
            df = pd.read_csv(csv_path, index_col=0)
            if df.empty:
                continue

            x = pd.to_numeric(pd.Series(df.index), errors="coerce").to_numpy()
            y = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy()

            valid_mask = np.isfinite(x) & np.isfinite(y) & (x > 0)
            if not np.any(valid_mask):
                continue

            x_valid = x[valid_mask]
            y_valid = y[valid_mask]
            row_series.append((x_valid, y_valid))

            all_x_values.extend(x_valid.tolist())
            all_y_values.extend(y_valid.tolist())

        loaded_series.append(row_series)

    if not all_x_values or not all_y_values:
        print("No plottable average data found.")
        return 1

    global_x_min = float(np.min(all_x_values))
    global_x_max = float(np.max(all_x_values))
    global_y_min = float(np.min(all_y_values))
    global_y_max = float(np.max(all_y_values))
    if global_y_min == global_y_max:
        global_y_max = global_y_min + 1.0

    if X_LIMITS is not None:
        global_x_min, global_x_max = X_LIMITS
    if Y_LIMITS is not None:
        global_y_min, global_y_max = Y_LIMITS

    heights_top_to_bottom = list(reversed(HEIGHTS_MM))[: len(experiment_info)]

    use_tcm_poster_style()
    fig, axes = plt.subplots(
        nrows=len(experiment_info),
        ncols=1,
        figsize=(10, max(2.2 * len(experiment_info), 4.0)),
        sharex=True,
    )

    if len(experiment_info) == 1:
        axes = [axes]

    for idx, (ax, (experiment_dir, _), row_series) in enumerate(
        zip(axes, subfolder_csvs, loaded_series, strict=True)
    ):
        for x_values, y_values in row_series:
            plot_binned_area(
                ax,
                x_values,
                y_values,
                x_mode="centers",
                color=PLOT_COLOR,
                alpha=PLOT_ALPHA,
                outline=False,
            )

        ax.set_xscale("log")
        ax.set_xlim(global_x_min, global_x_max)
        ax.set_ylim(global_y_min, global_y_max)
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

    axes[-1].set_xlabel("Particle size")
    append_unit_to_last_ticklabel(axes[-1], axis="x", unit="μm")

    fig.supylabel("Average number distribution (%)")
    fig.suptitle(
        f"SprayTec averages ({INTERVAL_MS[0]} to {INTERVAL_MS[1]} ms)",
        y=0.995,
    )
    fig.tight_layout()

    processed_dir = parent_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    output_pdf = processed_dir / (
        f"combined_averages_t_{INTERVAL_MS[0]}_to_{INTERVAL_MS[1]}ms.pdf"
    )
    fig.savefig(output_pdf, bbox_inches="tight")
    plt.close(fig)

    positive_y_values = [value for value in all_y_values if value > 0]
    if not positive_y_values:
        print("Skipped log-log variant because no positive y-values were found.")
        print(f"Saved combined figure: {output_pdf}")
        return 0

    global_y_min_log = float(np.min(positive_y_values))
    global_y_max_log = float(np.max(positive_y_values))
    if global_y_min_log == global_y_max_log:
        global_y_max_log = global_y_min_log * 10.0
    if Y_LIMITS_LOG is not None:
        global_y_min_log, global_y_max_log = Y_LIMITS_LOG

    fig_loglog, axes_loglog = plt.subplots(
        nrows=len(experiment_info),
        ncols=1,
        figsize=(10, max(2.2 * len(experiment_info), 4.0)),
        sharex=True,
    )

    if len(experiment_info) == 1:
        axes_loglog = [axes_loglog]

    for idx, (ax, (experiment_dir, _), row_series) in enumerate(
        zip(axes_loglog, subfolder_csvs, loaded_series, strict=True)
    ):
        for x_values, y_values in row_series:
            positive_mask = y_values > 0
            if not np.any(positive_mask):
                continue

            x_plot = x_values[positive_mask]
            y_plot = y_values[positive_mask]
            if x_plot.size < 2:
                continue

            plot_binned_area(
                ax,
                x_plot,
                y_plot,
                x_mode="centers",
                color=PLOT_COLOR,
                alpha=PLOT_ALPHA,
                outline=False,
            )

        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(global_x_min, global_x_max)
        ax.set_ylim(global_y_min_log, global_y_max_log)
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

    axes_loglog[-1].set_xlabel("Particle size")
    append_unit_to_last_ticklabel(axes_loglog[-1], axis="x", unit="um")

    fig_loglog.supylabel("Mean distribution")
    fig_loglog.suptitle(
        f"SprayTec averages log-log ({INTERVAL_MS[0]} to {INTERVAL_MS[1]} ms)",
        y=0.995,
    )
    fig_loglog.tight_layout()

    output_pdf_loglog = processed_dir / (
        f"combined_averages_loglog_t_{INTERVAL_MS[0]}_to_{INTERVAL_MS[1]}ms.pdf"
    )
    fig_loglog.savefig(output_pdf_loglog, bbox_inches="tight")
    plt.close(fig_loglog)

    print(f"Saved combined figure: {output_pdf}")
    print(f"Saved log-log figure: {output_pdf_loglog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
