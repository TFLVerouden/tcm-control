from __future__ import annotations

import importlib.util
from pathlib import Path
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


def _find_required_column(measurement_df: pd.DataFrame, expected_names: list[str]) -> str:
    normalized_to_column = {
        column_name.strip().lower(): column_name for column_name in measurement_df.columns
    }
    for expected_name in expected_names:
        resolved = normalized_to_column.get(expected_name.strip().lower())
        if resolved is not None:
            return resolved
    raise KeyError(f"Required column not found: any of {expected_names}")


def _find_n_lt_10_value_column(measurement_df: pd.DataFrame) -> str:
    for column_name in measurement_df.columns:
        normalized = column_name.replace("�", "").strip()
        if normalized.startswith("%N < 10") and normalized.endswith("(Value)"):
            return column_name
    raise KeyError("Required column not found: %N < 10(Value)")


def _plot_time_dependent_columns(result, plots_root: Path) -> None:
    measurement_df = result.measurement_df.copy()
    time_axis = pd.to_numeric(
        measurement_df["Time (relative)"], errors="coerce")
    if not time_axis.notna().any():
        raise ValueError(
            f"Time (relative) contains no numeric values in {result.file_path}"
        )

    trans_value_col = _find_required_column(measurement_df, ["Trans(Value)"])
    cv_percent_col = _find_required_column(measurement_df, ["Cv", "Cv(%)"])
    cv_value_col = _find_required_column(measurement_df, ["Cv(Value)"])
    d32_value_col = _find_required_column(measurement_df, ["D[3][2](Value)"])
    d43_value_col = _find_required_column(measurement_df, ["D[4][3](Value)"])
    dn10_value_col = _find_required_column(measurement_df, ["Dn(10)(Value)"])
    dn50_value_col = _find_required_column(measurement_df, ["Dn(50)(Value)"])
    dn90_value_col = _find_required_column(measurement_df, ["Dn(90)(Value)"])
    n_lt_10_value_col = _find_n_lt_10_value_column(measurement_df)
    scatter_start_col = _find_required_column(
        measurement_df, ["Scatter start"])
    scatter_end_col = _find_required_column(measurement_df, ["Scatter end"])

    csv_name = result.file_path.stem
    csv_plots_dir = plots_root / csv_name
    csv_plots_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"\n{result.file_path.name}: saving 6 hardcoded time-dependent plots."
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(time_axis, pd.to_numeric(
        measurement_df[trans_value_col], errors="coerce"), linewidth=1.2)
    ax.set_title(f"{result.file_path.name} - Transmission")
    ax.set_xlabel("Time (relative) (s)")
    ax.set_ylabel("Transmission (%)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(csv_plots_dir / "transmission_value.pdf")
    plt.close(fig)

    fig, ax_left = plt.subplots(figsize=(10, 6))
    cv_percent = pd.to_numeric(measurement_df[cv_percent_col], errors="coerce")
    cv_value = pd.to_numeric(measurement_df[cv_value_col], errors="coerce")
    ax_left.plot(time_axis, cv_percent, linewidth=1.2,
                 color="C0", label=cv_percent_col)
    ax_left.set_title(f"{result.file_path.name} - Cv")
    ax_left.set_xlabel("Time (relative) (s)")
    ax_left.set_ylabel("Cv (%)", color="C0")
    ax_left.tick_params(axis="y", labelcolor="C0")
    ax_left.grid(True, alpha=0.3)

    ax_right = ax_left.twinx()
    ax_right.plot(time_axis, cv_value, linewidth=1.2,
                  color="C1", label=cv_value_col)
    ax_right.set_ylabel("Cv(Value) (ppm)", color="C1")
    ax_right.tick_params(axis="y", labelcolor="C1")

    lines = ax_left.get_lines() + ax_right.get_lines()
    labels = [str(line.get_label()) for line in lines]
    ax_left.legend(lines, labels, loc="best")
    fig.tight_layout()
    fig.savefig(csv_plots_dir / "cv_and_cv_value.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(time_axis, pd.to_numeric(
        measurement_df[d32_value_col], errors="coerce"), linewidth=1.2, label=d32_value_col)
    ax.plot(time_axis, pd.to_numeric(
        measurement_df[d43_value_col], errors="coerce"), linewidth=1.2, label=d43_value_col)
    ax.set_title(f"{result.file_path.name} - Mean Diameters")
    ax.set_xlabel("Time (relative) (s)")
    ax.set_ylabel("Diameter (um)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(csv_plots_dir / "d32_d43_value.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(time_axis, pd.to_numeric(
        measurement_df[dn10_value_col], errors="coerce"), linewidth=1.2, label=dn10_value_col)
    ax.plot(time_axis, pd.to_numeric(
        measurement_df[dn50_value_col], errors="coerce"), linewidth=1.2, label=dn50_value_col)
    ax.plot(time_axis, pd.to_numeric(
        measurement_df[dn90_value_col], errors="coerce"), linewidth=1.2, label=dn90_value_col)
    ax.set_title(f"{result.file_path.name} - Dn Percentiles")
    ax.set_xlabel("Time (relative) (s)")
    ax.set_ylabel("Diameter (um)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(csv_plots_dir / "dn10_dn50_dn90_value.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(time_axis, pd.to_numeric(
        measurement_df[n_lt_10_value_col], errors="coerce"), linewidth=1.2)
    ax.set_title(f"{result.file_path.name} - %N < 10")
    ax.set_xlabel("Time (relative) (s)")
    ax.set_ylabel("%N < 10 (%)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(csv_plots_dir / "n_lt_10_value.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(time_axis, pd.to_numeric(
        measurement_df[scatter_start_col], errors="coerce"), linewidth=1.2, label=scatter_start_col)
    ax.plot(time_axis, pd.to_numeric(
        measurement_df[scatter_end_col], errors="coerce"), linewidth=1.2, label=scatter_end_col)
    ax.set_title(f"{result.file_path.name} - Scatter Start/End")
    ax.set_xlabel("Time (relative) (s)")
    ax.set_ylabel("Scatter channel")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(csv_plots_dir / "scatter_start_end.pdf")
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
