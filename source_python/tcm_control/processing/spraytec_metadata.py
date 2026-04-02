from __future__ import annotations

"""SprayTec metadata merge/export helpers.

This module owns metadata-only operations so CSV loading/parsing can stay in
`spraytec_processing.py`.
"""

from pathlib import Path
from typing import Any

from natsort import natsorted
from tcm_utils.io_utils import save_metadata_json

from tcm_control.processing.spraytec_processing import SpraytecCsvData


def _to_jsonable(value: Any) -> Any:
    """Recursively convert values to JSON-safe primitives."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(val) for val in value]
    return value


def export_spraytec_metadata_json(
    spraytec_data: SpraytecCsvData,
    output_dir: str | Path,
    filename: str | None = None,
) -> Path:
    """Export one loaded SprayTec metadata payload as JSON."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    resolved_filename = (
        filename if filename is not None else f"{spraytec_data.file_path.stem}_metadata.json"
    )
    json_path = output_path / resolved_filename

    payload = {
        "source_csv": spraytec_data.file_path,
        "metadata_by_category": spraytec_data.metadata_by_category,
        "time_dependent_columns": spraytec_data.measurement_columns,
        "bin_edges_um": spraytec_data.bin_edges_um,
        "bin_centers_um": spraytec_data.bin_centers_um,
    }

    save_metadata_json(_to_jsonable(payload), json_path)
    return json_path


def export_spraytec_metadata_jsons(
    spraytec_data_list: list[SpraytecCsvData],
    output_dir: str | Path,
) -> list[Path]:
    """Export metadata JSON files for multiple loaded SprayTec CSV files."""
    return [
        export_spraytec_metadata_json(
            spraytec_data=data, output_dir=output_dir)
        for data in spraytec_data_list
    ]


def _merge_metadata_values(values: list[Any]) -> Any:
    """Return shared scalar when all equal; otherwise keep per-file list."""
    if not values:
        return None
    first_value = values[0]
    if all(value == first_value for value in values[1:]):
        return first_value
    return values


def _build_combined_metadata_by_category(
    spraytec_data_list: list[SpraytecCsvData],
) -> dict[str, dict[str, Any]]:
    """Merge categorized metadata across files, listing differing values."""
    all_categories: set[str] = set()
    for data in spraytec_data_list:
        all_categories.update(data.metadata_by_category.keys())

    combined: dict[str, dict[str, Any]] = {}
    for category in natsorted(all_categories):
        all_keys: set[str] = set()
        for data in spraytec_data_list:
            category_dict = data.metadata_by_category.get(category, {})
            all_keys.update(category_dict.keys())

        combined_category: dict[str, Any] = {}
        for key in natsorted(all_keys):
            values = [
                data.metadata_by_category.get(category, {}).get(key)
                for data in spraytec_data_list
            ]
            combined_category[key] = _merge_metadata_values(values)

        combined[category] = combined_category

    return combined


def build_combined_spraytec_metadata(
    spraytec_data_list: list[SpraytecCsvData],
) -> dict[str, Any]:
    """Build one combined metadata dict across multiple SprayTec CSV files."""
    if not spraytec_data_list:
        raise ValueError("spraytec_data_list is empty")

    source_csvs = [str(data.file_path) for data in spraytec_data_list]
    file_names = [data.file_path.name for data in spraytec_data_list]

    all_time_dependent_columns: set[str] = set()
    for data in spraytec_data_list:
        all_time_dependent_columns.update(data.measurement_columns)

    all_bin_edges = [data.bin_edges_um for data in spraytec_data_list]
    all_bin_centers = [data.bin_centers_um for data in spraytec_data_list]
    absurd_counts = [
        data.absurd_values_converted_count for data in spraytec_data_list]
    combined_metadata_by_category = _build_combined_metadata_by_category(
        spraytec_data_list)

    return {
        "source_csvs": source_csvs,
        "source_file_names": file_names,
        "metadata_by_category": combined_metadata_by_category,
        "time_dependent_columns": natsorted(all_time_dependent_columns),
        "bin_edges_um": _merge_metadata_values(all_bin_edges),
        "bin_centers_um": _merge_metadata_values(all_bin_centers),
        "absurd_values_converted_count": {
            "per_file": dict(zip(file_names, absurd_counts, strict=True)),
            "total": sum(absurd_counts),
        },
    }


def export_combined_spraytec_metadata_json(
    spraytec_data_list: list[SpraytecCsvData],
    output_dir: str | Path,
    filename: str = "spraytec_metadata.json",
) -> Path:
    """Export one combined metadata JSON for multiple loaded SprayTec CSV files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    json_path = output_path / filename

    payload = build_combined_spraytec_metadata(spraytec_data_list)
    save_metadata_json(_to_jsonable(payload), json_path)
    return json_path
