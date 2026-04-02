from __future__ import annotations

"""SprayTec CSV loading and metadata-processing helpers.

This module contains functions that are not part of the append-file extraction
pipeline itself (parsing/splitting/copying), but are used for post-processing
loaded SprayTec CSV files and metadata export.
"""

import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from natsort import natsorted
from tcm_utils.io_utils import ask_open_file

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


@dataclass
class SpraytecCsvData:
    """Typed result for one loaded SprayTec CSV file."""

    file_path: Path
    data_df: pd.DataFrame
    measurement_df: pd.DataFrame
    measurement_columns: list[str]
    metadata_flat: dict[str, Any]
    metadata_by_category: dict[str, dict[str, Any]]
    bin_edges_um: list[float]
    bin_centers_um: list[float]
    absurd_values_converted_count: int


def _try_parse_float(value: str) -> float | None:
    """Return float(value) when parseable, else None."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_absurd_negative_sentinel(value: str) -> bool:
    """Detect extremely negative numeric sentinels used as overflow placeholders."""
    parsed = _try_parse_float(value)
    return parsed is not None and parsed < -1e20


def _is_bin_edge_column(column_name: str) -> bool:
    """Identify bin-edge columns by numeric headers (e.g., 0.10000020, 0.1165...)."""
    parsed = _try_parse_float(column_name.strip())
    return parsed is not None and parsed > 0


def _normalize_missing_value(value: Any) -> str | None:
    """Normalize blanks/sentinels to None, otherwise return stripped string."""
    if value is None:
        return None

    cleaned = str(value).strip()
    if cleaned.lower() in _MISSING_MARKERS or _is_absurd_negative_sentinel(cleaned):
        return None
    return cleaned


def _parse_scalar(value: str | None) -> Any:
    """Convert scalar text values to Python primitives where safe."""
    if value is None:
        return None

    numeric_pattern = re.compile(
        r"^[+-]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][+-]?\d+)?$"
    )
    if numeric_pattern.match(value):
        numeric_value = float(value)
        if numeric_value.is_integer() and "e" not in value.lower() and "." not in value:
            return int(numeric_value)
        return numeric_value

    return value


def _extract_prefix_category(column_name: str) -> str:
    """Extract prefix category from column names using delimiter-based grouping."""
    stripped = column_name.strip()
    if not stripped:
        return "general"

    for delimiter in ("(", "["):
        delimiter_pos = stripped.find(delimiter)
        if delimiter_pos > 0:
            prefix = stripped[:delimiter_pos].strip()
            return prefix if prefix else "general"

    return "general"


def _group_metadata_by_prefix(metadata_flat: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Group metadata columns by prefix-derived category with deterministic ordering."""
    grouped: dict[str, dict[str, Any]] = {}
    for column_name, value in metadata_flat.items():
        category = _extract_prefix_category(column_name)
        grouped.setdefault(category, {})[column_name] = value

    ordered = OrderedDict()
    sorted_categories = natsorted(
        grouped.keys(),
        key=lambda name: (
            _CATEGORY_SORT_ORDER.index(name)
            if name in _CATEGORY_SORT_ORDER
            else len(_CATEGORY_SORT_ORDER),
            name.lower(),
        ),
    )

    for category in sorted_categories:
        ordered[category] = dict(
            natsorted(grouped[category].items(),
                      key=lambda item: item[0].lower())
        )
    return dict(ordered)


def _coerce_numeric_if_possible(series: pd.Series) -> pd.Series:
    """Return numeric series only when most non-missing values are numeric."""
    raw = series.astype(str).str.strip()
    missing_mask = raw.str.lower().isin(_MISSING_MARKERS) | raw.apply(
        _is_absurd_negative_sentinel
    )
    cleaned = raw.mask(missing_mask, pd.NA)

    numeric = pd.to_numeric(cleaned, errors="coerce")
    non_missing_count = cleaned.notna().sum()
    if non_missing_count == 0:
        return cleaned

    numeric_non_missing_count = numeric.notna().sum()
    if numeric_non_missing_count / non_missing_count >= 0.90:
        return numeric
    return cleaned


def _read_spraytec_csv_dataframe(file_path: Path) -> pd.DataFrame:
    """Read SprayTec CSV robustly while preserving column ordering."""
    dataframe = pd.read_csv(
        file_path,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8",
        encoding_errors="replace",
    )

    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    dataframe = dataframe.apply(lambda series: series.astype(str).str.strip())
    return dataframe


def _count_absurd_negative_sentinels(dataframe: pd.DataFrame) -> int:
    """Count absurdly negative numeric sentinel values in a dataframe."""
    count = 0
    for column_name in dataframe.columns:
        count += int(
            dataframe[column_name]
            .astype(str)
            .str.strip()
            .apply(_is_absurd_negative_sentinel)
            .sum()
        )
    return count


def _compute_bin_edges_from_columns(columns: list[str]) -> list[float]:
    """Extract bin-edge values from numeric column headers in file order."""
    bin_edges: list[float] = []
    for column_name in columns:
        if not _is_bin_edge_column(column_name):
            continue
        parsed = _try_parse_float(column_name)
        if parsed is not None:
            bin_edges.append(parsed)
    return bin_edges


def _compute_bin_centers(bin_edges_um: list[float]) -> list[float]:
    """Compute consecutive bin centers from ordered edge values."""
    if len(bin_edges_um) < 2:
        return []
    return [
        (bin_edges_um[idx - 1] + bin_edges_um[idx]) / 2.0
        for idx in range(1, len(bin_edges_um))
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
        raise FileNotFoundError(
            f"SprayTec CSV file not found: {resolved_path}")
    if not resolved_path.is_file():
        raise ValueError(f"Path is not a file: {resolved_path}")
    return resolved_path


def load_spraytec_csv(file_path: str | Path | None = None) -> SpraytecCsvData:
    """Load one SprayTec CSV and split constant metadata vs measurement data.

    Metadata columns are detected as columns containing at most one effective
    non-missing value over all rows.
    """
    resolved_path = resolve_spraytec_csv_file_path(file_path)
    dataframe = _read_spraytec_csv_dataframe(resolved_path)
    absurd_values_converted_count = _count_absurd_negative_sentinels(dataframe)

    if dataframe.empty:
        raise ValueError(
            f"SprayTec CSV contains no data rows: {resolved_path}")

    print(
        "SprayTec warning: converted "
        f"{absurd_values_converted_count} absurdly large negative value(s) to NaN "
        f"while loading {resolved_path.name}."
    )

    metadata_flat: dict[str, Any] = {}
    measurement_columns: list[str] = []
    bin_edges_um = _compute_bin_edges_from_columns(list(dataframe.columns))
    bin_centers_um = _compute_bin_centers(bin_edges_um)

    for column_name in dataframe.columns:
        if _is_bin_edge_column(column_name):
            measurement_columns.append(column_name)
            continue

        normalized_values = [
            _normalize_missing_value(value) for value in dataframe[column_name].tolist()
        ]
        unique_non_missing_values = {
            value for value in normalized_values if value is not None}

        if len(unique_non_missing_values) <= 1:
            only_value = next(iter(unique_non_missing_values), None)
            metadata_flat[column_name] = _parse_scalar(only_value)
        else:
            measurement_columns.append(column_name)

    measurement_df = dataframe[measurement_columns].copy()
    for column_name in measurement_df.columns:
        measurement_df[column_name] = _coerce_numeric_if_possible(
            measurement_df[column_name])

    metadata_by_category = _group_metadata_by_prefix(metadata_flat)

    return SpraytecCsvData(
        file_path=resolved_path,
        data_df=dataframe,
        measurement_df=measurement_df,
        measurement_columns=list(measurement_df.columns),
        metadata_flat=metadata_flat,
        metadata_by_category=metadata_by_category,
        bin_edges_um=bin_edges_um,
        bin_centers_um=bin_centers_um,
        absurd_values_converted_count=absurd_values_converted_count,
    )


def load_spraytec_csvs(
    folder_path: str | Path,
    pattern: str = DEFAULT_SPRAYTEC_CSV_GLOB,
) -> list[SpraytecCsvData]:
    """Load all SprayTec CSV files in a folder and return typed results."""
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"SprayTec folder not found: {folder}")
    if not folder.is_dir():
        raise ValueError(f"Path is not a folder: {folder}")

    csv_paths = natsorted(
        path for path in folder.glob(pattern) if path.is_file())
    if not csv_paths:
        raise ValueError(
            f"No SprayTec CSV files found in {folder} with pattern '{pattern}'")

    return [load_spraytec_csv(path) for path in csv_paths]
