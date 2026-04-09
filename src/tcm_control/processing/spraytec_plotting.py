from __future__ import annotations

"""SprayTec plotting and distribution averaging helpers."""

from pathlib import Path
from typing import Any

import pandas as pd

from tcm_control.processing.common import get_processed_dir

__all__ = ["time_average_distribution"]


def _build_time_interval_labels(
    start_time_ms: int | None,
    end_time_ms: int | None,
) -> tuple[str, str]:
    """Return (human label, filename-safe label) using whole milliseconds."""
    start_ms_int = None if start_time_ms is None else int(start_time_ms)
    end_ms_int = None if end_time_ms is None else int(end_time_ms)

    if start_ms_int is None and end_ms_int is None:
        return "all time", "all_time"

    if start_ms_int is not None and end_ms_int is not None:
        return (
            f"{start_ms_int}ms to {end_ms_int}ms",
            f"t_{start_ms_int}_to_{end_ms_int}ms",
        )

    if start_ms_int is not None:
        return (
            f"from {start_ms_int}ms",
            f"t_from_{start_ms_int}ms",
        )

    return (
        f"until {end_ms_int}ms",
        f"t_until_{end_ms_int}ms",
    )


def time_average_distribution(
    spraytec_data: dict[str, Any],
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    time_column: str = "Date-Time",
    trigger_column: str = "Trigger",
    export_csv: bool = True,
    csv_filename: str | None = None,
    plot: bool = False,
    ax: Any | None = None,
    export_pdf: bool = False,
    pdf_filename: str | None = None,
    output_dir: str | Path | None = None,
    **plot_kwargs: Any,
) -> pd.Series:
    """Compute a time-averaged distribution, with optional export and plotting.

    Plot kwargs are forwarded to matplotlib's ax.plot(...).
    """
    measurement_df = spraytec_data["measurement_df"]
    bin_edges_um = spraytec_data["bin_edges_um"]

    if len(bin_edges_um) < 2:
        raise ValueError(
            "No valid bin edges found; cannot compute time average distribution.")

    def _is_close_to_any_edge(value: float) -> bool:
        for edge in bin_edges_um:
            tolerance = max(1e-6, 1e-3 * max(abs(edge), abs(value)))
            if abs(value - edge) <= tolerance:
                return True
        return False

    parsed_bin_columns: list[tuple[Any, float]] = []
    for column in measurement_df.columns:
        try:
            parsed = float(str(column).strip())
        except (TypeError, ValueError):
            continue
        if parsed <= 0:
            continue
        if _is_close_to_any_edge(parsed):
            parsed_bin_columns.append((column, parsed))

    # Fallback for unusual files where edge matching fails completely.
    if not parsed_bin_columns:
        for column in measurement_df.columns:
            try:
                parsed = float(str(column).strip())
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                parsed_bin_columns.append((column, parsed))

    bin_columns = [column for column, _ in parsed_bin_columns]
    bin_column_values = [value for _, value in parsed_bin_columns]

    if not bin_columns:
        raise ValueError(
            "No bin distribution columns found in measurement_df.")

    source_path = Path(spraytec_data["file_path"])
    print(
        "SprayTec debug: "
        f"{source_path.name} -> bin_edges={len(bin_edges_um)}, "
        f"bin_columns={len(bin_columns)}, rows_total={len(measurement_df)}"
    )

    start_ms_int = None if start_time_ms is None else int(start_time_ms)
    end_ms_int = None if end_time_ms is None else int(end_time_ms)
    if start_ms_int is not None and end_ms_int is not None and end_ms_int < start_ms_int:
        raise ValueError(
            f"Invalid time window: start_time_ms={start_ms_int}, end_time_ms={end_ms_int}"
        )

    filter_start_s = None if start_ms_int is None else start_ms_int / 1000.0
    filter_end_s = None if end_ms_int is None else end_ms_int / 1000.0

    def _normalize_column_name(name: Any) -> str:
        return str(name).strip().lower()

    def _resolve_column_name(preferred_name: str) -> Any | None:
        columns = list(working_df.columns)
        preferred_stripped = preferred_name.strip()
        preferred_norm = preferred_stripped.lower()
        preferred_compact = "".join(preferred_norm.split())

        for column in columns:
            if str(column).strip() == preferred_stripped:
                return column
        for column in columns:
            if _normalize_column_name(column) == preferred_norm:
                return column
        for column in columns:
            compact = "".join(_normalize_column_name(column).split())
            if compact == preferred_compact:
                return column
        return None

    working_df = measurement_df
    if filter_start_s is not None or filter_end_s is not None:
        rows_before_filter = len(working_df)
        resolved_time_column = _resolve_column_name(time_column)
        if resolved_time_column is None:
            # Fallback: pick an obvious time-like column if present.
            candidates = [
                column
                for column in working_df.columns
                if "time" in _normalize_column_name(column)
            ]
            if len(candidates) == 1:
                resolved_time_column = candidates[0]
            elif len(candidates) > 1:
                preferred_candidates = [
                    column
                    for column in candidates
                    if any(
                        token in _normalize_column_name(column)
                        for token in ("[s]", "(s)", "[ms]", "(ms)")
                    )
                ]
                if len(preferred_candidates) == 1:
                    resolved_time_column = preferred_candidates[0]

        if resolved_time_column is None:
            available_columns = ", ".join(map(str, working_df.columns))
            raise ValueError(
                "Time filtering requested, but no matching time column was found. "
                f"Requested: '{time_column}'. Available columns: {available_columns}"
            )

        resolved_trigger_column = _resolve_column_name(trigger_column)
        if resolved_trigger_column is None:
            available_columns = ", ".join(map(str, working_df.columns))
            raise ValueError(
                "Trigger-relative filtering requires a trigger column, but none was found. "
                f"Requested: '{trigger_column}'. Available columns: {available_columns}"
            )

        # Hardcoded SprayTec timestamp format, e.g. "18 Mar 2026 12:21:25.0744".
        parsed_time = pd.to_datetime(
            working_df[resolved_time_column].astype(str).str.strip(),
            format="%d %b %Y %H:%M:%S.%f",
            errors="coerce",
        )
        if parsed_time.isna().all():
            raise ValueError(
                "Failed to parse Date-Time values using format "
                "'%d %b %Y %H:%M:%S.%f'."
            )
        first_time = parsed_time.dropna().iloc[0]
        time_values = (parsed_time - first_time).dt.total_seconds()

        trigger_values = pd.to_numeric(
            working_df[resolved_trigger_column], errors="coerce").fillna(0.0)
        trigger_mask = trigger_values > 0
        if not trigger_mask.any():
            raise ValueError(
                f"No trigger event found in column: {resolved_trigger_column}"
            )
        t0_time_s = float(time_values[trigger_mask].iloc[0])
        time_values = time_values - t0_time_s

        mask = pd.Series(True, index=working_df.index)
        if filter_start_s is not None:
            mask &= time_values >= float(filter_start_s)
        if filter_end_s is not None:
            mask &= time_values <= float(filter_end_s)
        working_df = working_df[mask]

        rows_after_filter = len(working_df)
        print(
            "SprayTec debug: "
            f"{source_path.name} -> interval=[{start_ms_int}, {end_ms_int}] ms, "
            f"trigger_t0={t0_time_s * 1000.0:.1f} ms (relative to first timestamp), "
            f"rows_kept={rows_after_filter}/{rows_before_filter}"
        )

    if working_df.empty:
        raise ValueError("No rows left after applying time range filter.")

    dist_df = working_df[bin_columns].apply(pd.to_numeric, errors="coerce")
    averaged = pd.Series(dist_df.mean(axis=0, skipna=True))

    centers = [
        (bin_edges_um[idx - 1] + bin_edges_um[idx]) / 2.0
        for idx in range(1, len(bin_edges_um))
    ]

    if len(centers) == len(averaged.index):
        averaged.index = centers
        averaged.index.name = "bin_edge_um"

    interval_title, interval_filename = _build_time_interval_labels(
        start_time_ms=start_ms_int,
        end_time_ms=end_ms_int,
    )

    if output_dir is None:
        output_path = get_processed_dir(source_path.parent)
    else:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

    if export_csv:
        resolved_csv_filename = (
            csv_filename
            if csv_filename is not None
            else f"{source_path.stem}_time_average_{interval_filename}.csv"
        )
        csv_path = output_path / resolved_csv_filename
        export_df = averaged.rename(
            f"mean_distribution ({interval_title})").to_frame()
        if export_df.index.name is None:
            export_df.index.name = "bin_center_um"
        export_df.to_csv(csv_path)

    if plot or export_pdf or ax is not None:
        import matplotlib.pyplot as plt
        from tcm_utils.plot_style import plot_binned_area

        if ax is None:
            _, ax = plt.subplots(figsize=(7, 4))

        y_values = pd.to_numeric(averaged, errors="coerce")
        x_centers = list(bin_column_values)
        y_array = y_values.to_numpy(dtype=float)
        if len(x_centers) == len(y_array) and any(
            x_centers[idx] > x_centers[idx + 1] for idx in range(len(x_centers) - 1)
        ):
            order = sorted(range(len(x_centers)),
                           key=lambda idx: x_centers[idx])
            x_centers = [x_centers[idx] for idx in order]
            y_array = y_array[order]

        if len(x_centers) == len(y_array) + 1:
            x_edges = x_centers
        elif len(x_centers) == len(y_array):
            left_edge: float
            first_center = float(x_centers[0])
            sorted_edges = sorted(float(edge) for edge in bin_edges_um)
            previous_edges = [
                edge for edge in sorted_edges if edge < first_center]
            if previous_edges:
                left_edge = previous_edges[-1]
            elif len(x_centers) > 1 and x_centers[0] > 0 and x_centers[1] > 0:
                left_edge = float(x_centers[0] ** 2 / x_centers[1])
            elif len(x_centers) > 1:
                left_edge = float(x_centers[0] - (x_centers[1] - x_centers[0]))
            else:
                left_edge = float(x_centers[0] * 0.9)

            x_edges = [left_edge, *x_centers]
        else:
            bin_col_labels = [str(column).strip() for column in bin_columns]
            edge_labels = [f"{float(edge):g}" for edge in bin_edges_um]
            edge_set = set(edge_labels)
            missing_edge_columns = [
                label for label in edge_labels if label not in bin_col_labels
            ]
            extra_bin_columns = [
                label for label in bin_col_labels if label not in edge_set
            ]
            print("SprayTec debug: sanity check failed while plotting")
            print(f"SprayTec debug: file={source_path}")
            print(
                "SprayTec debug: "
                f"len(bin_column_values)={len(bin_column_values)}, len(y_values)={len(y_values)}, "
                f"len(bin_columns)={len(bin_columns)}"
            )
            print(
                "SprayTec debug: "
                f"first 8 edge labels={edge_labels[:8]}, last 8 edge labels={edge_labels[-8:]}"
            )
            print(
                "SprayTec debug: "
                f"first 8 bin column labels={bin_col_labels[:8]}, last 8 bin column labels={bin_col_labels[-8:]}"
            )
            print(
                "SprayTec debug: "
                f"first 8 parsed bin values={bin_column_values[:8]}, "
                f"last 8 parsed bin values={bin_column_values[-8:]}"
            )
            print(
                "SprayTec debug: "
                f"missing edge columns count={len(missing_edge_columns)}, "
                f"sample={missing_edge_columns[:10]}"
            )
            print(
                "SprayTec debug: "
                f"extra bin columns count={len(extra_bin_columns)}, "
                f"sample={extra_bin_columns[:10]}"
            )
            raise ValueError(
                "Cannot plot with bin edges from available columns: expected len(edges)==len(distribution)+1 "
                f"or len(centers)==len(distribution), got {len(bin_column_values)} bin x-values "
                f"and {len(y_values)} bins."
            )

        # Draw distribution as contiguous binned bars from explicit bin edges.
        plot_binned_area(
            ax,
            x_edges,
            y_array,
            x_mode="edges",
            **plot_kwargs,
        )
        ax.set_xscale("log")
        ax.set_xlabel("Particle size (μm)")
        ax.set_ylabel("Mean distribution")
        ax.set_title(f"SprayTec time-averaged distribution ({interval_title})")
        ax.grid(True, alpha=0.3)

        if export_pdf:
            resolved_pdf_filename = (
                pdf_filename
                if pdf_filename is not None
                else f"{source_path.stem}_time_average_{interval_filename}.pdf"
            )
            pdf_path = output_path / resolved_pdf_filename
            ax.figure.tight_layout()
            ax.figure.savefig(pdf_path, bbox_inches="tight")

    return averaged
