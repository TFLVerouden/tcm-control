from pathlib import Path
import csv
from typing import Optional
from tcm_utils.file_dialogs import ask_open_file
from tcm_utils.plot_style import (
    use_tcm_poster_style,
    append_unit_to_last_ticklabel,
    add_label,
)
from tcm_utils.cvd_check import set_cvd_friendly_colors, get_color

import numpy as np
import matplotlib.pyplot as plt

from tcm_control.processing.common import get_processed_dir


def plot_run_log(
    run_log_path: Path | None = None,
    experiment_dir: Path | None = None,
    *,
    show: bool = True,
) -> Path | None:
    # If no path provided, ask the user to select a run log CSV file.
    if run_log_path is None:
        run_log_path = ask_open_file(
            key="plot_run_log_csv",
            title="Select run log CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
    if run_log_path is None:
        print("No file selected, aborting.")
        return None

    run_log_path = Path(run_log_path)

    # Read the run log and extract metadata and data columns
    (trigger_t0_us, run_nr, time_us, sol_valve_action, req_flow_lps,
     prop_valve_ma, press_bar) = _read_run_log(run_log_path)

    # Process the time column to be relative to the trigger time and convert to milliseconds
    time_ms = (time_us - trigger_t0_us) / 1000.0

    # Get the solenoid valve start and open times
    sol_open_start_ms = time_ms[sol_valve_action == 1][0]
    sol_open_end_ms = time_ms[sol_valve_action == 0][0]

    use_tcm_poster_style()
    set_cvd_friendly_colors()

    # Plot time on the x-axis, with vertical shading indicating the moments when the solenoid valve is open (sol_valve_action == 1) and a vertical line indicating the trigger time (time_ms == 0).
    # On the left y-axis, plot the pressure in bar, on the first right y-axis the proportional valve current in mA, and on the second right y-axis the required flowrate in L/s.
    fig, ax1 = plt.subplots(figsize=(10, 6))
    # ax1.set_xlabel("Time (ms)")
    ax1.set_ylabel("Pressure (bar)", color=get_color(0))
    ax1.plot(time_ms, press_bar, color=get_color(
        0), label="Pressure (bar)", linewidth=2)
    ax1.tick_params(axis="y", labelcolor=get_color(0))
    p_min = int(np.floor(np.min(press_bar)))
    p_max = int(np.ceil(np.max(press_bar)))
    # Avoid singular limits when all pressure values are exactly one integer.
    if p_min == p_max:
        p_max += 1
    ax1.set_ylim(bottom=p_min, top=p_max)

    ax3 = ax1.twinx()
    ax3.set_ylabel("Required flowrate (L/s)", color=get_color(2))
    ax3.plot(time_ms[req_flow_lps >= 0], req_flow_lps[req_flow_lps >= 0], color=get_color(
        2), label="Required flowrate (L/s)", linewidth=2)
    ax3.tick_params(axis="y", labelcolor=get_color(2))
    f_min = -0.5
    f_max = float(np.ceil(np.max(req_flow_lps)+0.1)+0.5)
    if f_min == f_max:
        f_max += 1.0
    ax3.set_ylim(bottom=f_min, top=f_max)

    ax2 = ax1.twinx()
    ax2.spines["right"].set_position(("outward", 72))
    ax2.set_ylabel("Proportional valve setpoint (mA)", color=get_color(1))
    ax2.plot(time_ms[prop_valve_ma > 0], prop_valve_ma[prop_valve_ma > 0], color=get_color(
        1), label="Proportional valve setpoint (mA)", linewidth=2)
    ax2.tick_params(axis="y", labelcolor=get_color(1))
    ax2.set_ylim(bottom=11.1, top=20.9)

    fig.subplots_adjust(right=0.82)

    # Add vertical shading for solenoid open times
    ax1.axvspan(sol_open_start_ms, sol_open_end_ms, linestyle="",
                color="#000000", alpha=0.2, label="Solenoid open")
    y_min, y_max = map(float, ax1.get_ylim())
    add_label(
        ax1,
        "< Solenoid valve open >",
        xy=((sol_open_start_ms + sol_open_end_ms) / 2.0,
            y_min + 0.02 * (y_max - y_min)),
        coord_system="data",
        ha="center",
        va="bottom",
        italic=False,
        color="#444444",
    )

    # Add vertical line for trigger time
    ax1.axvline(0, color="#000000", linestyle="--",
                linewidth=2, label="Trigger time")

    # Add legends
    # lines_labels = [ax.get_legend_handles_labels() for ax in [ax1, ax2]]
    # lines, labels = [sum(lol, []) for lol in zip(*lines_labels)]
    # ax1.legend(loc="upper right")

    append_unit_to_last_ticklabel(ax1, axis="x", unit="ms")
    plot_path: Path | None = None

    # Export to pdf in experiment directory/processed
    if experiment_dir is not None:
        processed_dir = get_processed_dir(Path(experiment_dir))
        plot_path = processed_dir / f"pressure_valve_timing_run{run_nr}.pdf"
        fig.savefig(plot_path)
        print(f"Plot saved to {plot_path}")

    if show:
        plt.show()
    else:
        plt.close(fig)

    return plot_path


def _read_run_log(run_log_path: Path) -> tuple[
        int,
        int,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray
]:
    """Read a run log and return metadata plus the five numeric data columns.

    Returns:
            (trigger_t0_us, run_nr, time_us,
             sol_valve_action, req_flow_lps, prop_valve_ma, press_bar)
    """
    run_nr: Optional[int] = None
    trigger_t0_us: Optional[int] = None
    header_found = False

    time_us: list[int] = []
    sol_valve_action: list[int] = []
    req_flow_lps: list[float] = []
    prop_valve_ma: list[float] = []
    press_bar: list[float] = []

    with run_log_path.open("r", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue

            key = row[0].strip()
            if key == "run_nr" and len(row) > 1:
                run_nr = int(row[1])
                continue

            if key == "trigger_t0_us" and len(row) > 1:
                trigger_t0_us = int(row[1])
                continue

            if key == "time_us":
                header_found = True
                continue

            if not header_found or len(row) < 4:
                continue

            time_us.append(int(row[0]))
            sol_valve_action.append(int(row[1]))
            req_flow_lps.append(float(row[2]))
            prop_valve_ma.append(float(row[3]))
            press_bar.append(float(row[4]))

    if run_nr is None:
        raise ValueError(f"Missing 'run_nr' in run log: {run_log_path}")

    if trigger_t0_us is None:
        raise ValueError(f"Missing 'trigger_t0_us' in run log: {run_log_path}")

    return (
        trigger_t0_us,
        run_nr,
        np.asarray(time_us, dtype=np.int64),
        np.asarray(sol_valve_action, dtype=np.int8),
        np.asarray(req_flow_lps, dtype=np.float64),
        np.asarray(prop_valve_ma, dtype=np.float64),
        np.asarray(press_bar, dtype=np.float64),
    )


def check_run_log_timing(run_log_path: Path) -> None:
    """Check the time between the steps in a run log for consistency."""
    (trigger_t0_us, run_nr, time_us, sol_valve_action, req_flow_lps,
     prop_valve_ma, press_bar) = _read_run_log(run_log_path)

    # Plot a histogram of the time differences between consecutive steps in the run log
    time_diffs_us = np.diff(time_us)
    plt.figure(figsize=(8, 4))
    plt.hist(time_diffs_us, bins=100, color="#0072B2", edgecolor="black")
    plt.title(f"Run log {run_log_path.name} timing differences")
    plt.xlabel("Time difference between steps (us)")
    plt.ylabel("Count")
    plt.grid(axis="y", alpha=0.75)

    plt.show()


if __name__ == "__main__":
    # plot_run_log(Path(
    # r".logs\run_logs\log_260910_101913.csv"), show=True)
    plot_run_log(Path(
        r".logs\run_logs\log_260910_095433.csv"), show=True, experiment_dir=Path("temp\processed2"))
