import os
import shutil
import tkinter  as tk
from tkinter import filedialog

#CREDITS NAAR CLAUDE AI
#I combined some of the merge_experiments with claude suggestions
#I do take responsibility for the final code

def move_small_files(
    source_dir: str,
    output_dir: str = "small_files",
    threshold_kb: float = 10,
    dry_run: bool = False,
    recursive: bool = False,
):
    """
    Move files smaller than threshold_kb into small_files folder.

    Args:
        source_dir:    Folder to scan for files.
        output_dir:    Destination folder for small files (created if needed).
        threshold_kb:  Files strictly below this size (in KB) are moved.
        dry_run:       If True, only print what would happen — no files are moved.
        recursive:     If True, scan subdirectories as well.
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
        # Skip the output folder itself to avoid moving files twice
        if os.path.abspath(dirpath) == output_dir:
            continue

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)

            if not os.path.isfile(filepath):
                continue

            size_bytes = os.path.getsize(filepath)

            if size_bytes < threshold_bytes:
                dest = os.path.join(output_dir, filename)

                # Avoid overwriting a file with the same name
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
    root.withdraw()  # hide the empty tkinter window

    source_dir = filedialog.askdirectory(title="Select the folder to scan")

    #looping through y-folders in selected folder for spraytec folders and moving small files to small_files folder in spraytec folder
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
            dry_run=False,
            recursive=False,
        )