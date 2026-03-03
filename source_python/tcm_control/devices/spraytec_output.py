from __future__ import annotations

import csv
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from tcm_utils.io_utils import ask_open_file, prompt_yes_no
from tcm_utils.time_utils import timestamp_str
from pathlib import Path


AUDIT_FILENAME = "spraytec_parsing_audit.csv"
REDUNDANCY_DIRNAME = "spraytec_individual_measurements"
ARCHIVE_DIRNAME = "archive"
DEFAULT_APPEND_MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024


def resolve_append_file_path(append_file_path: str | Path | None) -> Path:
    if append_file_path is None:
        selected_path = ask_open_file(
            key="spraytec_append_file",
            title="Select SprayTec append file",
            filetypes=[("Text files", "*.txt"),
                        ("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if selected_path is None:
            raise ValueError("No SprayTec append file selected.")
        append_path = Path(selected_path)
    else:
        append_path = Path(append_file_path)

    if not append_path.exists():
        raise FileNotFoundError(
            f"SprayTec append file not found: {append_path}")

    return append_path


def archive_spraytec_append_file(
    append_file_path: str | Path | None = None,
) -> Path:
    append_path = resolve_append_file_path(append_file_path)
    archive_dir = append_path.parent / ARCHIVE_DIRNAME
    archive_dir.mkdir(parents=True, exist_ok=True)

    archived_name = f"archived_{timestamp_str()}_{append_path.name}"
    archive_target = _next_available_path(archive_dir / archived_name)
    shutil.move(str(append_path), str(archive_target))
    return archive_target


@dataclass
class SpraytecBlock:
    measurement_idx: int
    block_id: str
    start_line: int
    end_line: int
    timestamp_raw: str
    timestamp_dt: datetime | None
    lot_value: str
    header_mode: str
    header_row: list[str]
    rows: list[list[str]]


def _row_is_header(row: list[str]) -> bool:
    if len(row) < 2:
        return False
    return row[0].strip() == "Date-Time" and row[1].strip() == "Material"


def _parse_spraytec_datetime(value: str) -> datetime | None:
    clean_value = value.strip()
    if not clean_value:
        return None

    dt_formats = (
        "%d %b %Y %H:%M:%S.%f",
        "%d %b %Y %H:%M:%S",
    )
    for dt_format in dt_formats:
        try:
            return datetime.strptime(clean_value, dt_format)
        except ValueError:
            continue
    return None


def _parse_start_time(value: str | int | float | None) -> datetime | None:
    if value is None:
        return None

    clean_value = str(value).strip()
    if not clean_value:
        return None

    formats = (
        "%y%m%d_%H%M%S",
        "%Y%m%d_%H%M%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d %b %Y %H:%M:%S.%f",
        "%d %b %Y %H:%M:%S",
    )
    for dt_format in formats:
        try:
            return datetime.strptime(clean_value, dt_format)
        except ValueError:
            continue

    raise ValueError(
        "Unsupported start_time format. Use yyMMdd_HHmmss, YYYYmmdd_HHMMSS, "
        "YYYY-mm-dd HH:MM:SS, or SprayTec datetime format."
    )


def _parse_lot_value(value: str) -> float | None:
    clean_value = value.strip()
    if not clean_value or clean_value == "---":
        return None
    try:
        return float(clean_value)
    except ValueError:
        return None


def _measurement_id(start_line: int, timestamp_raw: str, lot_value: str) -> str:
    return f"L{start_line}|T{timestamp_raw.strip()}|V{lot_value.strip()}"


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _load_audit_rows(audit_path: Path) -> dict[str, dict[str, str]]:
    if not audit_path.exists():
        return {}

    with open(audit_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [row for row in reader if row.get("block_id")]
    return {row["block_id"]: row for row in rows}


def _write_audit_rows(audit_path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "block_id",
        "measurement_idx",
        "start_line",
        "end_line",
        "timestamp_raw",
        "timestamp_iso",
        "lot_value",
        "header_mode",
        "rows_count",
        "cached_saved",
        "cached_csv",
        "copied_to_experiment",
        "experiment_dir",
        "experiment_csv",
        "copied_at",
    ]

    with open(audit_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_block_csv(block: SpraytecBlock, file_path: Path, fallback_header: list[str]) -> None:
    header_row = block.header_row or fallback_header
    with open(file_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header_row)
        writer.writerows(block.rows)


def _timestamp_for_filename(dt_value: datetime | None) -> str:
    if dt_value is None:
        return time.strftime("%y%m%d_%H%M%S_%f")
    return dt_value.strftime("%y%m%d_%H%M%S_%f")


def _block_to_audit_row(
        block: SpraytecBlock,
        previous: dict[str, str] | None = None,
) -> dict[str, str]:
    row = {
        "block_id": block.block_id,
        "measurement_idx": str(block.measurement_idx),
        "start_line": str(block.start_line),
        "end_line": str(block.end_line),
        "timestamp_raw": block.timestamp_raw,
        "timestamp_iso": block.timestamp_dt.isoformat() if block.timestamp_dt is not None else "",
        "lot_value": block.lot_value,
        "header_mode": block.header_mode,
        "rows_count": str(len(block.rows)),
        "cached_saved": "0",
        "cached_csv": "",
        "copied_to_experiment": "0",
        "experiment_dir": "",
        "experiment_csv": "",
        "copied_at": "",
    }

    if previous is not None:
        row["cached_saved"] = previous.get("cached_saved", row["cached_saved"])
        row["cached_csv"] = previous.get("cached_csv", row["cached_csv"])
        row["copied_to_experiment"] = previous.get(
            "copied_to_experiment", row["copied_to_experiment"]
        )
        row["experiment_dir"] = previous.get(
            "experiment_dir", row["experiment_dir"])
        row["experiment_csv"] = previous.get(
            "experiment_csv", row["experiment_csv"])
        row["copied_at"] = previous.get("copied_at", row["copied_at"])

    return row


def _build_blocks(append_path: Path) -> tuple[list[str], list[SpraytecBlock]]:
    top_header: list[str] | None = None
    active_header: list[str] | None = None
    lot_value_col: int | None = None

    blocks: list[SpraytecBlock] = []
    current_block: SpraytecBlock | None = None

    should_start_after_header = False
    previous_lot_value: float | None = None

    with open(append_path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for line_no, row in enumerate(reader, start=1):
            if not row:
                continue

            if _row_is_header(row):
                if top_header is None:
                    top_header = row
                active_header = row
                should_start_after_header = True
                previous_lot_value = None
                try:
                    lot_value_col = active_header.index("Lot Value")
                except ValueError:
                    lot_value_col = None
                continue

            if active_header is None:
                continue

            timestamp_raw = row[0].strip() if row else ""
            timestamp_dt = _parse_spraytec_datetime(timestamp_raw)
            if timestamp_dt is None:
                continue

            lot_value = ""
            if lot_value_col is not None and lot_value_col < len(row):
                lot_value = row[lot_value_col].strip()
            lot_numeric = _parse_lot_value(lot_value)

            starts_new_block = False
            header_mode = "inherited"

            if current_block is None:
                starts_new_block = True
                header_mode = "explicit" if should_start_after_header else "inherited"
            elif should_start_after_header:
                starts_new_block = True
                header_mode = "explicit"
            elif (
                    lot_numeric is not None
                    and previous_lot_value is not None
                    and lot_numeric > previous_lot_value
            ):
                starts_new_block = True
                header_mode = "lot-increase"

            if starts_new_block:
                if current_block is not None:
                    blocks.append(current_block)

                block_id = _measurement_id(line_no, timestamp_raw, lot_value)
                current_block = SpraytecBlock(
                    measurement_idx=len(blocks) + 1,
                    block_id=block_id,
                    start_line=line_no,
                    end_line=line_no,
                    timestamp_raw=timestamp_raw,
                    timestamp_dt=timestamp_dt,
                    lot_value=lot_value,
                    header_mode=header_mode,
                    header_row=active_header,
                    rows=[],
                )

            if current_block is None:
                continue

            current_block.rows.append(row)
            current_block.end_line = line_no
            should_start_after_header = False

            if lot_numeric is not None:
                previous_lot_value = lot_numeric

    if current_block is not None:
        blocks.append(current_block)

    if top_header is None:
        raise ValueError("Could not find SprayTec header row in append file.")

    return top_header, blocks


def list_spraytec_runs(
        append_file_path: str | Path | None = None,
) -> list[dict[str, str]]:
    append_path = resolve_append_file_path(append_file_path)

    _header, blocks = _build_blocks(append_path)
    audit_path = append_path.parent / AUDIT_FILENAME
    previous_rows = _load_audit_rows(audit_path)

    audit_rows: list[dict[str, str]] = []
    for block in blocks:
        previous = previous_rows.get(block.block_id)
        audit_rows.append(_block_to_audit_row(block, previous=previous))

    _write_audit_rows(audit_path, audit_rows)
    return audit_rows


def save_spraytec_data(
        append_file_path: str | Path | None = None,
        experiment_dir: str | Path | None = None,
        start_time: str | None = None,
        debug: bool = False,
        max_append_file_size_bytes: int = DEFAULT_APPEND_MAX_FILE_SIZE_BYTES,
        offer_archive_if_large: bool = True,
) -> Path:
    append_path = resolve_append_file_path(append_file_path)
    append_file_size_bytes = append_path.stat().st_size
    should_offer_archive = (
        offer_archive_if_large
        and max_append_file_size_bytes > 0
        and append_file_size_bytes > max_append_file_size_bytes
    )

    header_row, blocks = _build_blocks(append_path)
    audit_path = append_path.parent / AUDIT_FILENAME
    redundancy_dir = append_path.parent / REDUNDANCY_DIRNAME
    audit_file_created = not audit_path.exists()
    previous_rows = _load_audit_rows(audit_path)

    start_dt = _parse_start_time(start_time)
    experiment_path = Path(experiment_dir).resolve(
    ) if experiment_dir is not None else None
    if experiment_path is not None:
        experiment_path.mkdir(parents=True, exist_ok=True)

    audit_rows: list[dict[str, str]] = []
    extracted_count = 0
    copied_count = 0
    older_unprocessed_count = 0

    for block in blocks:
        if start_dt is None or block.timestamp_dt is None:
            continue
        if block.timestamp_dt <= start_dt:
            previous = previous_rows.get(block.block_id)
            copied = previous is not None and previous.get("copied_to_experiment") == "1"
            if not copied:
                older_unprocessed_count += 1

    for block in blocks:
        previous = previous_rows.get(block.block_id)
        row = _block_to_audit_row(block, previous=previous)

        is_after_start = (
            start_dt is None
            or (block.timestamp_dt is not None and block.timestamp_dt > start_dt)
        )
        already_copied = row.get("copied_to_experiment") == "1"

        if is_after_start and not already_copied:
            redundancy_dir.mkdir(parents=True, exist_ok=True)
            timestamp_label = _timestamp_for_filename(block.timestamp_dt)
            local_filename = f"spraytec_{timestamp_label}.csv"
            local_path = _next_available_path(redundancy_dir / local_filename)

            _write_block_csv(block, local_path, fallback_header=header_row)
            extracted_count += 1

            row["cached_saved"] = "1"
            row["cached_csv"] = str(local_path)

            should_copy_to_experiment = experiment_path is not None

            if should_copy_to_experiment:
                assert experiment_path is not None
                experiment_filename = f"spraytec_{timestamp_label}.csv"
                experiment_csv = _next_available_path(
                    experiment_path / experiment_filename)
                shutil.copy2(local_path, experiment_csv)
                copied_count += 1

                row["copied_to_experiment"] = "1"
                row["experiment_dir"] = str(experiment_path)
                row["experiment_csv"] = str(experiment_csv)
                row["copied_at"] = datetime.now().isoformat(timespec="seconds")

        audit_rows.append(row)

    _write_audit_rows(audit_path, audit_rows)

    if audit_file_created:
        print(f"SprayTec: created new audit file at {audit_path}")

    if older_unprocessed_count > 0:
        print(
            "SprayTec warning: "
            f"{older_unprocessed_count} measurement(s) before start time are still unprocessed."
        )

    if not debug:
        if experiment_path is None:
            print(f"SprayTec: extracted {extracted_count} file(s) to {redundancy_dir}.")
        else:
            print(
                f"SprayTec: extracted {extracted_count} file(s) to {redundancy_dir}; "
                f"copied {copied_count} to {experiment_path}."
            )
    else:
        print(
            "SprayTec debug: "
            f"detected={len(blocks)}, extracted={extracted_count}, copied={copied_count}, "
            f"audit={audit_path}"
        )

    if should_offer_archive:
        max_size_mb = max_append_file_size_bytes / (1024 * 1024)
        current_size_mb = append_file_size_bytes / (1024 * 1024)
        archive_now = prompt_yes_no(
            "SprayTec append file is large "
            f"({current_size_mb:.1f} MB > {max_size_mb:.1f} MB). Archive now?",
            default=False,
        )
        if archive_now:
            archived_path = archive_spraytec_append_file(append_path)
            print(f"SprayTec: append file archived to {archived_path}")

    return audit_path

    # ------------------------------------------------------------------------------
    # LEGACY FUNCTIONS
    # ------------------------------------------------------------------------------

    # def split_array_by_header_marker(arr, marker='Date-Time'):
    #     arr = np.array(arr)
    #     header = arr[:, 0]
    #     rows = arr[:, 1:]

    #     # Find indices where header has the marker
    #     split_indices = [i for i, val in enumerate(header) if val == marker]
    #     split_indices.append(len(header))  # include end boundary

    #     result = []
    #     for i in range(len(split_indices) - 1):
    #         start = split_indices[i]
    #         end = split_indices[i+1]
    #         section = arr[start:end]
    #         result.append(section)

    #     return result

    # def Spraytec_data_saved_check():
    #     """
    #     This function saves the last spraytec measurement of the previous run to a .txt
    #     in the folder individual_data_files. Do not touch this if you do not know waht you are doing!
    #     """
    #     # current_dir = os.path.dirname(os.path.abspath(__file__))
    #     # parent_path = os.path.dirname(current_dir)  # one level up
    #     spraytec_path = os.path.join("C:\\CoughMachineData\\SprayTec\\")
    #     path = os.path.join(spraytec_path, "SPRAYTEC_APPEND_FILE.txt")
    #     save_path = os.path.join(spraytec_path, "individual_data_files")
    #     file = np.loadtxt(path, dtype=str, delimiter=',')
    #     split_sections = split_array_by_header_marker(file)
    #     last_file = split_sections[-1]
    #     time_created = last_file[1, 0]
    #     filename = last_file[1, 1]
    #     dt = datetime.strptime(time_created, '%d %b %Y %H:%M:%S.%f')
    #     # Format as YYYY_MM_DD_HH_MM
    #     file_name_time = dt.strftime('%Y_%m_%d_%H_%M')
    #     save_path = os.path.join(
    #         save_path, file_name_time + "_" + filename + ".txt")
    #     if not os.path.exists(save_path):
    #         np.savetxt(save_path, last_file, fmt='%s', delimiter=',')
    #         print(f"Saved spraytec_data of {file_name_time}")
