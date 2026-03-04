from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import sys

import matplotlib.pyplot as plt
import pandas as pd
from tcm_utils.plot_style import plot_binned_area, set_log_axes, use_tcm_poster_style, append_unit_to_last_ticklabel
from tcm_utils.cvd_check import set_cvd_friendly_colors

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_PYTHON = SCRIPT_DIR.parents[1]
if str(SOURCE_PYTHON) not in sys.path:
    sys.path.insert(0, str(SOURCE_PYTHON))


SPRAYTEC_OUTPUT_PATH = SOURCE_PYTHON / \
    "tcm_control" / "devices" / "spraytec_output.py"
_module_spec = importlib.util.spec_from_file_location(
    "tcm_control_devices_spraytec_output",
    SPRAYTEC_OUTPUT_PATH,
)
if _module_spec is None or _module_spec.loader is None:
    raise ImportError(f"Could not load module from {SPRAYTEC_OUTPUT_PATH}")

_spraytec_output = importlib.util.module_from_spec(_module_spec)
sys.modules[_module_spec.name] = _spraytec_output
_module_spec.loader.exec_module(_spraytec_output)
load_spraytec_csv = _spraytec_output.load_spraytec_csv
export_combined_spraytec_metadata_json = _spraytec_output.export_combined_spraytec_metadata_json


def _print_metadata(file_path: Path, metadata_by_category: dict[str, dict[str, object]]) -> None:
    print(f"\n=== Metadata: {file_path.name} ===")
    for category, category_values in metadata_by_category.items():
        print(f"[{category}]")
        for key, value in category_values.items():
            print(f"  {key}: {value}")


def _print_time_dependent_columns(columns: list[str]) -> None:
    print(f"[time_dependent_columns] ({len(columns)})")
    for column_name in columns:
        print(f"  {column_name}")


def _print_metadata_differences(
    metadata_per_file: dict[str, dict[str, object]],
) -> None:
    file_names = list(metadata_per_file.keys())
    if len(file_names) < 2:
        return

    all_keys: set[str] = set()
    for metadata in metadata_per_file.values():
        all_keys.update(metadata.keys())

    differing_keys: list[str] = []
    for key in sorted(all_keys):
        values = [metadata_per_file[file_name].get(
            key) for file_name in file_names]
        if any(value != values[0] for value in values[1:]):
            differing_keys.append(key)

    print("\n=== Metadata differences across files ===")
    if not differing_keys:
        print("No metadata differences found.")
        return

    for key in differing_keys:
        print(f"{key}:")
        for file_name in file_names:
            print(f"  {file_name}: {metadata_per_file[file_name].get(key)}")


def _column_float(value: object) -> float:
    return float(str(value).strip())


def _is_number_distribution_column(column_name: str) -> bool:
    stripped = str(column_name).strip()
    if not stripped:
        return False
    try:
        return float(stripped) > 0
    except ValueError:
        return False


def _is_excluded_time_series_column(column_name: str) -> bool:
    stripped = str(column_name).strip()
    return (
        stripped.startswith("Sc[")
        or stripped.startswith("Sr[")
        or _is_number_distribution_column(stripped)
        or stripped == ""
    )


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    sanitized = sanitized.strip("._")
    return sanitized or "unnamed"


def _resolve_time_axis_relative_to_trigger(measurement_df: pd.DataFrame) -> tuple[pd.Series, str]:
    if "Date-Time" in measurement_df.columns:
        time_series = pd.to_datetime(
            measurement_df["Date-Time"],
            errors="coerce",
            format="%d %b %Y %H:%M:%S.%f",
        )
        if time_series.notna().any():
            trigger_timestamp = None
            if "Trigger" in measurement_df.columns:
                trigger_values = pd.to_numeric(
                    measurement_df["Trigger"], errors="coerce")
                trigger_rows = (trigger_values > 0).fillna(False)
                if trigger_rows.any():
                    trigger_idx = trigger_rows[trigger_rows].index[0]
                    trigger_timestamp = time_series.loc[trigger_idx]

            if pd.isna(trigger_timestamp):
                trigger_timestamp = time_series.dropna().iloc[0]

            relative_seconds = (
                time_series - trigger_timestamp).dt.total_seconds()
            return relative_seconds, "Time relative to trigger (s)"

    if "Time (relative)" in measurement_df.columns:
        relative_values = pd.to_numeric(
            measurement_df["Time (relative)"], errors="coerce")
        if relative_values.notna().any():
            trigger_reference = None
            if "Trigger" in measurement_df.columns:
                trigger_values = pd.to_numeric(
                    measurement_df["Trigger"], errors="coerce")
                trigger_rows = (trigger_values > 0).fillna(False)
                if trigger_rows.any():
                    trigger_idx = trigger_rows[trigger_rows].index[0]
                    trigger_reference = relative_values.loc[trigger_idx]

            if pd.isna(trigger_reference):
                trigger_reference = relative_values.dropna().iloc[0]

            return relative_values - trigger_reference, "Time relative to trigger (s)"

    return pd.Series(range(len(measurement_df))), "Sample index"


def _plot_time_dependent_columns(result, plots_root: Path) -> None:
    measurement_df = result.measurement_df.copy()
    time_axis, x_label = _resolve_time_axis_relative_to_trigger(measurement_df)
    csv_name = result.file_path.stem
    csv_plots_dir = plots_root / csv_name
    csv_plots_dir.mkdir(parents=True, exist_ok=True)

    columns_to_plot = [
        column_name
        for column_name in result.measurement_columns
        if column_name != "Date-Time" and not _is_excluded_time_series_column(column_name)
    ]

    print(
        f"\n{result.file_path.name}: saving {len(columns_to_plot)} per-quantity time-dependent plots "
        "(excluded Sc*, Sr*, and numeric distribution-bin columns)."
    )

    for column_name in columns_to_plot:
        numeric_values = pd.to_numeric(
            measurement_df[column_name], errors="coerce")
        if not numeric_values.notna().any():
            continue

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(time_axis, numeric_values, linewidth=1.2, alpha=0.9)
        ax.set_title(f"{result.file_path.name} — {column_name}")
        ax.set_xlabel(x_label)
        ax.set_ylabel(column_name)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        output_path = csv_plots_dir / f"{_sanitize_filename(column_name)}.pdf"
        fig.savefig(output_path)
        plt.close(fig)


def _plot_average_number_distributions(loaded_results: list, plots_root: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    color_cycle = plt.rcParams["axes.prop_cycle"].by_key().get(
        "color", ["C0", "C1", "C2", "C3"]
    )

    for index, result in enumerate(loaded_results):
        all_columns = list(result.data_df.columns)
        if len(all_columns) < 377:
            raise ValueError(
                f"Expected at least 377 columns in {result.file_path}, got {len(all_columns)}"
            )

        left_edge_header = all_columns[316]
        bin_headers = all_columns[317:377]

        x_edges_um = [_column_float(left_edge_header)] + [
            _column_float(header) for header in bin_headers
        ]
        y_average = (
            result.data_df[bin_headers]
            .apply(pd.to_numeric, errors="coerce")
            .mean(axis=0, skipna=True)
            .to_numpy()
        )

        print(
            f"\n{result.file_path.name}: left-edge header (col 317) = {left_edge_header}; "
            f"using {len(bin_headers)} bin columns (318..377)"
        )

        color = color_cycle[index % len(color_cycle)]
        plot_binned_area(
            ax,
            x_edges_um,
            y_average,
            x_mode="edges",
            color=color,
            alpha=0.25,
            outline=True,
            outline_color=color,
            outline_linewidth=2.5,
        )
        ax.plot([], [], color=color, label=result.file_path.name)

    set_log_axes(ax, x=True)
    ax.set_ylabel("Number (%)")
    append_unit_to_last_ticklabel(ax, axis="x", unit="µm")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()

    output_path = plots_root / "combined_average_number_distribution.pdf"
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Saved combined distribution plot: {output_path}")


def main() -> int:
    example_dir = SOURCE_PYTHON / "tcm_control" / "example_spraytec_data"
    file_paths = [
        example_dir / "spraytec1_260304_115013_741600.csv",
        example_dir / "spraytec2_260304_115045_245800.csv",
    ]

    loaded_results = [load_spraytec_csv(path) for path in file_paths]
    metadata_json_output_dir = example_dir
    exported_json_path = export_combined_spraytec_metadata_json(
        spraytec_data_list=loaded_results,
        output_dir=metadata_json_output_dir,
    )

    print("\nExported combined metadata JSON file:")
    print(f"  {exported_json_path}")

    metadata_per_file = {
        result.file_path.name: result.metadata_flat
        for result in loaded_results
    }
    _print_metadata_differences(metadata_per_file)

    plots_root = example_dir / "plots"
    plots_root.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving plots under: {plots_root}")

    set_cvd_friendly_colors()
    use_tcm_poster_style()

    for result in loaded_results:
        _print_metadata(result.file_path, result.metadata_by_category)
        _print_time_dependent_columns(result.measurement_columns)
        _plot_time_dependent_columns(result, plots_root=plots_root)

    _plot_average_number_distributions(loaded_results, plots_root=plots_root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
