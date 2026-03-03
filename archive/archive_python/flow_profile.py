from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from tcm_utils.file_dialogs import ask_open_file, find_repo_root


def extract_flow_profile(filename: str | Path, delimiter: str = ",") -> Tuple[List[str], List[str], List[str]]:
    time_values: List[str] = []
    mA_values: List[str] = []
    enable_values: List[str] = []
    row_idx = 0

    with open(filename, "r") as csvfile:
        csvreader = csv.reader(csvfile, delimiter=delimiter)

        for rows in csvreader:
            if len(rows) < 3 or not rows[0] or not rows[1] or rows[2] == "":
                print(
                    f"Encountered empty cell in flow profile dataset, row index {row_idx}!"
                )
                time_values = []
                mA_values = []
                enable_values = []
                break

            time_values.append(rows[0].replace(",", "."))
            mA_values.append(rows[1].replace(",", "."))
            enable = rows[2].strip()
            if enable not in ("0", "1"):
                raise ValueError(
                    f"Invalid enable value '{enable}' at row {row_idx}; expected 0 or 1"
                )
            enable_values.append(enable)
            row_idx += 1

    return time_values, mA_values, enable_values


def format_flow_profile(
    time_array: Iterable[str],
    mA_array: Iterable[str],
    enable_array: Iterable[str],
    prefix: str = "L",
    handshake_delim: str = " ",
    data_delim: str = ",",
    line_feed: str = "\n",
) -> str:
    time_list = list(time_array)
    mA_list = list(mA_array)
    enable_list = list(enable_array)

    if (
        len(time_list) != len(mA_list)
        or len(time_list) != len(enable_list)
        or len(time_list) == 0
        or len(mA_list) == 0
    ):
        print(
            "Arrays are not compatible! "
            f"Time length: {len(time_list)}, "
            f"mA length: {len(mA_list)}, "
            f"enable length: {len(enable_list)}"
        )
        return ""

    duration = time_list[-1]
    header = [prefix, handshake_delim, str(
        len(time_list)), handshake_delim, duration, handshake_delim]

    data = [
        str(val)
        for time, mA, e in zip(time_list, mA_list, enable_list)
        for val in (time, mA, e)
    ]

    return "".join(header) + data_delim.join(data) + line_feed


def resolve_flow_curve_path(
    file_path: Optional[str],
    key: str = "flow_curve_csv",
    title: str = "Select flow curve CSV",
    default_dir: Optional[Path] = None,
) -> Path:
    repo_root = find_repo_root()
    if file_path:
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Flow curve CSV not found: {path}")
        return path

    if default_dir is None:
        candidate = repo_root / "source_python"
        default_dir = candidate if candidate.exists() else repo_root / "src_python"

    flow_curve_path = ask_open_file(
        key=key,
        title=title,
        filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        default_dir=default_dir,
        start=repo_root,
    )

    if flow_curve_path is None:
        raise SystemExit("No flow curve CSV selected")

    return Path(flow_curve_path)
