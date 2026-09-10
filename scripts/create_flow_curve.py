import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tcm_utils.cough_model import CoughModel


def generate_flow_curve_csv(
        cough_model: "CoughModel",
        pressure_bar: float,
        output_csv_path: str):

    raise NotImplementedError("This function is not implemented yet.")

    # STEPS TO BE IMPLEMENTED

    # Generate flow curve data from the cough model

    # Read out proportional valve calibration file

    # Figure out which pressure is necessary to achieve the target flow rate

    # Convert to proportional valve current

    # Save to CSV

    # Return pressure setting and path to CSV file


def _is_multiple_of(value: float, step: float, tol: float = 1e-9) -> bool:
    remainder = value % step
    return remainder < tol or abs(remainder - step) < tol


def _validate_max_curve_rows(row_count: int, max_rows: int = 2000) -> None:
    """Raise if a generated flow-curve would exceed the allowed row count."""
    if row_count > max_rows:
        raise ValueError(
            f"Generated curve has {row_count} rows, which exceeds the "
            f"maximum allowed {max_rows} rows."
        )


def _default_step_curve_output_path(
    *,
    step_current_ma: float,
    step_duration_ms: float,
    default_subfolder: str | Path | None = None,
) -> Path:
    base_flow_curves_dir = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "tcm_control"
        / "flow_curves"
    )
    if default_subfolder is None:
        flow_curves_dir = base_flow_curves_dir
    else:
        candidate_dir = (base_flow_curves_dir /
                         Path(default_subfolder)).resolve()
        base_resolved = base_flow_curves_dir.resolve()
        if not candidate_dir.is_relative_to(base_resolved):
            raise ValueError(
                "default_subfolder must stay within the default flow_curves directory"
            )
        flow_curves_dir = candidate_dir

    rounded_current = round(step_current_ma, 1)
    rounded_duration_ms = int(round(step_duration_ms))
    current_label = f"{rounded_current:.1f}".replace(".", "-")
    filename = f"step_{current_label}mA_{rounded_duration_ms}ms.csv"
    return flow_curves_dir / filename


def generate_step_curve_csv(
    output_csv_path: str | Path | None = None,
    *,
    default_subfolder: str | Path | None = None,
    step_current_ma: float,
    closed_current_ma: float = 12.0,
    step_duration_ms: float = 300.0,
    pre_record_ms: float = 100.0,
    post_record_ms: float = 100.0,
    solenoid_lead_ms: float = 20.0,
    solenoid_lag_ms: float = 20.0,
    polling_interval_ms: float = 1.0,
    trigger_at_start: bool = True,
) -> Path:
    """Generate a single-step flow-curve CSV with fixed sampling interval.

    The generated curve has this timeline:
    1) Both valves closed for ``pre_record_ms``.
    2) Solenoid opens ``solenoid_lead_ms`` before proportional valve step.
    3) Proportional valve is at ``step_current_ma`` for ``step_duration_ms``.
    4) Solenoid stays open for ``solenoid_lag_ms`` after prop valve closes.
    5) Both valves closed for ``post_record_ms``.

    If ``output_csv_path`` is not provided, a filename is generated from
    rounded step current and step duration, e.g. ``step_20-0mA_800ms.csv``.
    Use ``default_subfolder`` to place this file under a subfolder of the
    default ``flow_curves`` directory.
    """
    if polling_interval_ms <= 0:
        raise ValueError("polling_interval_ms must be > 0")

    durations = {
        "step_duration_ms": step_duration_ms,
        "pre_record_ms": pre_record_ms,
        "post_record_ms": post_record_ms,
        "solenoid_lead_ms": solenoid_lead_ms,
        "solenoid_lag_ms": solenoid_lag_ms,
    }
    for name, value in durations.items():
        if value < 0:
            raise ValueError(f"{name} must be >= 0")
        if not _is_multiple_of(float(value), float(polling_interval_ms)):
            raise ValueError(
                f"{name} ({value} ms) must be a multiple of polling_interval_ms "
                f"({polling_interval_ms} ms)"
            )

    solenoid_open_ms = pre_record_ms
    prop_open_ms = solenoid_open_ms + solenoid_lead_ms
    prop_close_ms = prop_open_ms + step_duration_ms
    solenoid_close_ms = prop_close_ms + solenoid_lag_ms
    total_duration_ms = solenoid_close_ms + post_record_ms

    total_steps = int(round(total_duration_ms / polling_interval_ms))
    row_times = [round(step * polling_interval_ms, 9)
                 for step in range(total_steps + 1)]
    _validate_max_curve_rows(len(row_times))

    rows: list[tuple[float, float, int, int]] = []

    for idx, time_ms in enumerate(row_times):
        prop_open = prop_open_ms <= time_ms < prop_close_ms
        solenoid_open = solenoid_open_ms <= time_ms < solenoid_close_ms

        prop_current_ma = step_current_ma if prop_open else closed_current_ma
        trig = 1 if trigger_at_start and idx == 0 else 0

        rows.append((time_ms, prop_current_ma, int(solenoid_open), trig))

    if output_csv_path is None:
        output_path = _default_step_curve_output_path(
            step_current_ma=step_current_ma,
            step_duration_ms=step_duration_ms,
            default_subfolder=default_subfolder,
        )
    else:
        output_path = Path(output_csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_ms", "prop_valve_ma", "sol_valve", "trig"])
        writer.writerows(rows)

    return output_path


def main() -> None:
    generated = generate_step_curve_csv(
        default_subfolder="piv",
        step_current_ma=13.0,
        closed_current_ma=12.0,
        step_duration_ms=89,
        pre_record_ms=15,
        post_record_ms=16,
        solenoid_lead_ms=5,
        solenoid_lag_ms=0,
        polling_interval_ms=1,
        trigger_at_start=True,
    )
    print(f"Step curve written to {generated}")


if __name__ == "__main__":
    main()
