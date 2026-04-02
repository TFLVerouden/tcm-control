from __future__ import annotations

"""SprayTec CSV loading and processing helpers."""

import re
from pathlib import Path
from typing import Any

import pandas as pd
from natsort import natsorted
from tcm_control.processing.common import get_processed_dir
from tcm_utils.io_utils import ask_open_file, save_metadata_json

DEFAULT_SPRAYTEC_CSV_GLOB = "spraytec*.csv"

_MISSING_MARKERS = {
    "",
    "---",
    "nan",
    "none",
    "na",
    "n/a",
}

_CATEGORY_SORT_ORDER = [
    "general",
    "Trans",
    "Dn",
    "D",
    "Cv",
    "Span",
    "%N < 10�",
    "Sc",
    "Sr",
    "Bl",
    "Bd",
    "Dc",
]

__all__ = [
    "resolve_spraytec_csv_file_path",
    "load_spraytec_csv",
    "load_spraytec_csvs",
    "build_metadata",
    "time_average_distribution",
    "export_spraytec_metadata_json",
    "export_spraytec_metadata_jsons",
    "build_combined_spraytec_metadata",
    "export_combined_spraytec_metadata_json",
]


def resolve_spraytec_csv_file_path(file_path: str | Path | None) -> Path:
    """Return a validated SprayTec measurement CSV path."""
    if file_path is None:
        selected_path = ask_open_file(
            key="spraytec_csv_file",
            title="Select SprayTec CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if selected_path is None:
            raise ValueError("No SprayTec CSV file selected.")
        resolved_path = Path(selected_path)
    else:
        resolved_path = Path(file_path)

    if not resolved_path.exists():
        raise FileNotFoundError(f"SprayTec CSV file not found: {resolved_path}")
    if not resolved_path.is_file():
        raise ValueError(f"Path is not a file: {resolved_path}")
    return resolved_path


def load_spraytec_csv(file_path: str | Path | None = None) -> dict[str, Any]:
    """Load one SprayTec CSV and split metadata from time-dependent columns."""
    resolved_path = resolve_spraytec_csv_file_path(file_path)

    dataframe = pd.read_csv(
        resolved_path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8",
        encoding_errors="replace",
    )
    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    dataframe = dataframe.apply(lambda series: series.astype(str).str.strip())

    if dataframe.empty:
        raise ValueError(f"SprayTec CSV contains no data rows: {resolved_path}")

    numeric_pattern = re.compile(r"^[+-]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][+-]?\d+)?$")

    def try_parse_float(value: str) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def is_absurd_negative_sentinel(value: str) -> bool:
        parsed = try_parse_float(value)
        return parsed is not None and parsed < -1e20

    def is_bin_edge_column(column_name: str) -> bool:
        parsed = try_parse_float(column_name.strip())
        return parsed is not None and parsed > 0

    def parse_scalar(value: str | None) -> Any:
        if value is None:
            return None
        if numeric_pattern.match(value):
            numeric_value = float(value)
            if numeric_value.is_integer() and "e" not in value.lower() and "." not in value:
                return int(numeric_value)
            return numeric_value
        return value

    absurd_values_converted_count = 0
    for column_name in dataframe.columns:
        absurd_values_converted_count += int(
            dataframe[column_name].astype(str).str.strip().apply(is_absurd_negative_sentinel).sum()
        )

    print(
        "SprayTec warning: converted "
        f"{absurd_values_converted_count} absurdly large negative value(s) to NaN "
        f"while loading {resolved_path.name}."
    )

    metadata_flat: dict[str, Any] = {}
    measurement_columns: list[str] = []
    bin_edges_um: list[float] = []

    for column_name in dataframe.columns:
        if is_bin_edge_column(column_name):
            edge = try_parse_float(column_name)
            if edge is not None:
                bin_edges_um.append(edge)
            measurement_columns.append(column_name)
            continue

        normalized_values: list[str | None] = []
        for value in dataframe[column_name].tolist():
            cleaned = str(value).strip()
            if cleaned.lower() in _MISSING_MARKERS or is_absurd_negative_sentinel(cleaned):
                normalized_values.append(None)
            else:
                normalized_values.append(cleaned)

        unique_non_missing = {value for value in normalized_values if value is not None}
        if len(unique_non_missing) <= 1:
            only_value = next(iter(unique_non_missing), None)
            metadata_flat[column_name] = parse_scalar(only_value)
        else:
            measurement_columns.append(column_name)

    measurement_df = dataframe[measurement_columns].copy()
    for column_name in measurement_df.columns:
        raw = measurement_df[column_name].astype(str).str.strip()
        missing_mask = raw.str.lower().isin(_MISSING_MARKERS) | raw.apply(
            is_absurd_negative_sentinel
        )
        cleaned = raw.mask(missing_mask, pd.NA)

        numeric = pd.to_numeric(cleaned, errors="coerce")
        non_missing_count = cleaned.notna().sum()
        numeric_non_missing_count = numeric.notna().sum()

        if non_missing_count > 0 and numeric_non_missing_count / non_missing_count >= 0.90:
            measurement_df[column_name] = numeric
        else:
            measurement_df[column_name] = cleaned

    metadata_by_category = build_metadata(metadata_flat)
    bin_centers_um = [
        (bin_edges_um[idx - 1] + bin_edges_um[idx]) / 2.0
        for idx in range(1, len(bin_edges_um))
    ]

    return {
        "file_path": resolved_path,
        "data_df": dataframe,
        "measurement_df": measurement_df,
        "measurement_columns": list(measurement_df.columns),
        "metadata_flat": metadata_flat,
        "metadata_by_category": metadata_by_category,
        "bin_edges_um": bin_edges_um,
        "bin_centers_um": bin_centers_um,
        "absurd_values_converted_count": absurd_values_converted_count,
    }


def load_spraytec_csvs(
    folder_path: str | Path,
    pattern: str = DEFAULT_SPRAYTEC_CSV_GLOB,
) -> list[dict[str, Any]]:
    """Load all SprayTec CSV files in a folder and return list payloads."""
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"SprayTec folder not found: {folder}")
    if not folder.is_dir():
        raise ValueError(f"Path is not a folder: {folder}")

    csv_paths = natsorted(path for path in folder.glob(pattern) if path.is_file())
    if not csv_paths:
        raise ValueError(f"No SprayTec CSV files found in {folder} with pattern '{pattern}'")

    return [load_spraytec_csv(path) for path in csv_paths]


def build_metadata(metadata_flat: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Group metadata columns by prefix-based category."""
    grouped: dict[str, dict[str, Any]] = {}

    for column_name, value in metadata_flat.items():
        stripped = column_name.strip()
        if not stripped:
            category = "general"
        else:
            category = "general"
            for delimiter in ("(", "["):
                delimiter_pos = stripped.find(delimiter)
                if delimiter_pos > 0:
                    prefix = stripped[:delimiter_pos].strip()
                    category = prefix if prefix else "general"
                    break

        grouped.setdefault(category, {})[column_name] = value

    sorted_categories = natsorted(
        grouped.keys(),
        key=lambda name: (
            _CATEGORY_SORT_ORDER.index(name)
            if name in _CATEGORY_SORT_ORDER
            else len(_CATEGORY_SORT_ORDER),
            name.lower(),
        ),
    )

    metadata_by_category: dict[str, dict[str, Any]] = {}
    for category in sorted_categories:
        metadata_by_category[category] = dict(
            natsorted(grouped[category].items(), key=lambda item: item[0].lower())
        )

    return metadata_by_category


def _build_time_interval_labels(
    start_time_s: float | None,
    end_time_s: float | None,
) -> tuple[str, str]:
    """Return (human label, filename-safe label) with ms precision."""
    if start_time_s is None and end_time_s is None:
        return "all time", "all_time"

    if start_time_s is not None and end_time_s is not None:
        return (
            f"{start_time_s:.3f}s to {end_time_s:.3f}s",
            f"t_{start_time_s:.3f}_to_{end_time_s:.3f}s",
        )

    if start_time_s is not None:
        return (
            f"from {start_time_s:.3f}s",
            f"t_from_{start_time_s:.3f}s",
        )

    return (
        f"until {end_time_s:.3f}s",
        f"t_until_{end_time_s:.3f}s",
    )


def time_average_distribution(
    spraytec_data: dict[str, Any],
    start_time_s: float | None = None,
    end_time_s: float | None = None,
    time_column: str = "Time [s]",
    export_csv: bool = True,
    csv_filename: str | None = None,
    plot: bool = False,
    ax: Any | None = None,
    export_pdf: bool = False,
    pdf_filename: str | None = None,
    **plot_kwargs: Any,
) -> pd.Series:
    """Compute a time-averaged distribution, with optional export and plotting.

    Plot kwargs are forwarded to matplotlib's ax.plot(...).
    """
    measurement_df = spraytec_data["measurement_df"]
    bin_edges_um = spraytec_data["bin_edges_um"]

    if len(bin_edges_um) < 2:
        raise ValueError("No valid bin edges found; cannot compute time average distribution.")

    bin_edge_labels = {str(edge) for edge in bin_edges_um}
    bin_columns = [
        column for column in measurement_df.columns if str(column).strip() in bin_edge_labels
    ]

    if not bin_columns:
        bin_columns = []
        for column in measurement_df.columns:
            try:
                parsed = float(str(column).strip())
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                bin_columns.append(column)

    if not bin_columns:
        raise ValueError("No bin distribution columns found in measurement_df.")

    working_df = measurement_df
    if time_column in working_df.columns and (start_time_s is not None or end_time_s is not None):
        time_values = pd.to_numeric(working_df[time_column], errors="coerce")
        mask = pd.Series(True, index=working_df.index)
        if start_time_s is not None:
            mask &= time_values >= float(start_time_s)
        if end_time_s is not None:
            mask &= time_values <= float(end_time_s)
        working_df = working_df[mask]

    if working_df.empty:
        raise ValueError("No rows left after applying time range filter.")

    dist_df = working_df[bin_columns].apply(pd.to_numeric, errors="coerce")
    averaged = pd.Series(dist_df.mean(axis=0, skipna=True))

    centers = [
        (bin_edges_um[idx - 1] + bin_edges_um[idx]) / 2.0
        for idx in range(1, len(bin_edges_um))
    ]

    if len(centers) == len(averaged.index):
        averaged.index = centers
        averaged.index.name = "bin_center_um"

    interval_title, interval_filename = _build_time_interval_labels(
        start_time_s=start_time_s,
        end_time_s=end_time_s,
    )

    source_path = Path(spraytec_data["file_path"])
    output_path = get_processed_dir(source_path.parent)

    if export_csv:
        resolved_csv_filename = (
            csv_filename
            if csv_filename is not None
            else f"{source_path.stem}_time_average_{interval_filename}.csv"
        )
        csv_path = output_path / resolved_csv_filename
        export_df = averaged.rename(f"mean_distribution ({interval_title})").to_frame()
        if export_df.index.name is None:
            export_df.index.name = "bin_center_um"
        export_df.to_csv(csv_path)

    if plot or export_pdf or ax is not None:
        import matplotlib.pyplot as plt

        if ax is None:
            _, ax = plt.subplots(figsize=(7, 4))

        x_values = pd.to_numeric(pd.Series(averaged.index), errors="coerce")
        y_values = pd.to_numeric(averaged, errors="coerce")

        if "linewidth" not in plot_kwargs:
            plot_kwargs["linewidth"] = 2
        ax.plot(x_values, y_values, **plot_kwargs)
        ax.set_xlabel("Particle size (um)")
        ax.set_ylabel("Mean distribution")
        ax.set_title(f"SprayTec time-averaged distribution ({interval_title})")
        ax.grid(True, alpha=0.3)

        if export_pdf:
            resolved_pdf_filename = (
                pdf_filename
                if pdf_filename is not None
                else f"{source_path.stem}_time_average_{interval_filename}.pdf"
            )
            pdf_path = output_path / resolved_pdf_filename
            ax.figure.tight_layout()
            ax.figure.savefig(pdf_path, bbox_inches="tight")

    return averaged


def export_spraytec_metadata_json(
    spraytec_data: dict[str, Any],
    filename: str | None = None,
) -> Path:
    """Export one loaded SprayTec metadata payload as JSON."""
    source_path = Path(spraytec_data["file_path"])
    output_path = get_processed_dir(source_path.parent)

    resolved_filename = (
        filename if filename is not None else f"{source_path.stem}_metadata.json"
    )
    json_path = output_path / resolved_filename

    payload = {
        "source_csv": spraytec_data["file_path"],
        "metadata_by_category": spraytec_data["metadata_by_category"],
        "time_dependent_columns": spraytec_data["measurement_columns"],
        "bin_edges_um": spraytec_data["bin_edges_um"],
        "bin_centers_um": spraytec_data["bin_centers_um"],
    }

    def to_jsonable(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): to_jsonable(val) for key, val in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [to_jsonable(val) for val in value]
        return value

    save_metadata_json(to_jsonable(payload), json_path)
    return json_path


def export_spraytec_metadata_jsons(
    spraytec_data_list: list[dict[str, Any]],
) -> list[Path]:
    """Export metadata JSON files for multiple loaded SprayTec CSV files."""
    return [export_spraytec_metadata_json(spraytec_data=data) for data in spraytec_data_list]


def build_combined_spraytec_metadata(
    spraytec_data_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one combined metadata dict across multiple SprayTec CSV files."""
    if not spraytec_data_list:
        raise ValueError("spraytec_data_list is empty")

    def merge_values(values: list[Any]) -> Any:
        if not values:
            return None
        first_value = values[0]
        if all(value == first_value for value in values[1:]):
            return first_value
        return values

    source_csvs = [str(data["file_path"]) for data in spraytec_data_list]
    file_names = [Path(data["file_path"]).name for data in spraytec_data_list]

    all_time_dependent_columns: set[str] = set()
    for data in spraytec_data_list:
        all_time_dependent_columns.update(data["measurement_columns"])

    all_bin_edges = [data["bin_edges_um"] for data in spraytec_data_list]
    all_bin_centers = [data["bin_centers_um"] for data in spraytec_data_list]
    absurd_counts = [data["absurd_values_converted_count"] for data in spraytec_data_list]

    all_categories: set[str] = set()
    for data in spraytec_data_list:
        all_categories.update(data["metadata_by_category"].keys())

    combined_metadata_by_category: dict[str, dict[str, Any]] = {}
    for category in natsorted(all_categories):
        all_keys: set[str] = set()
        for data in spraytec_data_list:
            all_keys.update(data["metadata_by_category"].get(category, {}).keys())

        combined_category: dict[str, Any] = {}
        for key in natsorted(all_keys):
            values = [
                data["metadata_by_category"].get(category, {}).get(key)
                for data in spraytec_data_list
            ]
            combined_category[key] = merge_values(values)

        combined_metadata_by_category[category] = combined_category

    return {
        "source_csvs": source_csvs,
        "source_file_names": file_names,
        "metadata_by_category": combined_metadata_by_category,
        "time_dependent_columns": natsorted(all_time_dependent_columns),
        "bin_edges_um": merge_values(all_bin_edges),
        "bin_centers_um": merge_values(all_bin_centers),
        "absurd_values_converted_count": {
            "per_file": dict(zip(file_names, absurd_counts, strict=True)),
            "total": sum(absurd_counts),
        },
    }


def export_combined_spraytec_metadata_json(
    spraytec_data_list: list[dict[str, Any]],
    filename: str = "spraytec_metadata.json",
) -> Path:
    """Export one combined metadata JSON for multiple loaded SprayTec CSV files."""
    source_folders = {Path(data["file_path"]).parent.resolve() for data in spraytec_data_list}
    if not source_folders:
        raise ValueError("spraytec_data_list is empty")
    if len(source_folders) > 1:
        raise ValueError(
            "Combined metadata export requires all source CSV files in the same folder."
        )

    output_path = get_processed_dir(next(iter(source_folders)))
    json_path = output_path / filename

    payload = build_combined_spraytec_metadata(spraytec_data_list)

    def to_jsonable(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): to_jsonable(val) for key, val in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [to_jsonable(val) for val in value]
        return value

    save_metadata_json(to_jsonable(payload), json_path)
    return json_path
