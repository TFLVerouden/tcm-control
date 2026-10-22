from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# This script assumes an editable install. Install once from repo root: `pip install -e .`

from tcm_utils.file_dialogs import ask_directory
from tcm_utils.io_utils import prompt_input, prompt_yes_no


METADATA_GLOB = "*metadata.json"
INVALID_FOLDER_CHARS = re.compile(r"[<>:\"/\\|?*\x00]")


def is_valid_folder_name(name: str) -> tuple[bool, str | None]:
    """Validate folder name using conservative cross-platform rules."""
    if name == "":
        return False, "Folder name cannot be empty."
    if name in {".", ".."}:
        return False, "Folder name cannot be '.' or '..'."
    if INVALID_FOLDER_CHARS.search(name):
        return False, (
            "Folder name contains invalid characters. Avoid any of: "
            "<>:\"/\\|?*"
        )
    if name.endswith(" ") or name.endswith("."):
        return False, "Folder name cannot end with a space or dot."
    return True, None


def _replace_path_segment(path_text: str, old_name: str, new_name: str) -> str:
    """Replace one path segment name while preserving separators."""
    pattern = re.compile(rf"(^|[\\/]){re.escape(old_name)}(?=([\\/]|$))")
    return pattern.sub(rf"\g<1>{new_name}", path_text)


def _find_string_occurrences(payload: Any, needle: str, prefix: str = "") -> list[str]:
    """Collect JSON paths where a string contains ``needle``."""
    hits: list[str] = []

    if isinstance(payload, dict):
        for key, value in payload.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            hits.extend(_find_string_occurrences(value, needle, child_prefix))
        return hits

    if isinstance(payload, list):
        for idx, value in enumerate(payload):
            child_prefix = f"{prefix}[{idx}]"
            hits.extend(_find_string_occurrences(value, needle, child_prefix))
        return hits

    if isinstance(payload, str) and needle in payload:
        hits.append(prefix or "<root>")

    return hits


def update_metadata_output_dir(
        metadata_path: Path,
        *,
        old_folder_name: str,
        new_folder_name: str,
) -> tuple[bool, list[str]]:
    """Update ``experiment.output_dir`` and return changed flag + unexpected hits."""
    with metadata_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    changed = False
    experiment_dict: dict[str, Any] | None = (
        payload.get("experiment") if isinstance(payload, dict) else None
    )
    output_dir = (
        experiment_dict.get("output_dir")
        if isinstance(experiment_dict, dict)
        else None
    )

    if isinstance(experiment_dict, dict) and isinstance(output_dir, str):
        updated_output_dir = _replace_path_segment(
            output_dir,
            old_name=old_folder_name,
            new_name=new_folder_name,
        )
        if updated_output_dir != output_dir:
            experiment_dict["output_dir"] = updated_output_dir
            changed = True

    if changed:
        with metadata_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

    all_hits = _find_string_occurrences(payload, old_folder_name)
    expected_field = "experiment.output_dir"
    unexpected_hits = [hit for hit in all_hits if hit != expected_field]

    return changed, unexpected_hits


def _replace_folder_name_in_payload_strings(
        payload: Any,
        *,
        old_folder_name: str,
        new_folder_name: str,
) -> tuple[Any, int]:
    """Recursively replace folder name in all string values."""
    if isinstance(payload, dict):
        total_replacements = 0
        updated_dict: dict[str, Any] = {}
        for key, value in payload.items():
            updated_value, replacements = _replace_folder_name_in_payload_strings(
                value,
                old_folder_name=old_folder_name,
                new_folder_name=new_folder_name,
            )
            updated_dict[key] = updated_value
            total_replacements += replacements
        return updated_dict, total_replacements

    if isinstance(payload, list):
        total_replacements = 0
        updated_list: list[Any] = []
        for value in payload:
            updated_value, replacements = _replace_folder_name_in_payload_strings(
                value,
                old_folder_name=old_folder_name,
                new_folder_name=new_folder_name,
            )
            updated_list.append(updated_value)
            total_replacements += replacements
        return updated_list, total_replacements

    if isinstance(payload, str):
        updated = _replace_path_segment(
            payload,
            old_name=old_folder_name,
            new_name=new_folder_name,
        )
        if updated != payload:
            return updated, 1

    return payload, 0


def update_additional_folder_references(
        metadata_path: Path,
        *,
        old_folder_name: str,
        new_folder_name: str,
) -> int:
    """Update all remaining folder-name references in one metadata JSON file."""
    with metadata_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    updated_payload, replacements = _replace_folder_name_in_payload_strings(
        payload,
        old_folder_name=old_folder_name,
        new_folder_name=new_folder_name,
    )
    if replacements > 0:
        with metadata_path.open("w", encoding="utf-8") as fh:
            json.dump(updated_payload, fh, indent=2)

    return replacements


def main() -> int:
    selected = ask_directory(
        key="rename_experiment_folder_selected_dir",
        title="Select experiment folder to rename",
        start=Path(__file__).resolve().parent,
    )
    if not selected:
        print("No folder selected.")
        return 1

    source_folder = Path(selected).expanduser().resolve()
    if not source_folder.exists() or not source_folder.is_dir():
        raise FileNotFoundError(
            f"Selected folder does not exist: {source_folder}")

    suggested_name = source_folder.name
    while True:
        new_name = prompt_input(
            f"Enter new folder name [{suggested_name}]: ",
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

        if candidate_name == source_folder.name:
            print("New folder name is the same as the current name. Nothing to do.")
            return 0

        target_folder = source_folder.with_name(candidate_name)
        if target_folder.exists():
            print(f"Target folder already exists: {target_folder}")
            continue

        break

    confirm = prompt_yes_no(
        (
            f"Rename folder '{source_folder.name}' to '{target_folder.name}' "
            "and update metadata JSON files? (press ENTER to rename, type 'n' to cancel)"
        ),
        default=True,
    )
    if not confirm:
        print("Cancelled by user.")
        return 1

    source_folder.rename(target_folder)
    print(f"Renamed folder:\n  from: {source_folder}\n  to:   {target_folder}")

    metadata_paths = sorted(target_folder.rglob(METADATA_GLOB))
    if not metadata_paths:
        print("No metadata JSON files found. Rename complete.")
        return 0

    changed_count = 0
    unexpected_occurrences: dict[Path, list[str]] = {}

    for metadata_path in metadata_paths:
        changed, unexpected_hits = update_metadata_output_dir(
            metadata_path,
            old_folder_name=source_folder.name,
            new_folder_name=target_folder.name,
        )
        if changed:
            changed_count += 1
        if unexpected_hits:
            unexpected_occurrences[metadata_path] = unexpected_hits

    print(
        f"Checked {len(metadata_paths)} metadata JSON file(s); "
        f"updated {changed_count} file(s)."
    )

    if unexpected_occurrences:
        print("Found old folder name in additional JSON fields:")
        for path, json_paths in unexpected_occurrences.items():
            locations = ", ".join(json_paths)
            print(f"  - {path}: {locations}")

        update_additional = prompt_yes_no(
            (
                "Also update these additional JSON field references now? "
                "(press ENTER to update, type 'n' to skip)"
            ),
            default=True,
        )
        if update_additional:
            updated_files = 0
            updated_references = 0
            for metadata_path in unexpected_occurrences:
                replacements = update_additional_folder_references(
                    metadata_path,
                    old_folder_name=source_folder.name,
                    new_folder_name=target_folder.name,
                )
                if replacements > 0:
                    updated_files += 1
                    updated_references += replacements

            print(
                "Updated additional references in "
                f"{updated_files} metadata JSON file(s) "
                f"({updated_references} replacement(s))."
            )
        else:
            print("Skipped updating additional JSON references.")
    else:
        print("No old folder-name references found outside experiment.output_dir.")

    # Final confirmation that the new folder name still passes validation.
    valid, message = is_valid_folder_name(target_folder.name)
    if valid:
        print(f"Final folder name validation passed: '{target_folder.name}'")
    else:
        print(f"Final folder name validation warning: {message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
