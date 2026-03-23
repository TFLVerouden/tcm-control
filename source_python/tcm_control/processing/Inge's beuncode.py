from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import pandas as pd
from natsort import natsorted
from tcm_utils.plot_style import plot_binned_area, set_log_axes, use_tcm_poster_style, append_unit_to_last_ticklabel
from tcm_utils.cvd_check import set_cvd_friendly_colors
from tcm_utils.io_utils import ask_directory
import scipy.signal as scip
import numpy as np
from tcm_control.processing import PROCESSED_SUBDIR_NAME
from tcm_control.devices import SprayTec

# instellingen
cv_peaks = []
transmission_peaks = []


SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_PYTHON = SCRIPT_DIR.parents[1]
if str(SOURCE_PYTHON) not in sys.path:
    sys.path.insert(0, str(SOURCE_PYTHON))


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
    for key in natsorted(all_keys):
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


def _to_volume_distribution_percent(
    y_number_percent: np.ndarray,
    x_edges_um: list[float],
    *,
    context_label: str,
) -> np.ndarray:
    y_number = np.nan_to_num(np.asarray(y_number_percent, dtype=float), nan=0.0)
    x_edges = np.asarray(x_edges_um, dtype=float)

    if len(x_edges) != len(y_number) + 1:
        raise ValueError(
            "Expected len(x_edges_um) == len(y_number_percent) + 1, got "
            f"{len(x_edges)} and {len(y_number)}"
        )

    # Use bin-center diameter for V = N * D^3 conversion.
    bin_centers_um = 0.5 * (x_edges[:-1] + x_edges[1:])
    y_volume_raw = y_number * np.power(bin_centers_um, 3)
    raw_sum = float(np.nansum(y_volume_raw))
    if raw_sum <= 0:
        raise ValueError(
            f"Volume conversion produced non-positive total for {context_label}"
        )

    y_volume_percent = 100.0 * y_volume_raw / raw_sum
    renorm_sum = float(np.nansum(y_volume_percent))
    print(
        f"{context_label}: volume renormalization check = {renorm_sum:.6f}% "
        f"(target: 100.000000%)"
    )
    return y_volume_percent


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
    residual_col = _find_required_column(measurement_df, ["R(Value)"])
    scatter_end_col = _find_required_column(measurement_df, ["Scatter end"])

    csv_name = result.file_path.stem
    csv_plots_dir = plots_root / csv_name
    csv_plots_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"\n{result.file_path.name}: saving 7 hardcoded time-dependent plots."
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
        measurement_df[residual_col], errors="coerce"), linewidth=1.2, label=residual_col)

    ax.set_title(f"{result.file_path.name} - Residual")
    ax.set_xlabel("Time (relative) (s)")
    ax.set_ylabel("Residual")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(csv_plots_dir / "residual_value.pdf")
    plt.close(fig)

    # vind piektijden in cv en transmissie plots en vergelijk of die overeenkomen met elkaar en met andere datasets.

    np_tijd = time_axis.to_numpy()

    # height aanpassen per set afhankelijk van ruis
    index_peaks_cv, _ = scip.find_peaks(cv_value, height=1)
    # voeg piek toe zodat er altijd een cv piek is, anders crash
    index_peaks_cv = np.append(index_peaks_cv, 370)
    print(cv_percent[index_peaks_cv])
    best_cv_peak = index_peaks_cv[np.argmax(cv_value[index_peaks_cv])]

    transmissie = measurement_df[trans_value_col].to_numpy()
    index_peaks_transmissie, _ = scip.find_peaks(
        np.ones(len(transmissie)) * 100 - transmissie, height=0.15)
    # voeg cv piek toe zodat er altijd een transmissie piek is, anders crash
    index_peaks_transmissie = np.append(index_peaks_transmissie, best_cv_peak)
    best_peak_transmissie = index_peaks_transmissie[np.argmax(
        transmissie[index_peaks_transmissie])]
    print(
        f"Peaks in transmissie plot at time:{np_tijd[best_peak_transmissie]}")
    print(f"Peaks in cv plot at time:{np_tijd[best_cv_peak]}")
    # toevoegen aan globale lijst zodat we ze kunnen vergelijken tussen runs

    cv_peaks.append(np_tijd[best_cv_peak])
    transmission_peaks.append(np_tijd[best_peak_transmissie])


def _plot_average_number_distributions(loaded_results: list, plots_root: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    fig_vol, ax_vol = plt.subplots(figsize=(10, 6))
    color_cycle = plt.rcParams["axes.prop_cycle"].by_key().get(
        "color", ["C0", "C1", "C2", "C3"])

    for index, result in enumerate(loaded_results):
        all_columns = list(result.data_df.columns)
        if len(all_columns) < 382:
            raise ValueError(
                f"Expected at least 382 columns in {result.file_path}, got {len(all_columns)}"
            )

        left_edge_header = all_columns[321]
        bin_headers = all_columns[322:382]

        x_edges_um = [_column_float(left_edge_header)] + [
            _column_float(header) for header in bin_headers
        ]
        y_average = (
            result.data_df[bin_headers]
            .apply(pd.to_numeric, errors="coerce")
            .mean(axis=0, skipna=True)
            .to_numpy()
        )
        y_volume_average = _to_volume_distribution_percent(
            y_average,
            x_edges_um,
            context_label=f"{result.file_path.name} (full average)",
        )

        print(
            f"\n{result.file_path.name}: left-edge header (col 322) = {left_edge_header}; "
            f"using {len(bin_headers)} bin columns (322..382)"
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

        plot_binned_area(
            ax_vol,
            x_edges_um,
            y_volume_average,
            x_mode="edges",
            color=color,
            alpha=0.25,
            outline=True,
            outline_color=color,
            outline_linewidth=2.5,
        )
        ax_vol.plot([], [], color=color, label=result.file_path.name)

    set_log_axes(ax, x=True)
    ax.set_ylabel("Number (%)")
    append_unit_to_last_ticklabel(ax, axis="x", unit="µm")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()

    set_log_axes(ax_vol, x=True)
    ax_vol.set_ylabel("Volume (%)")
    append_unit_to_last_ticklabel(ax_vol, axis="x", unit="µm")
    ax_vol.grid(True, alpha=0.3)
    ax_vol.legend(loc="upper right")
    fig_vol.tight_layout()

    output_path = plots_root / "number_distributions_averaged_full.pdf"
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Saved combined distribution plot: {output_path}")

    output_path_vol = plots_root / "volume_distributions_averaged_full.pdf"
    fig_vol.savefig(output_path_vol)
    plt.close(fig_vol)
    print(f"Saved combined volume distribution plot: {output_path_vol}")


def _averaging(loaded_results, plots_root, averaging_time, t_droplet) -> None:

    fig, ax = plt.subplots(figsize=(10, 6))
    fig_vol, ax_vol = plt.subplots(figsize=(10, 6))
    color_cycle = plt.rcParams["axes.prop_cycle"].by_key().get(
        "color", ["C0", "C1", "C2", "C3"]
    )

    for index, result in enumerate(loaded_results):

        df = result.data_df.copy()
        df["Time (relative)"] = pd.to_numeric(
            df["Time (relative)"], errors="coerce")

        df = df[
            (df["Time (relative)"] >= t_droplet)
            & (df["Time (relative)"] <= averaging_time)]

        all_columns = list(result.data_df.columns)
        if len(all_columns) < 382:
            raise ValueError(
                f"Expected at least 382 columns in {result.file_path}, got {len(all_columns)}"
            )

        left_edge_header = all_columns[321]
        bin_headers = all_columns[322:382]

        x_edges_um = [_column_float(left_edge_header)] + [
            _column_float(header) for header in bin_headers
        ]

        y_average = (
            df[bin_headers]
            .apply(pd.to_numeric, errors="coerce")
            .mean(axis=0, skipna=True)
            .to_numpy())
        y_volume_average = _to_volume_distribution_percent(
            y_average,
            x_edges_um,
            context_label=f"{result.file_path.name} (interval average)",
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

        plot_binned_area(
            ax_vol,
            x_edges_um,
            y_volume_average,
            x_mode="edges",
            color=color,
            alpha=0.25,
            outline=True,
            outline_color=color,
            outline_linewidth=2.5,
        )
        ax_vol.plot([], [], color=color, label=result.file_path.name)

    set_log_axes(ax, x=True)
    ax.set_ylabel("Number (%)")
    append_unit_to_last_ticklabel(ax, axis="x", unit="µm")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()

    set_log_axes(ax_vol, x=True)
    ax_vol.set_ylabel("Volume (%)")
    append_unit_to_last_ticklabel(ax_vol, axis="x", unit="µm")
    ax_vol.grid(True, alpha=0.3)
    ax_vol.legend(loc="upper right")
    fig_vol.tight_layout()

    output_path = plots_root / "number_distributions_averaged_interval.pdf"
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Saved combined average number distribution plot: {output_path}")

    output_path_vol = plots_root / "volume_distributions_averaged_interval.pdf"
    fig_vol.savefig(output_path_vol)
    plt.close(fig_vol)
    print(f"Saved combined average volume distribution plot: {output_path_vol}")


def main() -> int:
    default_input_dir = SOURCE_PYTHON / "tcm_control" / "example_spraytec_data"
    selected_dir = ask_directory(
        key="spraytec_data_dir",
        title="Select directory with Spraytec CSV files",
        default_dir=default_input_dir,
    )
    if selected_dir is None:
        print("No directory selected.")
        return 1

    example_dir = Path(selected_dir).expanduser().resolve()
    processed_dir = example_dir.parent / PROCESSED_SUBDIR_NAME
    processed_dir.mkdir(parents=True, exist_ok=True)

    file_paths = natsorted(
        path for path in example_dir.glob("*.csv")
        if path.name.lower().startswith("spraytec")
    )
    if not file_paths:
        print(
            f"No spraytec CSV files found in: {example_dir} "
            "(expected file names starting with 'spraytec')."
        )
        return 1

    spraytec = SprayTec()
    loaded_results = [spraytec.load_csv(path) for path in file_paths]
    metadata_json_output_dir = processed_dir
    exported_json_path = spraytec.export_combined_metadata_json(
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

    plots_root = processed_dir
    plots_root.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving plots under: {plots_root}")

    set_cvd_friendly_colors()
    use_tcm_poster_style()

    for result in loaded_results:
        # _print_metadata(result.file_path, result.metadata_by_category)
        # _print_time_dependent_columns(result.measurement_columns)
        _plot_time_dependent_columns(result, plots_root=plots_root)

    print(f"\nCv peaks across runs: {cv_peaks}")
    print(f"Transmission peaks across runs: {transmission_peaks}")

    _plot_average_number_distributions(
        loaded_results, plots_root=plots_root)

    # alleen wanneer cv en transmissie piek overlappen gbruiken in averaging plot
    if abs(cv_peaks[-1] - transmission_peaks[-1]) < 1:
        _averaging(loaded_results, plots_root,
                   averaging_time=0.2, t_droplet=cv_peaks[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
