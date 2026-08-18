from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from tcm_utils.file_dialogs import ask_directory
from tcm_utils.io_utils import path_relative_to


METADATA_GLOB = "metadata*.json"


def get_nested_value(payload: dict[str, Any], key_path: str) -> Any:
    """Return a nested value using dotted paths, e.g. 'experiment.temperature_start'."""
    current: Any = payload
    for key in key_path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise KeyError(
                f"Missing key path '{key_path}' at segment '{key}'.")
        current = current[key]
    return current


def find_metadata_files(root_dir: Path) -> list[Path]:
    """Find metadata files recursively under root_dir."""
    return sorted(path for path in root_dir.rglob(METADATA_GLOB) if path.is_file())


def collect_metadata_rows(root_dir: Path, variable_paths: list[str]) -> list[dict[str, Any]]:
    """Read all metadata files and collect requested variables into row dicts."""
    rows: list[dict[str, Any]] = []

    for metadata_path in find_metadata_files(root_dir):
        with metadata_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)

        row: dict[str, Any] = {
            "metadata_file": path_relative_to(metadata_path, root_dir),
            "time_start": get_nested_value(payload, "time.start"),
            "time_finish": get_nested_value(payload, "time.finish"),
        }

        for variable_path in variable_paths:
            try:
                row[variable_path] = get_nested_value(payload, variable_path)
            except KeyError:
                row[variable_path] = ""

        rows.append(row)

    return rows


def write_summary_csv(root_dir: Path, rows: list[dict[str, Any]], csv_name: str) -> Path:
    """Write a long-format CSV including per-file values and aggregate stats rows."""
    csv_path = root_dir / csv_name

    fieldnames = [
        "metadata_file",
        "time_start",
        "time_finish",
        "variable",
        "value",
        "group",
        "mean",
        "stddev",
        "count",
    ]

    # Collect numeric values per variable for aggregate rows.
    numeric_by_variable: dict[str, list[float]] = {}

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            for key, value in row.items():
                if key in {"metadata_file", "time_start", "time_finish"}:
                    continue

                writer.writerow(
                    {
                        "metadata_file": row["metadata_file"],
                        "time_start": row["time_start"],
                        "time_finish": row["time_finish"],
                        "variable": key,
                        "value": value,
                        "group": "value",
                        "mean": "",
                        "stddev": "",
                        "count": "",
                    }
                )

                if isinstance(value, (int, float)):
                    numeric_by_variable.setdefault(
                        key, []).append(float(value))

        for variable, values in sorted(numeric_by_variable.items()):
            if not values:
                continue
            mean = float(np.mean(values))
            stddev = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
            writer.writerow(
                {
                    "metadata_file": "",
                    "time_start": "",
                    "time_finish": "",
                    "variable": variable,
                    "value": "",
                    "group": "summary",
                    "mean": f"{mean:.6g}",
                    "stddev": f"{stddev:.6g}",
                    "count": len(values),
                }
            )

    return csv_path


def main() -> int:
    selected = ask_directory(
        key="extract_metadata_values_root_dir",
        title="Select root folder containing metadata_*.json files",
        start=Path(__file__).resolve().parent,
    )
    if not selected:
        print("No folder selected.")
        return 1

    root_dir = Path(selected).expanduser().resolve()

    # Expand this list to include any additional dotted key paths from metadata.
    variable_paths = [
        "experiment.temperature_start",
        "experiment.temperature_finish",
        "experiment.humidity_start",
        "experiment.humidity_finish",
    ]

    rows = collect_metadata_rows(root_dir, variable_paths=variable_paths)
    if not rows:
        print(f"No files matching '{METADATA_GLOB}' found under: {root_dir}")
        return 1

    csv_path = write_summary_csv(
        root_dir, rows, csv_name="metadata_variable_report.csv")
    print(f"Wrote {len(rows)} metadata records to: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
