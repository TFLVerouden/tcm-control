from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from tcm_utils.file_dialogs import ask_directory
from tcm_utils.io_utils import prompt_input, prompt_yes_no


INVALID_FOLDER_CHARS = re.compile(r"[<>:\"/\\|?*\x00]")

# hallo
def is_valid_folder_name(name: str) -> tuple[bool, str | None]:
    # Keep folder-name validation conservative so merged output is portable.
    if name == "":
        return False, "Folder name cannot be empty."
    if name in {".", ".."}:
        return False, "Folder name cannot be '.' or '..'."
    if INVALID_FOLDER_CHARS.search(name):
        return False, "Folder name contains invalid characters. Avoid any of: <>:\"/\\|?*"
    if name.endswith(" ") or name.endswith("."):
        return False, "Folder name cannot end with a space or dot."
    return True, None


def main() -> int:
    # 1) Ask the user to select multiple experiment folders.
    selected = ask_directory(
        key="merge_experiment_folders_selected_dirs",
        title="Select experiment folders to merge",
        start=Path(__file__).resolve().parent,
        multiple=True,
    )
    if not selected:
        print("No folders selected.")
        return 1

    selected_folders_raw = [selected] if isinstance(
        selected, (str, Path)) else list(selected)
    selected_folders: list[Path] = []
    seen_folders: set[str] = set()

    # 2) Normalize/validate selected paths and remove duplicates.
    for folder_raw in selected_folders_raw:
        folder = Path(folder_raw).expanduser().resolve()
        folder_key = str(folder).lower()
        if folder_key in seen_folders:
            continue
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(
                f"Selected folder does not exist: {folder}")
        selected_folders.append(folder)
        seen_folders.add(folder_key)

    if len(selected_folders) < 2:
        print("Please select at least 2 experiment folders.")
        return 1

    # 3) Read each metadata.json and extract experiment start time.
    experiments: list[tuple[Path, str, datetime]] = []
    for folder in selected_folders:
        metadata_path = folder / "metadata.json"
        if not metadata_path.exists():
            print(f"Missing metadata.json in: {folder}")
            return 1

        with metadata_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)

        start_text = payload.get("time", {}).get(
            "start") if isinstance(payload, dict) else None
        if not isinstance(start_text, str):
            print(f"Could not read time.start from: {metadata_path}")
            return 1

        try:
            start_time = datetime.strptime(start_text, "%y%m%d_%H%M%S")
        except ValueError:
            print(
                f"Invalid time.start format in {metadata_path}: '{start_text}'. "
                "Expected 'YYMMDD_HHMMSS'."
            )
            return 1

        experiments.append((folder, start_text, start_time))

    # 4) Merge order is chronological by metadata time.start.
    experiments.sort(key=lambda item: item[2])

    print("Merge order by metadata time.start:")
    for index, experiment in enumerate(experiments, start=1):
        print(f"  {index}. {experiment[0]} ({experiment[1]})")

    # 5) Ask for destination folder name and validate it.
    suggested_name = f"{experiments[0][0].name}_merged"
    target_parent = experiments[0][0].parent

    while True:
        new_name = prompt_input(
            f"Enter merged folder name [leave empty to use '{suggested_name}']: ",
            value_type="string",
            allow_empty=True,
        )
        candidate_name = (
            suggested_name if new_name is None or str(
                new_name).strip() == "" else str(new_name).strip()
        )

        valid, message = is_valid_folder_name(candidate_name)
        if not valid:
            print(f"Invalid folder name: {message}")
            continue

        target_folder = target_parent / candidate_name
        if target_folder.exists():
            print(f"Target folder already exists: {target_folder}")
            continue

        break

    # 6) Final confirmation before creating output.
    confirm = prompt_yes_no(
        (
            f"Merge {len(experiments)} experiments into '{target_folder}'? "
            "(press ENTER to merge, type 'n' to cancel)"
        ),
        default=True,
    )
    if not confirm:
        print("Cancelled by user.")
        return 1

    target_folder.mkdir(parents=True, exist_ok=False)

    # 7) Initialize counters and tracking for merge planning/copying.
    run_log_counter = 1
    spraytec_counter = 1
    copied_files = 0
    renamed_on_collision = 0
    collision_renames: list[tuple[Path, Path]] = []

    planned_files: list[tuple[Path, Path, str, bool, str]] = []
    non_renumbered_dest_counts: Counter[str] = Counter()

    # 8) First pass: plan destination names for every file.
    #    - Renumber run_logs/log*.csv across experiments.
    #    - Renumber spraytec/spraytec*.csv across experiments.
    #    - Track non-renumbered destination collisions.
    for source_folder, _, _ in experiments:
        source_folder_name = source_folder.name

        for source_path in sorted(source_folder.rglob("*")):
            if source_path.is_dir():
                continue

            rel_path = source_path.relative_to(source_folder)
            parts = rel_path.parts
            destination_path: Path

            in_run_logs = len(parts) >= 2 and parts[0] == "run_logs"
            run_log_match = re.match(
                r"^log\d+(.*)$", source_path.stem, flags=re.IGNORECASE)

            in_spraytec = len(parts) >= 2 and parts[0] == "spraytec"
            spraytec_match = re.match(
                r"^spraytec\d+(.*)$", source_path.stem, flags=re.IGNORECASE)

            if in_run_logs and run_log_match:
                tail = run_log_match.group(1)
                new_name = f"log{run_log_counter}{tail}{source_path.suffix}"
                destination_path = Path("run_logs") / new_name
                run_log_counter += 1
                needs_conflict_suffix = False
                conflict_key = ""
            elif in_spraytec and spraytec_match:
                tail = spraytec_match.group(1)
                new_name = f"spraytec{spraytec_counter}{tail}{source_path.suffix}"
                destination_path = Path("spraytec") / new_name
                spraytec_counter += 1
                needs_conflict_suffix = False
                conflict_key = ""
            else:
                destination_path = rel_path
                conflict_key = str(destination_path).lower()
                non_renumbered_dest_counts[conflict_key] += 1
                needs_conflict_suffix = True

            planned_files.append(
                (
                    source_path,
                    destination_path,
                    source_folder_name,
                    needs_conflict_suffix,
                    conflict_key,
                )
            )

    # 9) Second pass: apply conflict renaming and copy files.
    #    If multiple files map to the same non-renumbered path,
    #    each gets a source-folder suffix.
    for source_path, destination_path_rel, source_folder_name, needs_conflict_suffix, conflict_key in planned_files:
        final_rel_path = destination_path_rel

        if needs_conflict_suffix and non_renumbered_dest_counts[conflict_key] > 1:
            renamed_on_collision += 1
            previous_rel_path = final_rel_path
            final_rel_path = final_rel_path.with_name(
                f"{final_rel_path.stem}_{source_folder_name}{final_rel_path.suffix}"
            )
            collision_renames.append((previous_rel_path, final_rel_path))

        destination_path = target_folder / final_rel_path
        disambiguation_counter = 2
        while destination_path.exists():
            destination_path = (target_folder / final_rel_path).with_name(
                f"{final_rel_path.stem}_{disambiguation_counter}{final_rel_path.suffix}"
            )
            disambiguation_counter += 1

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        copied_files += 1

    # 10) Print merge summary and detailed collision rename report.
    print(f"Created merged folder: {target_folder}")
    print(f"Copied {copied_files} files.")
    print(
        "Renumbered run logs and spraytec files in chronological experiment order "
        f"(final counters: log{run_log_counter-1}, spraytec{spraytec_counter-1})."
    )
    print(f"Renamed {renamed_on_collision} file(s) due to name collisions.")
    if collision_renames:
        print("Collision rename list:")
        for old_rel, new_rel in collision_renames:
            print(f"  - {old_rel} -> {new_rel}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
