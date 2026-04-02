from __future__ import annotations

"""Parse, cache, and export SprayTec measurements from append files.

This module handles four main tasks:
1) Resolve and optionally archive the rolling SprayTec append file.
2) Parse append-file rows into logical measurement blocks.
3) Persist parsing state in an audit CSV for idempotent processing.
4) Save per-measurement CSV files to a local redundancy folder and
    optionally copy them into an experiment folder.
"""

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime
from tcm_utils.io_utils import (
    ask_open_file,
    make_minimal_progress_bar,
    prompt_yes_no,
)
from tcm_utils.time_utils import timestamp_str
from pathlib import Path

from tcm_control.logger import create_labeled_csv_filename


# =============================================================================
# Constants
# =============================================================================

# File and folder names used beside the append file.
AUDIT_FILENAME = "spraytec_parsing_audit.csv"
REDUNDANCY_DIRNAME = "spraytec_individual_measurements"
ARCHIVE_DIRNAME = "archive"
EXPERIMENT_SPRAYTEC_SUBDIR = "spraytec"
DEFAULT_APPEND_MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024


class SprayTec:
    """Stateful SprayTec helper storing append parsing and export configuration."""

    def __init__(
        self,
        append_file_path: str | Path | None = None,
        experiment_dir: str | Path | None = None,
        max_append_file_size_bytes: int = DEFAULT_APPEND_MAX_FILE_SIZE_BYTES,
        offer_archive_if_large: bool = True,
    ):
        # Persist default workflow inputs so subsequent method calls can omit
        # repeated arguments (append file path, output directory, archive policy).
        self.append_file_path = (
            Path(append_file_path) if append_file_path is not None else None
        )
        self.experiment_dir = (
            Path(experiment_dir).resolve() if experiment_dir is not None else None
        )
        self.max_append_file_size_bytes = max_append_file_size_bytes
        self.offer_archive_if_large = offer_archive_if_large

        # Runtime state populated by listing/saving operations.
        # These fields allow callers to inspect outcomes after each step.
        self.audit_path: Path | None = None
        self.last_listed_runs: list[dict[str, str]] = []

    def resolve_append_file_path(
        self,
        append_file_path: str | Path | None = None,
    ) -> Path:
        """Resolve and store append-file path for subsequent operations."""
        # Prefer explicit argument when provided, otherwise fall back to the
        # instance default configured at construction time.
        candidate = (
            append_file_path if append_file_path is not None else self.append_file_path
        )

        # If no path is supplied, ask the user to pick the current SprayTec append file.
        if candidate is None:
            selected_path = ask_open_file(
                key="spraytec_append_file",
                title="Select SprayTec append file",
                filetypes=[
                    ("Text files", "*.txt"),
                    ("CSV files", "*.csv"),
                    ("All files", "*.*"),
                ],
            )
            if selected_path is None:
                raise ValueError("No SprayTec append file selected.")
            resolved_path = Path(selected_path)
        else:
            # Normalize any string/Path-like input to a Path instance.
            resolved_path = Path(candidate)

        # Fail early when the configured file does not exist.
        if not resolved_path.exists():
            raise FileNotFoundError(
                f"SprayTec append file not found: {resolved_path}"
            )

        self.append_file_path = resolved_path
        return resolved_path

    def archive_append_file(self, append_file_path: str | Path | None = None) -> Path:
        """Archive append file and clear stored append path."""
        # Resolve source file and ensure the archive target folder exists.
        append_path = self.resolve_append_file_path(append_file_path)
        archive_dir = append_path.parent / ARCHIVE_DIRNAME
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Prefix the original filename with an archive timestamp, avoiding collisions.
        archived_name = f"archived_{timestamp_str()}_{append_path.name}"
        archive_target = _next_available_path(archive_dir / archived_name)
        shutil.move(str(append_path), str(archive_target))

        self.append_file_path = None
        return archive_target

    def list_runs(self, append_file_path: str | Path | None = None) -> list[dict[str, str]]:
        """Refresh audit rows and store latest list/audit path in instance state."""
        append_path = self.resolve_append_file_path(append_file_path)
        _header, blocks = _build_blocks(append_path)

        audit_path = append_path.parent / AUDIT_FILENAME
        previous_rows = _load_audit_rows(audit_path)

        rows: list[dict[str, str]] = []
        for block in blocks:
            previous = previous_rows.get(block.block_id)
            rows.append(_block_to_audit_row(block, previous=previous))

        _write_audit_rows(audit_path, rows)

        self.last_listed_runs = rows
        self.audit_path = audit_path
        return rows

    def save_data(
        self,
        append_file_path: str | Path | None = None,
        experiment_dir: str | Path | None = None,
        start_time: str | None = None,
        debug: bool = False,
        max_append_file_size_bytes: int | None = None,
        offer_archive_if_large: bool | None = None,
        ask_retry_on_permission_error: bool = True,
        min_rows_per_block: int = 1,
    ) -> Path:
        """Extract new measurements and update stored audit state.

        When ``ask_retry_on_permission_error`` is True, this method catches
        ``PermissionError`` (for example when the SprayTec append file is still
        locked by the exporter), prompts the user to retry, and loops until
        success or user cancellation.
        """
        # Step 1: Resolve effective append file and update per-call overrides.
        resolved_append_path = self.resolve_append_file_path(append_file_path)
        print(
            f"Gathering SprayTec data from append file: {resolved_append_path}")
        if experiment_dir is not None:
            self.experiment_dir = Path(experiment_dir).resolve()

        if max_append_file_size_bytes is not None:
            self.max_append_file_size_bytes = max_append_file_size_bytes
        if offer_archive_if_large is not None:
            self.offer_archive_if_large = offer_archive_if_large

        # Step 2: Run extraction in a retry loop to handle temporary file locks.
        default_audit_path = resolved_append_path.parent / AUDIT_FILENAME
        while True:
            try:
                # 2a) Resolve file size/archive policy and parse append blocks.
                append_path = resolved_append_path
                append_file_size_bytes = append_path.stat().st_size
                should_offer_archive = (
                    self.offer_archive_if_large
                    and self.max_append_file_size_bytes > 0
                    and append_file_size_bytes > self.max_append_file_size_bytes
                )

                header_row, blocks = _build_blocks(append_path)
                blocks = _apply_min_rows_filter(
                    blocks=blocks,
                    min_rows_per_block=max(1, int(min_rows_per_block)),
                    debug=debug,
                )

                # 2b) Prepare audit/cache/output paths and optional start-time filter.
                audit_path = append_path.parent / AUDIT_FILENAME
                redundancy_dir = append_path.parent / REDUNDANCY_DIRNAME
                audit_file_created = not audit_path.exists()
                previous_rows = _load_audit_rows(audit_path)

                start_dt = _parse_start_time(start_time)
                experiment_path = (
                    self.experiment_dir / EXPERIMENT_SPRAYTEC_SUBDIR
                    if self.experiment_dir is not None
                    else None
                )
                if experiment_path is not None:
                    experiment_path.mkdir(parents=True, exist_ok=True)

                # 2c) Initialize counters/state for per-block processing.
                audit_rows: list[dict[str, str]] = []
                extracted_count = 0
                copied_count = 0
                older_unprocessed_count = 0
                first_experiment_csv: Path | None = None
                first_experiment_timestamp: str | None = None
                first_experiment_row: dict[str, str] | None = None

                # Count historical blocks that are before start time and still uncopied.
                for block in blocks:
                    if start_dt is None or block.timestamp_dt is None:
                        continue
                    if block.timestamp_dt <= start_dt:
                        previous = previous_rows.get(block.block_id)
                        copied = previous is not None and previous.get(
                            "copied_to_experiment") == "1"
                        if not copied:
                            older_unprocessed_count += 1

                # 2d) Process all blocks and persist/copy only new measurements.
                with make_minimal_progress_bar(
                    total=len(blocks),
                    label="SprayTec",
                    unit_label="blocks",
                ) as pbar:
                    for block in blocks:
                        previous = previous_rows.get(block.block_id)
                        row = _block_to_audit_row(block, previous=previous)

                        is_after_start = (
                            start_dt is None
                            or (block.timestamp_dt is not None and block.timestamp_dt > start_dt)
                        )
                        already_copied = row.get("copied_to_experiment") == "1"

                        if is_after_start and not already_copied:
                            # Always save parsed measurement in local redundancy cache first.
                            redundancy_dir.mkdir(parents=True, exist_ok=True)
                            timestamp_label = timestamp_str(
                                block.timestamp_dt,
                                include_us=True,
                            )
                            local_filename = f"spraytec_{timestamp_label}.csv"
                            local_path = _next_available_path(
                                redundancy_dir / local_filename)

                            _write_block_csv(
                                block, local_path, fallback_header=header_row)
                            extracted_count += 1

                            row["cached_saved"] = "1"
                            row["cached_csv"] = str(local_path)

                            should_copy_to_experiment = experiment_path is not None
                            if should_copy_to_experiment:
                                assert experiment_path is not None
                                next_copy_index = copied_count + 1

                                # If this becomes a multi-file batch, rename first copied file to
                                # label 1 so copied files are consistently numbered 1..N.
                                if (
                                    next_copy_index == 2
                                    and first_experiment_csv is not None
                                    and first_experiment_timestamp is not None
                                    and first_experiment_row is not None
                                ):
                                    first_labeled_filename = create_labeled_csv_filename(
                                        prefix="spraytec",
                                        label=1,
                                        timestamp=first_experiment_timestamp,
                                    )
                                    first_labeled_path = _next_available_path(
                                        experiment_path / first_labeled_filename
                                    )
                                    first_experiment_csv.rename(
                                        first_labeled_path)
                                    first_experiment_csv = first_labeled_path
                                    first_experiment_row["experiment_csv"] = str(
                                        first_labeled_path
                                    )

                                label = next_copy_index if next_copy_index > 1 else None
                                experiment_filename = create_labeled_csv_filename(
                                    prefix="spraytec",
                                    label=label,
                                    timestamp=timestamp_label,
                                )
                                experiment_csv = _next_available_path(
                                    experiment_path / experiment_filename
                                )
                                shutil.copy2(local_path, experiment_csv)
                                copied_count += 1

                                row["copied_to_experiment"] = "1"
                                row["experiment_dir"] = str(experiment_path)
                                row["experiment_csv"] = str(experiment_csv)
                                row["copied_at"] = datetime.now().isoformat(
                                    timespec="seconds"
                                )

                                # Keep first copied file state for potential retroactive label.
                                if copied_count == 1:
                                    first_experiment_csv = experiment_csv
                                    first_experiment_timestamp = timestamp_label
                                    first_experiment_row = row

                        audit_rows.append(row)
                        pbar.update(1)

                # 2e) Persist audit and print run summary.
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
                        print(
                            f"SprayTec: extracted {extracted_count} file(s) to {redundancy_dir}."
                        )
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

                # 2f) Optionally archive oversized append files after successful processing.
                if should_offer_archive:
                    max_size_mb = self.max_append_file_size_bytes / \
                        (1024 * 1024)
                    current_size_mb = append_file_size_bytes / (1024 * 1024)
                    archive_now = prompt_yes_no(
                        "SprayTec append file is large "
                        f"({current_size_mb:.1f} MB > {max_size_mb:.1f} MB). Archive now (press ENTER for yes or type 'n')?",
                        default=True,
                    )
                    if archive_now:
                        archived_path = self.archive_append_file(append_path)
                        print(
                            f"SprayTec: append file archived to {archived_path}")

                break
            except PermissionError as err:
                if not ask_retry_on_permission_error:
                    raise

                print(
                    "SprayTec append file is currently in use; "
                    "wait for SprayTec to finish exporting, then retry."
                )
                if debug:
                    print(f"SprayTec debug: {err}")

                retry_now = prompt_yes_no(
                    "Retry SprayTec append-file parsing now (press ENTER for yes or type 'n')?",
                    default=True,
                )
                if retry_now:
                    continue

                print(
                    "SprayTec save skipped; export manually from SprayTec software"
                )
                self.audit_path = default_audit_path
                return default_audit_path

        self.audit_path = audit_path

        return audit_path


@dataclass
class SpraytecBlock:
    """Container for one parsed measurement block in the append file."""
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


# =============================================================================
# Helpers used by append parsing/saving
# =============================================================================


def _row_is_header(row: list[str]) -> bool:
    """Detect the canonical SprayTec data header row."""
    if len(row) < 2:
        return False
    return row[0].strip() == "Date-Time" and row[1].strip() == "Material"


def _parse_spraytec_datetime(value: str) -> datetime | None:
    """Parse a SprayTec timestamp field, returning None for non-data rows."""
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
    """Parse the run start time across accepted formats."""
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
    """Convert the Lot Value column to float when possible."""
    clean_value = value.strip()
    if not clean_value or clean_value == "---":
        return None
    try:
        return float(clean_value)
    except ValueError:
        return None


def _measurement_id(start_line: int, timestamp_raw: str, lot_value: str) -> str:
    """Build a stable block identifier used by the audit CSV."""
    return f"L{start_line}|T{timestamp_raw.strip()}|V{lot_value.strip()}"


def _apply_min_rows_filter(
    blocks: list[SpraytecBlock],
    min_rows_per_block: int,
    debug: bool = False,
) -> list[SpraytecBlock]:
    """Optionally drop short blocks after explicit user confirmation."""
    if min_rows_per_block <= 1:
        return blocks

    short_blocks = [block for block in blocks if len(
        block.rows) < min_rows_per_block]
    if not short_blocks:
        return blocks

    should_reject = prompt_yes_no(
        "SprayTec: found "
        f"{len(short_blocks)} block(s) with fewer than {min_rows_per_block} row(s). "
        "Reject these short outputs (press ENTER for yes or type 'n')?",
        default=True,
    )
    if not should_reject:
        return blocks

    kept_blocks = [block for block in blocks if len(
        block.rows) >= min_rows_per_block]
    for idx, block in enumerate(kept_blocks, start=1):
        block.measurement_idx = idx

    if debug:
        print(
            "SprayTec debug: rejected "
            f"{len(short_blocks)} short block(s) with min_rows_per_block={min_rows_per_block}."
        )

    return kept_blocks
# =============================================================================
# Append parsing + audit persistence helpers
# =============================================================================


def _next_available_path(path: Path) -> Path:
    """Return path or first free suffixed variant (_2, _3, ...)."""
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
    """Load existing audit rows keyed by block_id."""
    if not audit_path.exists():
        return {}

    with open(audit_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [row for row in reader if row.get("block_id")]
    return {row["block_id"]: row for row in rows}


def _write_audit_rows(audit_path: Path, rows: list[dict[str, str]]) -> None:
    """Rewrite the full audit CSV with a fixed schema."""
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
    """Write one parsed measurement block to CSV."""
    # Prefer the block-specific header, but fall back to the top header if needed.
    header_row = block.header_row or fallback_header
    with open(file_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header_row)
        writer.writerows(block.rows)


def _block_to_audit_row(
        block: SpraytecBlock,
        previous: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map a parsed block to one audit row, preserving prior status fields."""
    # Initialize deterministic block metadata and empty processing status values.
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

    # Carry over prior processing state to make repeated runs idempotent.
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
    """Parse append file into measurement blocks and return (header, blocks)."""
    # top_header: first explicit data header encountered in the file.
    # active_header: most recently seen header, used for following rows.
    # lot_value_col: optional index of "Lot Value" when present.
    top_header: list[str] | None = None
    active_header: list[str] | None = None
    lot_value_col: int | None = None

    blocks: list[SpraytecBlock] = []
    current_block: SpraytecBlock | None = None

    should_start_after_header = False
    previous_lot_value: float | None = None

    # Read the append file row-by-row to detect boundaries between measurements.
    with open(append_path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for line_no, row in enumerate(reader, start=1):
            if not row:
                continue

            # Header rows reset per-section parsing state.
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

            # Only rows with a parseable timestamp are considered data rows.
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

            # Start a new block when:
            # 1) we have no current block yet,
            # 2) a fresh header was seen,
            # 3) lot value increases (fallback split heuristic).
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


