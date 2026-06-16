"""
pool_all_coordinates.py
 
Pools averaged SprayTec number distributions across all main coordinates
(merged_Xmm folders) and all their subcoordinates (height folders), applying
per-subcoordinate weights by folder name, to produce one overall pooled
distribution.
 
Folder structure expected:
    parent_dir/
        merged_X1mm/
            <height_folder>/          e.g. "z=0mm", "z=10mm"
                processed/
                    run01_..._cv200.csv
                    run02_..._cv200.csv
                    ...
        merged_X2mm/
            <height_folder>/
                processed/
                    ...
        ...
"""
 
from __future__ import annotations
 
import re
from pathlib import Path
 
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
 
from tcm_utils.file_dialogs import ask_directory
from tcm_utils.plot_style import (
    append_unit_to_last_ticklabel,
    plot_binned_area,
    use_tcm_poster_style,
)
 
# ----------------------------------------------------------------------
# Settings — edit these
# ----------------------------------------------------------------------
 
# Parent directory containing all merged_Xmm folders (None = folder dialog).
PARENT_DIR: str | None = None
 
# Time interval used when generating the averaged CSVs.
INTERVAL_MS = (0, 350)
 
# Mask mode used when generating the averaged CSVs.
# "cv"   -> matches files ending in ..._cv<CV_THRESHOLD>.csv
# "time" -> matches files ending in ..._time<INTERVAL_MS[0]>-<INTERVAL_MS[1]>ms.csv
# None   -> matches files ending in ...t_<start>_to_<end>ms.csv (no mask)
MASK_MODE: str | None = "cv"
CV_THRESHOLD = 5  # only used when MASK_MODE == "cv"
 
# Per-subcoordinate weights by folder name.
# Any folder not listed gets weight 1.0.
# Set to None to weight all subcoordinates equally.
SUBCOORDINATE_WEIGHTS: dict[str, float] | None = None
# Example:
# SUBCOORDINATE_WEIGHTS = {
#     "z=0mm":  1.0,
#     "z=10mm": 2.0,
#     "z=20mm": 1.5,
# }
 
PLOT_COLOR = "C0"
PLOT_ALPHA = 0.18
X_LIMITS: tuple[float, float] | None = None
Y_LIMITS: tuple[float, float] | None = (0, 50)
 
# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
 
def _build_interval_suffix() -> str:
    base = f"t_{INTERVAL_MS[0]}_to_{INTERVAL_MS[1]}ms"
    if MASK_MODE == "cv":
        return f"{base}_cv{int(CV_THRESHOLD)}.csv"
    elif MASK_MODE == "time":
        return f"{base}_time{INTERVAL_MS[0]}-{INTERVAL_MS[1]}ms.csv"
    else:
        return f"{base}.csv"
 
 
def _extract_main_coord(folder_name: str) -> int | None:
    """Extract coordinate value from folder names like 'merged_50mm'."""
    match = re.search(r"merged_(-?\d+)\s*mm", folder_name, re.IGNORECASE)
    return int(match.group(1)) if match else None
 
 
def _load_csv(csv_path: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """Load a single averaged distribution CSV into (x, y) arrays."""
    try:
        df = pd.read_csv(csv_path, index_col=0)
    except Exception as exc:
        print(f"  [warn] Could not read {csv_path.name}: {exc}")
        return None
 
    if df.empty:
        return None
 
    x = pd.to_numeric(pd.Series(df.index), errors="coerce").to_numpy()
    y = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy()
 
    valid = np.isfinite(x) & np.isfinite(y) & (x > 0)
    if not valid.any():
        return None
 
    return x[valid], y[valid]
 
 
# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
 
def main() -> int:
    if INTERVAL_MS[1] <= INTERVAL_MS[0]:
        raise ValueError(f"INTERVAL_MS invalid: {INTERVAL_MS}")
 
    if PARENT_DIR is None:
        selected = ask_directory(
            key="pool_all_coordinates_parent_dir",
            title="Select parent directory containing merged_Xmm folders",
            start=Path(__file__).resolve().parent,
        )
        if not selected:
            print("No parent directory selected.")
            return 1
        parent_dir = Path(selected).expanduser().resolve()
    else:
        parent_dir = Path(PARENT_DIR).expanduser().resolve()
 
    if not parent_dir.exists() or not parent_dir.is_dir():
        raise FileNotFoundError(f"Parent directory not found: {parent_dir}")
 
    interval_suffix = _build_interval_suffix()
    print(f"Looking for files ending in: {interval_suffix}")
 
    # --- find all merged_Xmm folders ---
    main_coord_dirs = sorted(
        p for p in parent_dir.iterdir()
        if p.is_dir() and re.search(r"merged_-?\d+\s*mm", p.name, re.IGNORECASE)
    )
    if not main_coord_dirs:
        print("No merged_Xmm folders found.")
        return 1
 
    print(f"\nFound {len(main_coord_dirs)} main coordinate folder(s):")
    for d in main_coord_dirs:
        print(f"  {d.name}")
 
    # --- collect weighted (x, y) arrays ---
    x_ref: np.ndarray | None = None
    y_stack: list[np.ndarray] = []
    weight_stack: list[float] = []
 
    total_coords = 0
    total_runs = 0
    skipped_runs = 0
 
    for main_dir in main_coord_dirs:
        print(f"\n{'='*60}")
        print(f"Main coordinate: {main_dir.name}")
 
        # Find subcoordinate (height) folders — exclude processed
        sub_dirs = sorted(
            p for p in main_dir.iterdir()
            if p.is_dir() and not p.name.lower().startswith("processed")
        )
 
        if not sub_dirs:
            print("  No subcoordinate folders found.")
            continue
 
        for sub_dir in sub_dirs:
            folder_name = sub_dir.name
            weight = 1.0
            if SUBCOORDINATE_WEIGHTS is not None:
                weight = SUBCOORDINATE_WEIGHTS.get(folder_name, 1.0)
 
            processed_dir = sub_dir / "processed"
            if not processed_dir.exists():
                print(f"  [{folder_name}] No processed/ folder found — skipped.")
                continue
 
            csv_paths = sorted(
                p for p in processed_dir.rglob("*.csv")
                if p.is_file() and p.name.endswith(interval_suffix)
            )
 
            if not csv_paths:
                print(f"  [{folder_name}] No matching CSVs found — skipped.")
                continue
 
            print(f"  [{folder_name}] weight={weight:.2f}, {len(csv_paths)} run(s)")
            total_coords += 1
 
            for csv_path in csv_paths:
                result = _load_csv(csv_path)
                if result is None:
                    print(f"    [warn] Could not load {csv_path.name} — skipped.")
                    skipped_runs += 1
                    continue
 
                x_values, y_values = result
 
                if x_ref is None:
                    x_ref = x_values
                elif not np.allclose(x_values, x_ref, rtol=1e-3):
                    print(f"    [warn] Bin edges differ in {csv_path.name} — skipped.")
                    skipped_runs += 1
                    continue
 
                y_stack.append(y_values)
                weight_stack.append(weight)
                total_runs += 1
 
    print(f"\nLoaded {total_runs} run(s) from {total_coords} subcoordinate(s).")
    if skipped_runs:
        print(f"Skipped {skipped_runs} run(s) due to missing data or bin mismatch.")
 
    if x_ref is None or not y_stack:
        print("No plottable data found.")
        return 1
 
    # --- pool: weighted sum across all runs, then renormalise ---
    weights = np.array(weight_stack)
    y_matrix = np.array(y_stack)                        # shape: (n_runs, n_bins)
    y_pooled = np.average(y_matrix, axis=0, weights=weights)
    total = y_pooled.sum()
    if total > 0:
        y_pooled = y_pooled / total * 100.0
 
    # --- plot ---
    use_tcm_poster_style()
    fig, ax = plt.subplots(figsize=(10, 4.5))
 
    plot_binned_area(
        ax, x_ref, y_pooled,
        x_mode="centers",
        color=PLOT_COLOR,
        alpha=PLOT_ALPHA,
        outline=True,
    )
 
    ax.set_xscale("log")
    if X_LIMITS is not None:
        ax.set_xlim(*X_LIMITS)
    if Y_LIMITS is not None:
        ax.set_ylim(*Y_LIMITS)
    ax.set_xlabel("Particle size")
    append_unit_to_last_ticklabel(ax, axis="x", unit="μm")
    ax.set_ylabel("Number distribution (%)")
    ax.set_title(
        f"Pooled distribution — all coordinates & heights "
        f"({INTERVAL_MS[0]} to {INTERVAL_MS[1]} ms)"
    )
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
 
    # --- save ---
    processed_dir = parent_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    output_pdf = processed_dir / f"pooled_all_coordinates_{interval_suffix.replace('.csv', '.pdf')}"
    fig.savefig(output_pdf, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved pooled distribution: {output_pdf}")
 
    return 0
 
 
if __name__ == "__main__":
    raise SystemExit(main())