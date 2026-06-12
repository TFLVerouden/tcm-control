import os
import shutil
import tkinter as tk
from tkinter import filedialog

import pandas as pd
from pathlib import Path


#CREDITS NAAR CLAUDE AI
#I combined some of the merge_experiments with claude suggestions
#I do take responsibility for the final code

def _first_existing(candidates: list[str], available_columns: list[str]) -> str | None:
    normalized_to_original = {
        str(col).strip().lower(): str(col) for col in available_columns
    }
    for candidate in candidates:
        resolved = normalized_to_original.get(candidate.strip().lower())
        if resolved is not None:
            return resolved
    return None

def move_small_files(
    source_dir: str,
    output_dir: str = "small_files",
    threshold_kb: float = 10,
    dry_run: bool = False,
    recursive: bool = False,
    fix_headers: bool = False,
):
    """
    Move files smaller than threshold_kb into small_files folder.
    Optionally prepend headers from small files to the next headerless file.

    Args:
        source_dir:    Folder to scan for files.
        output_dir:    Destination folder for small files (created if needed).
        threshold_kb:  Files strictly below this size (in KB) are moved.
        dry_run:       If True, only print what would happen — no files are moved.
        recursive:     If True, scan subdirectories as well.
        fix_headers:   If True, prepend headers from small files to the next headerless CSV.
    """
    source_dir = os.path.abspath(source_dir)
    output_dir = os.path.abspath(output_dir)
    threshold_bytes = threshold_kb * 1024

    if not os.path.isdir(source_dir):
        raise NotADirectoryError(f"Source not found: {source_dir}")

    if not dry_run:
        os.makedirs(output_dir, exist_ok=True)

    moved, skipped = 0, 0

    walker = os.walk(source_dir) if recursive else [(source_dir, [], os.listdir(source_dir))]

    for dirpath, _, filenames in walker:
        if os.path.abspath(dirpath) == output_dir:
            continue

        # Sort so run order is preserved when fixing headers
        csv_files = sorted([
            f for f in filenames
            if f.lower().endswith(".csv") and
            os.path.isfile(os.path.join(dirpath, f))
        ])

        for i, filename in enumerate(csv_files):
            filepath = os.path.join(dirpath, filename)
            size_bytes = os.path.getsize(filepath)

            if size_bytes < threshold_bytes:

                # --- Header fix: prepend headers to next file if needed ---
              if fix_headers and i + 1 < len(csv_files):
                next_filepath = os.path.join(dirpath, csv_files[i + 1])
                try:
                    next_df = pd.read_csv(next_filepath)
                    trigger_col = _first_existing(["Trigger", "trigger"], list(next_df.columns))

                    if trigger_col is None:
                        print(f"  No trigger column found in {csv_files[i+1]}, skipping fix.")
                    else:
                        print(f"{'[DRY RUN] ' if dry_run else ''}Setting trigger in first row of: {csv_files[i+1]}")
                        if not dry_run:
                            next_df.at[next_df.index[0], trigger_col] = 1
                            next_df.to_csv(next_filepath, index=False)
                            print(f"  Fixed trigger in: {csv_files[i+1]}")

                except Exception as exc:
                    print(f"  Could not fix trigger in {csv_files[i+1]}: {exc}")
                # --- Move small file ---
                dest = os.path.join(output_dir, filename)
                if os.path.exists(dest):
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(dest):
                        dest = os.path.join(output_dir, f"{base}_{counter}{ext}")
                        counter += 1

                size_kb = size_bytes / 1024
                print(f"{'[DRY RUN] ' if dry_run else ''}Moving: {filename} ({size_kb:.1f} KB) → {dest}")

                if not dry_run:
                    shutil.move(filepath, dest)
                moved += 1
            else:
                skipped += 1

        # Handle non-CSV files
        for filename in filenames:
            if filename.lower().endswith(".csv"):
                continue
            filepath = os.path.join(dirpath, filename)
            if not os.path.isfile(filepath):
                continue
            size_bytes = os.path.getsize(filepath)
            if size_bytes < threshold_bytes:
                dest = os.path.join(output_dir, filename)
                if os.path.exists(dest):
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(dest):
                        dest = os.path.join(output_dir, f"{base}_{counter}{ext}")
                        counter += 1
                size_kb = size_bytes / 1024
                print(f"{'[DRY RUN] ' if dry_run else ''}Moving: {filename} ({size_kb:.1f} KB) → {dest}")
                if not dry_run:
                    shutil.move(filepath, dest)
                moved += 1
            else:
                skipped += 1

    print(f"\nDone. {'Would move' if dry_run else 'Moved'}: {moved} file(s) | Skipped (≥{threshold_kb} KB): {skipped}")


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    source_dir = filedialog.askdirectory(title="Select the folder to scan")

    if source_dir:
        for height in os.scandir(source_dir):
            if not height.is_dir():
                continue

            spraytec_dir = os.path.join(height.path, "spraytec")

            if not os.path.isdir(spraytec_dir):
                print(f"No spraytec folder found in: {height.name}, skipping.")
                continue

            move_small_files(
                source_dir=spraytec_dir,
                output_dir=os.path.join(spraytec_dir, "small_files"),
                threshold_kb=1000,
                dry_run=True,    # ← set to False when ready
                recursive=False,
                fix_headers=True,  # ← enables header fixing
            )